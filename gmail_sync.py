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

from dataclasses import dataclass
from datetime import datetime, time
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


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


# === AUTHENTICATION ===

def _load_credentials() -> Credentials:
    """Return valid read-only credentials, signing in or refreshing as needed.

    Reuses token_gmail.json when possible, refreshes it silently when expired,
    and only falls back to the browser consent flow when there's no usable token.
    """
    credentials: Credentials | None = None
    if TOKEN_PATH.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except ValueError:
            # Corrupt or incompatible token file — treat as no token.
            credentials = None

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            raise GmailSyncError(
                "Your saved Gmail sign-in has expired. Delete token_gmail.json "
                "and run again to sign in."
            ) from error
        _save_token(credentials)
        return credentials

    return _run_consent_flow()


def _run_consent_flow() -> Credentials:
    """Open the browser for Google sign-in and cache the resulting token."""
    if not CREDENTIALS_PATH.exists():
        raise GmailSyncError(
            "Missing credentials.json. Download your OAuth client from the "
            "Google Cloud console and place it in the project root."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    credentials = flow.run_local_server(port=0)
    _save_token(credentials)
    return credentials


def _save_token(credentials: Credentials) -> None:
    """Write the sign-in token to token_gmail.json, readable only by the user."""
    TOKEN_PATH.write_text(credentials.to_json())
    TOKEN_PATH.chmod(0o600)


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
        raise GmailSyncError(
            f"Gmail returned an error (HTTP {error.resp.status})."
        ) from error
    except (GoogleAuthError, OSError) as error:
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
        raise GmailSyncError(
            f"Gmail returned an error (HTTP {error.resp.status})."
        ) from error
    except (GoogleAuthError, OSError) as error:
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
