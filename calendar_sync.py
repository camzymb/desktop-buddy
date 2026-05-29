"""Read-only Google Calendar access for the buddy.

Fetches today's events from the user's primary Google Calendar using the
official Google client libraries. The OAuth scope is restricted to
`calendar.readonly`, so this module can *only* read the calendar — it can
never create, edit, or delete events.

Secrets stay local: the OAuth client lives in `credentials.json` and the
saved sign-in lives in `token.json`; both are gitignored and their contents
are never printed. On first run a browser consent flow creates `token.json`;
later runs reuse it and refresh silently when it expires.

This is a standalone module for now — run it directly to print today's events
and confirm calendar access before it gets wired into the app:

    .venv/bin/python calendar_sync.py
"""

# === IMPORTS ===

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent

# OAuth client secret (downloaded from Google Cloud) and the cached sign-in
# token created after the first consent. Both are gitignored.
CREDENTIALS_PATH = PROJECT_DIR / "credentials.json"
TOKEN_PATH = PROJECT_DIR / "token.json"

# Read-only scope: the app can read the calendar but never modify it.
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Which calendar to read, and a sane cap on how many events to pull per day.
PRIMARY_CALENDAR_ID = "primary"
MAX_EVENTS = 50

# Human-friendly clock format, e.g. "2:00 PM" (no leading zero on the hour).
TIME_FORMAT = "%-I:%M %p"


# === ERRORS ===

class CalendarSyncError(Exception):
    """A user-friendly calendar problem (missing setup, offline, expired auth).

    Raised with a message safe to show directly to the user; it never contains
    tokens or other secrets.
    """


# === DATA MODEL ===

@dataclass(frozen=True)
class CalendarEvent:
    """One calendar event, with start/end already formatted for display.

    `past` is True when the event's end time is already behind us (used to
    show finished events as done). All-day events are never marked past.

    `start_dt` is the actual start as a timezone-aware datetime (None for
    all-day events), used to schedule reminders; `event_id` is the calendar's
    stable id, used to remind about each event only once. The formatted `start`
    string stays for display.
    """
    title: str
    start: str
    end: str
    all_day: bool
    past: bool
    start_dt: datetime | None
    event_id: str


# === AUTHENTICATION ===

def _load_credentials() -> Credentials:
    """Return valid read-only credentials, signing in or refreshing as needed.

    Reuses token.json when possible, refreshes it silently when expired, and
    only falls back to the browser consent flow when there's no usable token.
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
            raise CalendarSyncError(
                "Your saved Google sign-in has expired. Delete token.json and "
                "run again to sign in."
            ) from error
        _save_token(credentials)
        return credentials

    return _run_consent_flow()


def _run_consent_flow() -> Credentials:
    """Open the browser for Google sign-in and cache the resulting token."""
    if not CREDENTIALS_PATH.exists():
        raise CalendarSyncError(
            "Missing credentials.json. Download your OAuth client from the "
            "Google Cloud console and place it in the project root."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    credentials = flow.run_local_server(port=0)
    _save_token(credentials)
    return credentials


def _save_token(credentials: Credentials) -> None:
    """Write the sign-in token to token.json, readable only by the user."""
    TOKEN_PATH.write_text(credentials.to_json())
    TOKEN_PATH.chmod(0o600)


# === FETCHING ===

def fetch_todays_events() -> list[CalendarEvent]:
    """Return today's events from the primary calendar, ordered by start time.

    Raises CalendarSyncError with a friendly message if the calendar can't be
    reached, the sign-in is missing/expired, or the API returns an error.
    """
    credentials = _load_credentials()
    time_min, time_max = _todays_window()

    try:
        service = build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        )
        response = (
            service.events()
            .list(
                calendarId=PRIMARY_CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=MAX_EVENTS,
            )
            .execute()
        )
    except HttpError as error:
        raise CalendarSyncError(
            f"Google Calendar returned an error (HTTP {error.resp.status})."
        ) from error
    except (GoogleAuthError, OSError) as error:
        raise CalendarSyncError(
            "Couldn't reach Google Calendar. Check your internet connection "
            "and try again."
        ) from error

    return [_to_event(item) for item in response.get("items", [])]


def _todays_window() -> tuple[str, str]:
    """Return today's [start, end) as RFC3339 timestamps in the local timezone."""
    now_local = datetime.now().astimezone()
    start_of_day = datetime.combine(now_local.date(), time.min, tzinfo=now_local.tzinfo)
    start_of_next_day = start_of_day + timedelta(days=1)
    return start_of_day.isoformat(), start_of_next_day.isoformat()


# === FORMATTING ===

def _to_event(item: dict) -> CalendarEvent:
    """Convert one raw API event into a display-ready CalendarEvent."""
    title = item.get("summary", "(no title)")
    event_id = item.get("id", "")
    start = item["start"]
    end = item["end"]

    # All-day events carry a "date" instead of a "dateTime"; with no start_dt
    # the reminder logic never gives them a 15-minute countdown.
    if "date" in start:
        return CalendarEvent(
            title=title, start="All day", end="All day", all_day=True, past=False,
            start_dt=None, event_id=event_id,
        )

    start_iso = start["dateTime"]
    return CalendarEvent(
        title=title,
        start=_format_time(start_iso),
        end=_format_time(end["dateTime"]),
        all_day=False,
        past=_has_passed(end["dateTime"]),
        start_dt=datetime.fromisoformat(start_iso).astimezone(),
        event_id=event_id,
    )


def _format_time(iso_datetime: str) -> str:
    """Format an ISO datetime string as a local clock time, e.g. "2:00 PM"."""
    local_time = datetime.fromisoformat(iso_datetime).astimezone()
    return local_time.strftime(TIME_FORMAT)


def _has_passed(iso_datetime: str) -> bool:
    """Return True if the given ISO datetime is already in the past."""
    end_time = datetime.fromisoformat(iso_datetime).astimezone()
    return end_time < datetime.now().astimezone()


# === REMINDERS ===

def due_reminders(
    events: list[CalendarEvent],
    now: datetime,
    lead: timedelta,
    already_reminded: set[str],
) -> list[CalendarEvent]:
    """Return events starting within `lead` of `now` that still need a reminder.

    Pure scheduling logic, kept here and Qt-free so it's easy to read and test.
    An event qualifies when:

      * it has a real start time — all-day events (start_dt is None) are skipped,
        so they never trigger a countdown reminder;
      * its start is still ahead of us but no more than `lead` away (events that
        already started are not "coming up"); and
      * its id isn't already in `already_reminded`, so each event nudges once.

    Results keep the input order (events arrive sorted by start time), so the
    soonest event is first.
    """
    lead_seconds = lead.total_seconds()
    due: list[CalendarEvent] = []
    for event in events:
        if event.start_dt is None or event.event_id in already_reminded:
            continue
        seconds_until_start = (event.start_dt - now).total_seconds()
        if 0 < seconds_until_start <= lead_seconds:
            due.append(event)
    return due


# === TEST ENTRY POINT ===

def _print_todays_events() -> None:
    """Print today's events to the terminal (or a friendly note if there's a problem)."""
    try:
        events = fetch_todays_events()
    except CalendarSyncError as error:
        print(f"⚠️  {error}")
        return

    if not events:
        print("No events on your calendar today. 🤍")
        return

    print(f"Today's events ({len(events)}):")
    for event in events:
        when = "all day" if event.all_day else f"{event.start} – {event.end}"
        done_marker = " ✓ done" if event.past else ""
        print(f"  • {event.title} — {when}{done_marker}")


if __name__ == "__main__":
    _print_todays_events()
