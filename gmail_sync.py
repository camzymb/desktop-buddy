"""Read-only Gmail access for the buddy's Morning Brief.

Counts today's unread emails using the official Google client libraries. The
OAuth scope is restricted to `gmail.readonly`, so this module can *only* read
mail — it can never send, delete, label, or modify anything.

It reuses the same OAuth client (`credentials.json`) as the calendar, but keeps
its own sign-in token (`token_gmail.json`) holding only the Gmail scope. That
way the working calendar sign-in is never disturbed, and each part of the app
holds the least access it needs.

Secrets stay local: both `credentials.json` and `token_gmail.json` are
gitignored and their contents are never printed. On first run a browser consent
flow creates `token_gmail.json`; later runs reuse it and refresh silently when
it expires.

This is a standalone test for now — run it directly to confirm Gmail access
before it gets wired into the Morning Brief:

    .venv/bin/python gmail_sync.py
"""

# === IMPORTS ===

import base64
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path

from google.auth.exceptions import GoogleAuthError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import google_auth

logger = logging.getLogger(__name__)


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent

# Reuse the calendar's OAuth client, but keep a separate Gmail-only token so the
# working calendar sign-in (token.json) is never touched. Both are gitignored.
CREDENTIALS_PATH = PROJECT_DIR / "credentials.json"
TOKEN_PATH = PROJECT_DIR / "token_gmail.json"

# Read-only scope: the app can read mail but never send, delete, or modify it.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# We only look at personal mail sitting unread in the inbox today — not spam,
# not promotions buried in other tabs. A sane cap keeps the request small.
MAILBOX_USER = "me"
MAX_MESSAGES = 100

# --- Reply drafting ---
# The draft assistant (draft_assistant.py) reuses the SAME read-only access and
# the SAME importance filter below; the only difference is that, for the few
# emails the filter already approves, it also reads that one message's body so a
# relevant reply can be drafted. Reading bodies is still squarely within the
# gmail.readonly scope — nothing here can ever send, delete, or modify mail.

# Never draft for more than this many emails in one pass — bounds both the work
# and (since each becomes exactly one cheap API call downstream) the cost.
MAX_REPLY_DRAFTS = 10

# Cap the body text we hand to the drafting model, so one very long email can't
# inflate token cost. A few thousand characters is plenty of context for a reply.
BODY_CHAR_LIMIT = 4000

# --- Importance filtering ---
# The brief should surface only mail from a person where a reply is plausibly
# expected, and stay quiet about noise. The rule of thumb: when in doubt, treat
# as NOT important — under-surfacing is fine, surfacing noise is the failure.

# Only ask Gmail for the headers we need to judge importance (keeps it cheap and
# means we never download message bodies / personal content).
METADATA_HEADERS = ["From", "Subject", "List-Unsubscribe"]

# Gmail's own tab labels we skip entirely: marketing and social notifications.
NOISE_LABELS = frozenset({"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"})

# Sender fragments that mark automated / do-not-reply mail no human awaits.
AUTOMATED_SENDER_MARKERS = (
    "no-reply", "noreply", "no_reply", "donotreply", "do-not-reply",
    "notifications", "notification@", "mailer-daemon", "automated", "auto-confirm",
)

# Subject prefixes that mark a forwarded message (we skip forwards).
FORWARD_PREFIXES = ("fwd:", "fw:")

# Phrases that typically mark a job-application rejection (skipped — gentle).
REJECTION_PHRASES = (
    "unfortunately", "we regret", "regret to inform", "not moving forward",
    "won't be moving forward", "will not be moving forward", "decided not to",
    "other candidates", "position has been filled", "no longer under consideration",
    "not be progressing", "was unsuccessful", "not selected",
)


# === ERRORS ===

class GmailSyncError(Exception):
    """A user-friendly Gmail problem (missing setup, offline, expired auth).

    Raised with a message safe to show directly to the user; it never contains
    tokens or other secrets.
    """


