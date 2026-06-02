"""Best-effort local weather for the buddy's Morning Brief.

Finds the user's approximate city from their IP address and looks up the
current temperature — both via free services that need no API key:

    * location  → ipapi.co
    * weather   → open-meteo.com (with its free geocoder for the fallback city)

IP-based location is approximate and fails behind a VPN, so if the lookup
fails this falls back to a configurable default city (passed in by the caller).
Nothing here ever raises: every network problem returns None, so the Morning
Brief can simply skip the weather line and still show calendar and email.

No personal data is stored or sent anywhere — the only outbound requests are
the user's own IP geolocation and a public weather lookup.

Run directly to print the current weather (a free, no-key request):

    .venv/bin/python weather.py
"""

# === IMPORTS ===

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

# === CONSTANTS ===

# Keep network calls snappy — a morning brief shouldn't hang on a slow lookup.
REQUEST_TIMEOUT_SECONDS = 6
USER_AGENT = "desktop-buddy/1.0"

# Free, no-API-key endpoints.
IP_LOCATION_URL = "https://ipapi.co/json/"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=en&format=json"
WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code"
    # Rain chance only exists in the HOURLY forecast, not the current block, so
    # we also pull today's hourly probabilities and read the current hour's.
    "&hourly=precipitation_probability&forecast_days=1"
)

# WMO weather codes → short, gentle words for the brief. Unlisted codes fall
# back to no description (the brief then just states the temperature).
WEATHER_DESCRIPTIONS: dict[int, str] = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "cloudy",
    45: "foggy",
    48: "foggy",
    51: "drizzly",
    53: "drizzly",
    55: "drizzly",
    56: "icy",
    57: "icy",
    61: "rainy",
    63: "rainy",
    65: "rainy",
    66: "icy",
    67: "icy",
    71: "snowy",
    73: "snowy",
    75: "snowy",
    77: "snowy",
    80: "rainy",
    81: "rainy",
    82: "rainy",
    85: "snowy",
    86: "snowy",
    95: "stormy",
    96: "stormy",
    99: "stormy",
}


# === DATA MODEL ===

@dataclass(frozen=True)
class Weather:
    """Current weather, ready for display: city name, °C, a short sky word, and
    the chance of rain (%) for the current hour (None when unavailable)."""
    city: str
    temperature_c: int
    description: str
    precipitation_probability: int | None = None


# === NETWORK HELPER ===

def _get_json(url: str) -> dict | None:
    """Fetch and parse JSON from a URL, returning None on any problem.

    Deliberately swallows every error (timeout, offline, bad response, bad
    JSON) so callers can treat weather as optional and never crash.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


# === LOOKUPS ===

def _locate_from_ip() -> tuple[str, float, float] | None:
    """Return (city, latitude, longitude) from the IP address, or None."""
    data = _get_json(IP_LOCATION_URL)
    if not data or data.get("error"):
        return None
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    if latitude is None or longitude is None:
        return None
    city = data.get("city") or "your area"
    return city, float(latitude), float(longitude)


def _geocode_city(city: str) -> tuple[str, float, float] | None:
    """Return (city, latitude, longitude) for a named city, or None."""
    data = _get_json(GEOCODE_URL.format(city=urllib.request.quote(city)))
    results = (data or {}).get("results") or []
    if not results:
        return None
    top = results[0]
    if "latitude" not in top or "longitude" not in top:
        return None
    return top.get("name", city), float(top["latitude"]), float(top["longitude"])


def _current_weather(
    latitude: float, longitude: float
) -> tuple[float, int, int | None] | None:
    """Return (temperature_c, weather_code, rain_chance_pct) for a place, or None.

    The rain chance is the precipitation probability for the current hour; it's
    None when that data isn't in the response, so the brief just leaves it off.
    """
    data = _get_json(WEATHER_URL.format(lat=latitude, lon=longitude))
    current = (data or {}).get("current") or {}
    if "temperature_2m" not in current or "weather_code" not in current:
        return None
    rain_chance = _current_rain_chance(data, current.get("time"))
    return float(current["temperature_2m"]), int(current["weather_code"]), rain_chance


def _current_rain_chance(data: dict | None, current_time: str | None) -> int | None:
    """Pull the precipitation probability (%) for the current hour, or None.

    Open-Meteo reports rain chance only in the hourly forecast, so we match the
    'current' timestamp to its hour and read that probability. Any gap in the
    data (missing field, mismatched lengths, no matching hour, a null value)
    yields None, and the brief omits the rain note rather than guessing.
    """
    hourly = (data or {}).get("hourly") or {}
    times = hourly.get("time") or []
    chances = hourly.get("precipitation_probability") or []
    if not current_time or len(times) != len(chances):
        return None
    current_hour = current_time[:13]  # "YYYY-MM-DDTHH" — drop the minutes
    for time_str, chance in zip(times, chances):
        if isinstance(time_str, str) and time_str[:13] == current_hour and chance is not None:
            return int(chance)
    return None


# === PUBLIC API ===

def get_weather(default_city: str) -> Weather | None:
    """Return current weather for the user's location, or None if unavailable.

    Tries IP-based location first; on failure (e.g. VPN) falls back to the
    given default city. Returns None only if both location and the weather
    lookup fail — the caller then simply omits the weather line.
    """
    location = _locate_from_ip() or _geocode_city(default_city)
    if location is None:
        return None

    city, latitude, longitude = location
    reading = _current_weather(latitude, longitude)
    if reading is None:
        return None

    temperature_c, weather_code, rain_chance = reading
    return Weather(
        city=city,
        temperature_c=round(temperature_c),
        description=WEATHER_DESCRIPTIONS.get(weather_code, ""),
        precipitation_probability=rain_chance,
    )


# === TEST ENTRY POINT ===

def _print_weather() -> None:
    """Print the current weather (or a friendly note if it's unavailable)."""
    current = get_weather("Oslo")
    if current is None:
        print("Couldn't reach a weather service right now. 🤍")
        return
    parts = [f"{current.temperature_c}°C"]
    if current.description:
        parts.append(current.description)
    if current.precipitation_probability is not None:
        parts.append(f"{current.precipitation_probability}% chance of rain")
    print(f"{', '.join(parts)} in {current.city}.")


if __name__ == "__main__":
    _print_weather()
