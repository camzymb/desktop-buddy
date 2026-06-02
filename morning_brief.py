"""Morning Brief — one short, warm summary to start the day.

Gathers three things and folds them into a single gentle paragraph, written to
be both shown in the buddy's speech bubble and spoken aloud (the display wiring
lives in the app; this module only composes the words):

    * Weather  — current temperature and sky for the user's area (weather.py),
                 falling back to a configurable default city if IP location
                 fails. If weather is unavailable, that line is simply omitted.
    * Calendar — today's events, via the existing read-only Google Calendar
                 integration (calendar_sync.py).
    * Email    — the few unread inbox emails worth attention, via the existing
                 read-only Gmail integration (gmail_sync.py).

The tone mirrors the buddy's other messages (see quotes.py): soft, caring, and
short — a kind friend checking in, never a status dashboard.

Test the wording for free, with fake data and no network or Gmail calls:

    .venv/bin/python morning_brief.py --mock   # free: sample brief, no API calls
    .venv/bin/python morning_brief.py          # real: live weather + calendar + email
"""

# === IMPORTS ===

import argparse
import os

import calendar_sync
import gmail_sync
import weather
from content_planner import load_env_file

# === CONSTANTS ===

# Who the buddy greets. Easy to change; this is Camille's companion.
GREETING_NAME = "Camille"

# Where to pretend the user is when IP-based location fails (e.g. on a VPN).
# Read from .env so it's configurable without touching code; defaults to Oslo.
DEFAULT_CITY_VAR = "WEATHER_DEFAULT_CITY"
FALLBACK_CITY = "Oslo"

# Small counts read warmer as words than digits ("Two events", not "2 events").
NUMBER_WORDS = {
    0: "No", 1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
    6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten",
}

# Only mention rain when it's high enough to actually plan around (grab an
# umbrella) — below this the brief stays a warm note rather than a forecast
# readout, so it skips the line. Lower it toward 0 to hear every chance.
RAIN_MENTION_THRESHOLD_PCT = 20


# === COMPOSITION ===

def compose_brief(
    name: str,
    current_weather: weather.Weather | None,
    events: list[calendar_sync.CalendarEvent] | None,
    important_email: list[gmail_sync.ImportantEmail] | None,
) -> str:
    """Fold the gathered pieces into one short, warm summary string.

    Each piece is optional: pass None for a source that couldn't be reached and
    its sentence is left out, so the brief still reads naturally. (An empty list
    is different from None — it means "reached it, nothing there" and produces a
    gentle "all clear" line.)
    """
    sentences = [f"Good morning {name}."]
    if current_weather is not None:
        sentences.append(_weather_sentence(current_weather))
    if events is not None:
        sentences.append(_calendar_sentence(events))
    if important_email is not None:
        sentences.append(_email_sentence(important_email))
    return " ".join(sentences)


def _weather_sentence(current_weather: weather.Weather) -> str:
    """One line about the weather, with a rain heads-up when an umbrella's worth it.

    Builds up from the temperature: adds the sky word when there is one, and a
    "chance of rain" clause only when the probability is both available and at or
    above RAIN_MENTION_THRESHOLD_PCT. Examples:
        "It's 19°C, cloudy, 60% chance of rain in Oslo."  (sky + worthwhile rain)
        "It's 19°C and cloudy in Oslo."                   (no/low rain chance)
        "It's 19°C in Oslo."                              (no sky word either)
    """
    pieces = [f"{current_weather.temperature_c}°C"]
    if current_weather.description:
        pieces.append(current_weather.description)
    rain_chance = current_weather.precipitation_probability
    if rain_chance is not None and rain_chance >= RAIN_MENTION_THRESHOLD_PCT:
        pieces.append(f"{rain_chance}% chance of rain")

    if len(pieces) == 1:
        body = pieces[0]
    elif len(pieces) == 2:
        body = f"{pieces[0]} and {pieces[1]}"
    else:
        body = ", ".join(pieces)  # temp, sky, rain — comma-joined, e.g. "19°C, cloudy, 60% chance of rain"
    return f"It's {body} in {current_weather.city}."


