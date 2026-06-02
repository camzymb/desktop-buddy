"""Desktop Buddy entry point: launch the always-on-top companion overlay.

Keeps startup tiny and focused — take a per-user lock so only one buddy ever
runs, boot the Qt event loop, and show the overlay (defined in buddy_overlay.py).
Launch flags (e.g. --plan-week, --brief-mock, --draft-mock, --simulate-reminder)
are read here and passed into the overlay.
"""

# === IMPORTS ===

import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile, QStandardPaths
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from buddy_config import (
    APP_ICON_PATH,
    BRIEF_MOCK_FLAG,
    BRIEF_NOW_FLAG,
    DESKTOP_FILE_NAME,
    DRAFT_MOCK_FLAG,
    DRAFT_NOW_FLAG,
    LOCK_FILE_NAME,
    PLAN_MOCK_FLAG,
    PLAN_WEEK_FLAG,
    SIMULATE_REMINDER_FLAG,
)
from buddy_overlay import BuddyOverlay


# === ENTRY POINT ===

def _acquire_single_instance_lock() -> QLockFile | None:
    """Take a per-user lock so only one buddy runs; return it, or None if taken.

    The lock lives in the session runtime dir (falling back to the temp dir).
    QLockFile records the owning PID, so a lock left by a crashed instance is
    detected as stale and reclaimed automatically — only a *live* buddy blocks
    a second launch (the case autostart-plus-manual-launch could hit).
    """
    runtime_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.RuntimeLocation
    ) or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
    lock = QLockFile(str(Path(runtime_dir) / LOCK_FILE_NAME))
    return lock if lock.tryLock(0) else None


def main() -> int:
    """Boot the Qt event loop and show the buddy.

    We use showMaximized() rather than show() because on Wayland (COSMIC)
    the compositor decides window size and routinely ignores client size
    requests — maximizing is the reliable way to make the overlay fill the
    screen immediately, with no manual resize. resizeEvent() then re-anchors
    the buddy once the maximized size actually arrives.

    Note on always-on-top: Wayland gives clients no guaranteed control over
    stacking order, so WindowStaysOnTopHint is only a hint COSMIC may ignore.
    If the buddy still gets buried behind other windows, the robust fix is
    the wlr/ext layer-shell protocol (via the layer-shell-qt plugin), which
    stock PyQt6 does not expose — a larger change left for a later chunk.
    """
    app = QApplication(sys.argv)
    # Taskbar/dock icon. setDesktopFileName lets Wayland tie the window to the
    # autostart .desktop entry (and its icon); setWindowIcon covers the rest.
    app.setDesktopFileName(DESKTOP_FILE_NAME)
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    # Single instance: if a buddy is already running, bow out quietly. This is
    # what keeps autostart-on-login from ever spawning a second girl.
    instance_lock = _acquire_single_instance_lock()
    if instance_lock is None:
        print("Desktop Buddy is already running — not starting another.")
        return 0

    overlay = BuddyOverlay(
        simulate_reminder=SIMULATE_REMINDER_FLAG in sys.argv,
        plan_week=PLAN_WEEK_FLAG in sys.argv,
        plan_week_mock=PLAN_MOCK_FLAG in sys.argv,
        brief_now=BRIEF_NOW_FLAG in sys.argv,
        brief_mock=BRIEF_MOCK_FLAG in sys.argv,
        draft_now=DRAFT_NOW_FLAG in sys.argv,
        draft_mock=DRAFT_MOCK_FLAG in sys.argv,
    )
    overlay.showMaximized()
    try:
        return app.exec()
    finally:
        instance_lock.unlock()


if __name__ == "__main__":
    sys.exit(main())