# === DATA MODEL ===

@dataclass(frozen=True)
class ImportantEmail:
    """One inbox email worth the user's attention, ready for display.

    `sender` is the person's display name (falling back to their address), and
    `subject` is the email's subject line. No body or address book data is kept.
    """
    sender: str
    subject: str


@dataclass(frozen=True)
class ReplyableEmail:
    """An important email plus the bits needed to draft and address a reply.

    Carries the same `sender_name`/`subject` an `ImportantEmail` would, plus the
    sender's `sender_email` (so a reply can be addressed back to them) and the
    message `body` (capped at BODY_CHAR_LIMIT) the model reads to draft a
    relevant response. Only produced for emails the importance filter already
    approved — never for the skipped noise. Stays local; never written or logged.
    """
    sender_name: str
    sender_email: str
    subject: str
    body: str


# === AUTHENTICATION ===

def _load_credentials() -> Credentials:
    """Return valid read-only credentials, signing in or refreshing as needed.

    Delegates to the shared `google_auth.load_credentials`, passing this module's
    own Gmail-only token file, scope, error type, and expiry wording so behavior
    is unchanged — the scope stays `gmail.readonly`, read-only.
    """
    return google_auth.load_credentials(
        token_path=TOKEN_PATH,
        scopes=SCOPES,
        credentials_path=CREDENTIALS_PATH,
        error_class=GmailSyncError,
        expired_message=(
            "Your saved Gmail sign-in has expired. Delete token_gmail.json "
            "and run again to sign in."
        ),
    )


# === FETCHING ===

def count_unread_today() -> int:
    """Return how many emails are unread in the inbox so far today.

    "Today" means since local midnight. Raises GmailSyncError with a friendly
    message if Gmail can't be reached, the sign-in is missing/expired, or the
    API returns an error.
    """
    credentials = _load_credentials()
    query = f"is:unread in:inbox after:{_local_midnight_epoch()}"

    try:
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        response = (
            service.users()
            .messages()
            .list(userId=MAILBOX_USER, q=query, maxResults=MAX_MESSAGES)
            .execute()
        )
    except HttpError as error:
        logger.warning("Gmail request failed: HTTP %s", error.resp.status)
        raise GmailSyncError(
            f"Gmail returned an error (HTTP {error.resp.status})."
        ) from error
    except (GoogleAuthError, OSError) as error:
        logger.warning(
            "Gmail request failed: could not reach Gmail (%s)", type(error).__name__
        )
        raise GmailSyncError(
            "Couldn't reach Gmail. Check your internet connection and try again."
        ) from error

    return len(response.get("messages", []))


def _local_midnight_epoch() -> int:
    """Return today's local midnight as a Unix timestamp (Gmail's `after:` filter)."""
    now_local = datetime.now().astimezone()
    start_of_day = datetime.combine(now_local.date(), time.min, tzinfo=now_local.tzinfo)
    return int(start_of_day.timestamp())


