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
ICON_PATH="${PROJECT_DIR}/assets/app-icon.png"

# Must match the app's Wayland app-id / X11 WM class so the dock ties the running
# window to this .desktop (and shows its icon). main.py sets that id via
# app.setDesktopFileName("desktop-buddy").
WM_CLASS="desktop-buddy"

AUTOSTART_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart"
DESKTOP_FILE="${AUTOSTART_DIR}/desktop-buddy.desktop"

# A second copy in the applications dir is what the dock/launcher actually scans
# to match a window to its icon — the autostart dir alone isn't enough.
APPLICATIONS_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
APP_DESKTOP_FILE="${APPLICATIONS_DIR}/desktop-buddy.desktop"

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
    if [[ -f "${APP_DESKTOP_FILE}" ]]; then
        echo "Launcher entry (for the dock icon): ${APP_DESKTOP_FILE}  OK"
    else
        echo "Launcher entry (for the dock icon): ${APP_DESKTOP_FILE}  MISSING (re-run to install)"
    fi
    echo "Path checks:"
    for target in "${LAUNCHER}" "${VENV_PYTHON}" "${MAIN_SCRIPT}" "${ICON_PATH}"; do
        if [[ -e "${target}" ]]; then
            echo "  OK      ${target}"
        else
            echo "  MISSING ${target}"
        fi
    done
    exit 0
fi

# --- Remove mode: delete both entries and exit.
if [[ "${1:-}" == "--remove" ]]; then
    found=0
    for target in "${DESKTOP_FILE}" "${APP_DESKTOP_FILE}"; do
        if [[ -f "${target}" ]]; then
            rm -f "${target}"; found=1
            echo "Removed: ${target}"
        fi
    done
    if [[ "${found}" -eq 1 ]]; then
        echo "Desktop Buddy will no longer launch on login."
    else
        echo "No entries found (nothing to remove)."
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

mkdir -p "${AUTOSTART_DIR}" "${APPLICATIONS_DIR}"

# Write the autostart entry. Exec/Path use absolute paths because autostart does
# not expand ~ or $HOME in these fields. Exec runs the launch wrapper, which
# waits for the Wayland session to settle before starting main.py. StartupWMClass
# matches the running window's app-id so the dock shows this entry's icon.
cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=Desktop Buddy
Comment=Chibi desktop companion — morning greeting and daily post-it
Exec=${LAUNCHER}
Path=${PROJECT_DIR}
Icon=${ICON_PATH}
StartupWMClass=${WM_CLASS}
Terminal=false
X-GNOME-Autostart-enabled=true
Categories=Utility;
EOF

# Install the same entry in the applications dir so the dock/launcher can find it
# and match the running window (by StartupWMClass / app-id) to this icon. The
# autostart-only key is dropped here since it's meaningless for a launcher entry.
grep -v '^X-GNOME-Autostart-enabled=' "${DESKTOP_FILE}" > "${APP_DESKTOP_FILE}"

# Refresh the desktop database so the new launcher entry is picked up (best-effort).
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPLICATIONS_DIR}" >/dev/null 2>&1 || true
fi

echo "Installed autostart entry:  ${DESKTOP_FILE}"
echo "Installed launcher entry:   ${APP_DESKTOP_FILE}  (so the dock shows the icon)"
echo "Desktop Buddy will now launch automatically when you log in."
echo
echo "To disable later, run:  ${SCRIPT_DIR}/setup_autostart.sh --remove"
echo "(or delete the files above, or toggle it off in COSMIC Settings > Startup Applications)"
