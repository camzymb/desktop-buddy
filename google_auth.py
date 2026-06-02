"""Shared Google OAuth sign-in for the buddy's read-only integrations.

Gmail and Calendar each need the same dance: reuse a saved sign-in token when
possible, refresh it silently when it has expired, and only fall back to the
browser consent flow when there is no usable token. That logic is identical and
security-sensitive, so it lives here once rather than being copied per module.

Each integration keeps its OWN token file, scope, error type, and wording — those
are passed in, so this helper imposes no policy of its own. It never widens
access: whatever scope the caller hands in is the scope used (Gmail stays
`gmail.readonly`, Calendar stays `calendar.readonly`).

Secrets stay local: tokens are written with owner-only permissions and their
contents are never printed.
"""

# === IMPORTS ===

from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


# === CONSTANTS ===

# Shown when credentials.json (the OAuth client) is missing. Identical for every
# integration, so it lives here rather than being passed in.
MISSING_CREDENTIALS_MESSAGE = (
    "Missing credentials.json. Download your OAuth client from the "
    "Google Cloud console and place it in the project root."
)


# === AUTHENTICATION ===

def load_credentials(
    token_path: Path,
    scopes: list[str],
    credentials_path: Path,
    error_class: type[Exception],
    expired_message: str,
) -> Credentials:
    """Return valid credentials for `scopes`, signing in or refreshing as needed.

    Reuses the token at `token_path` when possible, refreshes it silently when
    expired, and only falls back to the browser consent flow when there is no
    usable token. On an unrecoverable expiry, raises `error_class(expired_message)`
    so the caller's own user-facing error type and wording are preserved.
    """
    credentials: Credentials | None = None
    if token_path.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_path), scopes)
        except ValueError:
            # Corrupt or incompatible token file — treat as no token.
            credentials = None

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            raise error_class(expired_message) from error
        _save_token(credentials, token_path)
        return credentials

    return _run_consent_flow(token_path, scopes, credentials_path, error_class)


def _run_consent_flow(
    token_path: Path,
    scopes: list[str],
    credentials_path: Path,
    error_class: type[Exception],
) -> Credentials:
    """Open the browser for Google sign-in and cache the resulting token."""
    if not credentials_path.exists():
        raise error_class(MISSING_CREDENTIALS_MESSAGE)
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), scopes)
    credentials = flow.run_local_server(port=0)
    _save_token(credentials, token_path)
    return credentials


def _save_token(credentials: Credentials, token_path: Path) -> None:
    """Write the sign-in token to `token_path`, readable only by the user."""
    token_path.write_text(credentials.to_json())
    token_path.chmod(0o600)