def _calendar_sentence(events: list[calendar_sync.CalendarEvent]) -> str:
    """One line about today's events, gentle when the day is open."""
    if not events:
        return "Nothing on your calendar today — enjoy the open space."

    first = events[0]
    if len(events) == 1:
        if first.all_day:
            return "One thing on your calendar today — it's all day."
        return f"One thing on your calendar today, at {first.start}."

    lead = "first one's all day" if first.all_day else f"first at {first.start}"
    return f"{_count_word(len(events))} events today, {lead}."


def _email_sentence(important_email: list[gmail_sync.ImportantEmail]) -> str:
    """One line about email worth a look, warm and quiet when there's none.

    Names everyone when there are one or two; past that, names the first and
    says "including" so the line reads complete rather than cut off.
    """
    if not important_email:
        return "Nothing urgent in your inbox. 🤍"
    if len(important_email) == 1:
        return f"One email worth a look — from {important_email[0].sender}."
    if len(important_email) == 2:
        return (
            f"Two emails worth a look — from "
            f"{important_email[0].sender} and {important_email[1].sender}."
        )
    return (
        f"{_count_word(len(important_email))} emails worth a look, "
        f"including one from {important_email[0].sender}."
    )


def _count_word(count: int) -> str:
    """Spell small counts as words for warmth, falling back to digits past ten."""
    return NUMBER_WORDS.get(count, str(count))


# === GATHERING ===

def gather_brief() -> str:
    """Gather live weather + calendar + email and return the composed brief.

    Each source degrades gracefully: weather returns None if unavailable, and a
    calendar or Gmail hiccup drops just that line (None) rather than crashing the
    whole brief.
    """
    load_env_file()
    default_city = os.environ.get(DEFAULT_CITY_VAR, "").strip() or FALLBACK_CITY

    current_weather = weather.get_weather(default_city)
    events = _safe_events()
    important_email = _safe_important_email()
    return compose_brief(GREETING_NAME, current_weather, events, important_email)


def _safe_events() -> list[calendar_sync.CalendarEvent] | None:
    """Today's events, or None if the calendar can't be reached right now."""
    try:
        return calendar_sync.fetch_todays_events()
    except calendar_sync.CalendarSyncError:
        return None


def _safe_important_email() -> list[gmail_sync.ImportantEmail] | None:
    """Today's important email, or None if Gmail can't be reached right now."""
    try:
        return gmail_sync.fetch_important_today()
    except gmail_sync.GmailSyncError:
        return None


# === MOCK (free, offline) ===

def mock_brief() -> str:
    """Compose the brief from fixed sample data — no network or Gmail calls.

    Lets the wording, length, and tone be checked at zero cost before wiring the
    brief into the buddy's bubble and voice.
    """
    sample_weather = weather.Weather(
        city="Oslo", temperature_c=3, description="cloudy", precipitation_probability=60
    )
    sample_events = [
        calendar_sync.CalendarEvent(
            title="Standup", start="10:00 AM", end="10:15 AM",
            all_day=False, past=False, start_dt=None, event_id="mock-1",
        ),
        calendar_sync.CalendarEvent(
            title="Client call", start="2:00 PM", end="3:00 PM",
            all_day=False, past=False, start_dt=None, event_id="mock-2",
        ),
    ]
    sample_email = [
        gmail_sync.ImportantEmail(sender="Jana at Bloomreach", subject="Re: collab idea"),
        gmail_sync.ImportantEmail(sender="Mark Reyes", subject="Quick question about your rates"),
    ]
    return compose_brief(GREETING_NAME, sample_weather, sample_events, sample_email)


# === ENTRY POINT ===

def main() -> None:
    """Print the morning brief — sample data with --mock, otherwise live."""
    parser = argparse.ArgumentParser(description="Compose the buddy's morning brief.")
    parser.add_argument(
        "--mock", action="store_true",
        help="use fixed sample data (no network or Gmail calls) — free to run",
    )
    args = parser.parse_args()
    print(mock_brief() if args.mock else gather_brief())


if __name__ == "__main__":
    main()
