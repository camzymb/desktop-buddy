#!/usr/bin/env bash
#
# Set up (or remove) autostart-on-login for Desktop Buddy on COSMIC/GNOME.
#
# On login, the desktop reads every *.desktop file in ~/.config/autostart/ and
# launches the ones marked as applications. This script writes such a file that
# starts main.py with the project's own virtualenv and working directory — so an
# autostarted buddy runs exactly like a manual launch.
#
# A short delay before launch (so the Wayland session is fully ready) lives in
# the launch wrapper, scripts/launch_buddy.sh — the .desktop entry points there
# rather than straight at python.
#
# Usage:
#   scripts/setup_autostart.sh            # install / enable autostart
#   scripts/setup_autostart.sh --status   # print the installed .desktop file & check paths
#   scripts/setup_autostart.sh --remove   # disable autostart (delete the file)
#
# Nothing personal is committed: the .desktop file is generated locally under
# your home directory and contains machine-specific paths, never the repo.

set -euo pipefail

# --- Resolve paths from this script's location, so it works wherever the repo lives.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
MAIN_SCRIPT="${PROJECT_DIR}/main.py"
LAUNCHER="${SCRIPT_DIR}/launch_buddy.sh"
ICON_PATH="${PROJECT_DIR}/sprites/idle_front.png"

AUTOSTART_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart"
DESKTOP_FILE="${AUTOSTART_DIR}/desktop-buddy.desktop"

# --- Status mode: show the installed entry and verify its paths still exist.
if [[ "${1:-}" == "--status" ]]; then
    if [[ ! -f "${DESKTOP_FILE}" ]]; then
        echo "No autostart entry installed at ${DESKTOP_FILE}"
        echo "Run scripts/setup_autostart.sh to install it."
        exit 1
    fi
    echo "Autostart entry: ${DESKTOP_FILE}"
    echo "----------------------------------------------------------------"
    cat "${DESKTOP_FILE}"
    echo "----------------------------------------------------------------"
    echo "Path checks:"
    for target in "${LAUNCHER}" "${VENV_PYTHON}" "${MAIN_SCRIPT}"; do
        if [[ -e "${target}" ]]; then
            echo "  OK      ${target}"
        else
            echo "  MISSING ${target}"
        fi
    done
    exit 0
fi

# --- Remove mode: delete the autostart entry and exit.
if [[ "${1:-}" == "--remove" ]]; then
    if [[ -f "${DESKTOP_FILE}" ]]; then
        rm -f "${DESKTOP_FILE}"
        echo "Removed autostart entry: ${DESKTOP_FILE}"
        echo "Desktop Buddy will no longer launch on login."
    else
        echo "No autostart entry found at ${DESKTOP_FILE} (nothing to remove)."
    fi
    exit 0
fi

# --- Install mode: sanity-check the venv and launcher exist before wiring up.
if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "Error: virtualenv Python not found at ${VENV_PYTHON}" >&2
    echo "Create it first, e.g.:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi
if [[ ! -x "${LAUNCHER}" ]]; then
    echo "Error: launch wrapper not found or not executable at ${LAUNCHER}" >&2
    echo "Fix it with:  chmod +x ${LAUNCHER}" >&2
    exit 1
fi

mkdir -p "${AUTOSTART_DIR}"

# Write the autostart entry. Exec/Path use absolute paths because autostart does
# not expand ~ or $HOME in these fields. Exec runs the launch wrapper, which
# waits for the Wayland session to settle before starting main.py.
cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=Desktop Buddy
Comment=Chibi desktop companion — morning greeting and daily post-it
Exec=${LAUNCHER}
Path=${PROJECT_DIR}
Icon=${ICON_PATH}
Terminal=false
X-GNOME-Autostart-enabled=true
Categories=Utility;
EOF

echo "Installed autostart entry: ${DESKTOP_FILE}"
echo "Desktop Buddy will now launch automatically when you log in."
echo
echo "To disable later, run:  ${SCRIPT_DIR}/setup_autostart.sh --remove"
echo "(or delete ${DESKTOP_FILE}, or toggle it off in COSMIC Settings > Startup Applications)"