def fetch_important_today() -> list[ImportantEmail]:
    """Return today's unread inbox emails that look worth the user's attention.

    Reads each unread message's headers (never its body), then keeps only mail
    from a person where a reply is plausibly expected — filtering out
    newsletters, automated senders, promotions/social, forwards, and rejections
    (see `_is_important`). Order matches Gmail's (newest first).

    Raises GmailSyncError with a friendly message if Gmail can't be reached, the
    sign-in is missing/expired, or the API returns an error.
    """
    credentials = _load_credentials()
    # Drop the bulk of the noise at the source; finer rules run per-message below.
    query = (
        f"is:unread in:inbox after:{_local_midnight_epoch()} "
        "-category:promotions -category:social"
    )

    try:
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        listing = (
            service.users()
            .messages()
            .list(userId=MAILBOX_USER, q=query, maxResults=MAX_MESSAGES)
            .execute()
        )
        important: list[ImportantEmail] = []
        for stub in listing.get("messages", []):
            message = (
                service.users()
                .messages()
                .get(
                    userId=MAILBOX_USER,
                    id=stub["id"],
                    format="metadata",
                    metadataHeaders=METADATA_HEADERS,
                )
                .execute()
            )
            headers = _headers_to_dict(message)
            if _is_important(headers, message.get("labelIds", [])):
                important.append(
                    ImportantEmail(
                        sender=_sender_name(headers.get("from", "")),
                        subject=_decode_header(headers.get("subject", "")) or "(no subject)",
                    )
                )
        return important
    except HttpError as error:
        logger.warning("Gmail request failed: HTTP %s", error.resp.status)
        raise GmailSyncError(
            f"Gmail returned an error (HTTP {error.resp.status})."
        ) from error
    except (GoogleAuthError, OSError) as error:
        logger.warning(
            "Gmail request failed: could not reach Gmail (%s)", type(error).__name__
        )
        raise GmailSyncError(
            "Couldn't reach Gmail. Check your internet connection and try again."
        ) from error


def fetch_important_for_reply(max_emails: int = MAX_REPLY_DRAFTS) -> list[ReplyableEmail]:
    """Return today's reply-worthy emails, each with the body needed to draft one.

    Reuses the exact same listing and importance filter as `fetch_important_today`
    (`_is_important` — newsletters, automated senders, promotions/social,
    forwards, and rejections all skipped). The only addition: for each email the
    filter approves, it then reads that one message's body (capped at
    BODY_CHAR_LIMIT) and the sender's address, so a relevant reply can be drafted
    and addressed back. To honor least-access, noise is judged from cheap
    metadata FIRST and only the approved emails ever have their body downloaded.
    At most `max_emails` are returned (newest first), bounding the work and cost.

    Raises GmailSyncError with a friendly message if Gmail can't be reached, the
    sign-in is missing/expired, or the API returns an error.
    """
    credentials = _load_credentials()
    query = (
        f"is:unread in:inbox after:{_local_midnight_epoch()} "
        "-category:promotions -category:social"
    )

    try:
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        listing = (
            service.users()
            .messages()
            .list(userId=MAILBOX_USER, q=query, maxResults=MAX_MESSAGES)
            .execute()
        )
        replyable: list[ReplyableEmail] = []
        for stub in listing.get("messages", []):
            if len(replyable) >= max_emails:
                break
            # Cheap metadata pass first: decide importance WITHOUT downloading the
            # body, so the noise we skip never has its contents read.
            metadata = (
                service.users()
                .messages()
                .get(
                    userId=MAILBOX_USER,
                    id=stub["id"],
                    format="metadata",
                    metadataHeaders=METADATA_HEADERS,
                )
                .execute()
            )
            headers = _headers_to_dict(metadata)
            if not _is_important(headers, metadata.get("labelIds", [])):
                continue

            # Approved: now (and only now) read the full message for its body.
            full = (
                service.users()
                .messages()
                .get(userId=MAILBOX_USER, id=stub["id"], format="full")
                .execute()
            )
            from_header = _headers_to_dict(full).get("from", "")
            _, sender_email = parseaddr(_decode_header(from_header))
            replyable.append(
                ReplyableEmail(
                    sender_name=_sender_name(from_header),
                    sender_email=sender_email,
                    subject=_decode_header(headers.get("subject", "")) or "(no subject)",
                    body=_extract_body(full.get("payload", {})),
                )
            )
        return replyable
    except HttpError as error:
        logger.warning("Gmail request failed: HTTP %s", error.resp.status)
        raise GmailSyncError(
            f"Gmail returned an error (HTTP {error.resp.status})."
        ) from error
    except (GoogleAuthError, OSError) as error:
        logger.warning(
            "Gmail request failed: could not reach Gmail (%s)", type(error).__name__
        )
        raise GmailSyncError(
            "Couldn't reach Gmail. Check your internet connection and try again."
        ) from error


