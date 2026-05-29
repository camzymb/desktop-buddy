#!/usr/bin/env bash
#
# Autostart launch wrapper for Desktop Buddy.
#
# When the desktop logs in, the Wayland/COSMIC session (compositor, panels,
# layer-shell surfaces) is not always ready the instant autostart entries fire.
# Launching the overlay too early can silently fail. This wrapper waits a few
# seconds for the session to settle, then hands off to main.py via the project's
# own virtualenv. The .desktop autostart entry points here instead of straight
# at python, so the delay lives in version control and is easy to tune.
#
# Run it directly to simulate exactly what happens at login.

set -euo pipefail

# --- Seconds to wait before launching, so the Wayland session is fully ready.
#     Bump this up if the buddy still appears before the desktop has settled.
STARTUP_DELAY_SECONDS=15

# --- Resolve paths from this script's location, so it works wherever the repo lives.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
MAIN_SCRIPT="${PROJECT_DIR}/main.py"

sleep "${STARTUP_DELAY_SECONDS}"

cd "${PROJECT_DIR}"
exec "${VENV_PYTHON}" "${MAIN_SCRIPT}" "$@"
