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

from datetime import datetime, time
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

# We only count personal mail sitting unread in the inbox today — not spam,
# not promotions buried in other tabs. A sane cap keeps the request small.
MAILBOX_USER = "me"
MAX_MESSAGES = 100


# === ERRORS ===

class GmailSyncError(Exception):
    """A user-friendly Gmail problem (missing setup, offline, expired auth).

    Raised with a message safe to show directly to the user; it never contains
    tokens or other secrets.
    """


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


# === TEST ENTRY POINT ===

def _print_unread_count() -> None:
    """Print today's unread count (or a friendly note if there's a problem)."""
    try:
        count = count_unread_today()
    except GmailSyncError as error:
        print(f"⚠️  {error}")
        return

    print(f"You have {count} unread emails today.")


if __name__ == "__main__":
    _print_unread_count()