# === IMPORTANCE FILTERING ===

def _is_important(headers: dict[str, str], label_ids: list[str]) -> bool:
    """Decide whether one email is worth surfacing, from its headers and labels.

    Returns False (skip) for anything that smells automated or bulk; True only
    for what's left — likely real, reply-worthy mail. Errs toward skipping.
    """
    if any(label in NOISE_LABELS for label in label_ids):
        return False
    # A List-Unsubscribe header is the tell-tale sign of bulk/marketing mail.
    if headers.get("list-unsubscribe"):
        return False

    sender = headers.get("from", "").lower()
    if any(marker in sender for marker in AUTOMATED_SENDER_MARKERS):
        return False

    subject = _decode_header(headers.get("subject", "")).lower().strip()
    if subject.startswith(FORWARD_PREFIXES):
        return False
    if any(phrase in subject for phrase in REJECTION_PHRASES):
        return False

    return True


def _headers_to_dict(message: dict) -> dict[str, str]:
    """Flatten a message's header list into a lower-cased name → value map."""
    headers = message.get("payload", {}).get("headers", [])
    return {item["name"].lower(): item["value"] for item in headers}


def _extract_body(payload: dict) -> str:
    """Return readable plain text from a message payload, capped and tidied.

    Prefers the email's text/plain part; if it's HTML-only, falls back to the
    text/html part with tags crudely stripped. The result is whitespace-collapsed
    and truncated to BODY_CHAR_LIMIT so a long thread can't inflate token cost.
    Returns "" when no text part is found (the caller drafts from subject alone).
    """
    text = _collect_part_text(payload, "text/plain")
    if not text:
        html = _collect_part_text(payload, "text/html")
        text = re.sub(r"<[^>]+>", " ", html) if html else ""
    # Collapse runs of whitespace/blank lines into single spaces/newlines so the
    # drafting prompt stays compact and readable.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:BODY_CHAR_LIMIT]


def _collect_part_text(part: dict, mime_type: str) -> str:
    """Find the first body part of the given MIME type, walking nested parts.

    Gmail nests multipart emails (e.g. multipart/alternative holding both a
    text/plain and a text/html copy), so this recurses to locate the wanted type
    and decodes its URL-safe base64 data to text.
    """
    if part.get("mimeType") == mime_type:
        data = part.get("body", {}).get("data")
        if data:
            return _decode_base64url(data)
    for sub_part in part.get("parts", []) or []:
        found = _collect_part_text(sub_part, mime_type)
        if found:
            return found
    return ""


def _decode_base64url(data: str) -> str:
    """Decode Gmail's URL-safe base64 body data to text, tolerating bad bytes."""
    padded = data + "=" * (-len(data) % 4)  # Gmail omits base64 padding
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _sender_name(from_header: str) -> str:
    """Return a sender's display name, falling back to their email address."""
    name, address = parseaddr(_decode_header(from_header))
    return name.strip() or address or "someone"


def _decode_header(raw: str) -> str:
    """Decode a possibly MIME-encoded header (e.g. "=?UTF-8?...?=") to plain text."""
    if not raw:
        return ""
    decoded = ""
    for text, charset in decode_header(raw):
        if isinstance(text, bytes):
            decoded += text.decode(charset or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


# === TEST ENTRY POINT ===

def _print_summary() -> None:
    """Print today's unread count and the emails worth a look (or a friendly note)."""
    try:
        count = count_unread_today()
        important = fetch_important_today()
    except GmailSyncError as error:
        print(f"⚠️  {error}")
        return

    print(f"You have {count} unread emails today.")
    if not important:
        print("Nothing in there looks urgent. 🤍")
        return
    print(f"{len(important)} worth a look:")
    for email in important:
        print(f"  • {email.sender} — {email.subject}")


if __name__ == "__main__":
    _print_summary()
