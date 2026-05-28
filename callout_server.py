"""Local web server for the daily summary callout.

Serves the static callout/ page and exposes a single JSON endpoint,
GET /api/today, that returns today's real Google Calendar events via
calendar_sync. The page's JavaScript fetches that endpoint and fills in the
"Today's Events" section; the other sections remain placeholders for now.

The server binds to 127.0.0.1 only, so your calendar data is served just to
this machine and never exposed on the network. Calendar credentials/tokens
stay local and gitignored — none of that data is written into the page or
the repo.

Run it, then open the printed URL in your browser:

    .venv/bin/python callout_server.py
"""

# === IMPORTS ===

import json
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from calendar_sync import CalendarSyncError, fetch_todays_events


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent
CALLOUT_DIR = PROJECT_DIR / "callout"

# Localhost only — never serve personal calendar data on the network.
HOST = "127.0.0.1"
PORT = 8000

# Endpoint the page polls for today's events.
API_PATH = "/api/today"


# === REQUEST HANDLER ===

class CalloutRequestHandler(SimpleHTTPRequestHandler):
    """Serves the callout files and the today's-events JSON endpoint."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(CALLOUT_DIR), **kwargs)

    def do_GET(self) -> None:
        """Route the events endpoint to JSON; serve everything else as a file."""
        if self.path == API_PATH:
            self._serve_today_events()
        else:
            super().do_GET()

    def _serve_today_events(self) -> None:
        """Return today's events as JSON, or a friendly error message."""
        try:
            events = fetch_todays_events()
            payload = {"events": [asdict(event) for event in events]}
        except CalendarSyncError as error:
            payload = {"error": str(error)}

        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Client navigated away before reading the response; nothing to do.
            pass


# === ENTRY POINT ===

def main() -> None:
    """Start the local callout server until interrupted."""
    server = ThreadingHTTPServer((HOST, PORT), CalloutRequestHandler)
    print(f"Daily summary callout running at http://{HOST}:{PORT}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
