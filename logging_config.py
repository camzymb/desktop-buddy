"""Central logging setup for the desktop buddy.

One call to `setup_logging()` at startup configures logging for the whole app:
a rotating file in the project root (desktop_buddy.log) for the full diagnostic
trail, and a quiet console that shows only warnings and errors so a healthy run
prints nothing. Every other module logs through the standard library's `logging`
(a module-level `logging.getLogger(__name__)`), so this is the only place that
decides where logs go, how they're formatted, and how verbose to be.

Privacy: this module decides WHERE logs go, not what they contain. Call sites
must never log secrets (tokens, API keys) or personal content (email
subjects/bodies, calendar titles) — only failures, error types, and small
counts. The log file is covered by .gitignore (`*.log`) so it never reaches the
public repo, but keeping the contents minimal is the real safeguard.

Verbosity is tunable without code changes via the BUDDY_LOG_LEVEL environment
variable (e.g. `BUDDY_LOG_LEVEL=DEBUG` for a verbose trace on both the file and
the console). Unset, the file captures INFO and the console stays at WARNING.
"""

# === IMPORTS ===

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent

# The single log file, kept in the project root and gitignored (`*.log`).
# Rotated so it can never grow without bound: a few small files at most.
LOG_PATH = PROJECT_DIR / "desktop_buddy.log"
LOG_MAX_BYTES = 1_000_000  # ~1 MB per file before it rolls over
LOG_BACKUP_COUNT = 3       # keep this many rotated copies

# Default levels when BUDDY_LOG_LEVEL is not set: the file keeps the milestones
# and everything worse; the console stays quiet so a healthy run prints nothing.
DEFAULT_FILE_LEVEL = logging.INFO
DEFAULT_CONSOLE_LEVEL = logging.WARNING

# Opt-in override: set BUDDY_LOG_LEVEL=DEBUG (or INFO/WARNING/ERROR) for a more
# verbose trace on BOTH the file and the console.
LEVEL_ENV_VAR = "BUDDY_LOG_LEVEL"

# timestamp · level · module · message
LOG_FORMAT = "%(asctime)s  %(levelname)-7s  %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# === SETUP ===

def setup_logging() -> None:
    """Configure the root logger once: a rotating file plus a quiet console.

    Safe to call more than once — it clears any handlers it added before, so a
    repeat call never double-prints every line. Reads BUDDY_LOG_LEVEL to allow a
    verbose trace without code changes; an unset or unrecognized value falls back
    to the quiet defaults. If the log file can't be opened (e.g. a read-only
    directory), it degrades to console-only rather than taking the app down —
    logging must never be the thing that crashes the buddy.
    """
    override = _resolve_override_level()
    file_level = override if override is not None else DEFAULT_FILE_LEVEL
    console_level = override if override is not None else DEFAULT_CONSOLE_LEVEL

    root = logging.getLogger()
    # Let through the more verbose of the two handlers; each handler still
    # applies its own threshold below.
    root.setLevel(min(file_level, console_level))

    # Drop handlers from any previous setup_logging() so repeated calls don't
    # duplicate output.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler()  # stderr
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    try:
        file_handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError as error:
        # Console-only is an acceptable degradation; never crash over logging.
        root.warning("Could not open log file %s: %s", LOG_PATH.name, error)
        return
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def _resolve_override_level() -> int | None:
    """Return the numeric level from BUDDY_LOG_LEVEL, or None if unset/invalid.

    `logging.getLevelName` maps a known name (e.g. "DEBUG") to its int; for an
    unknown name it returns a string like "Level FOO", so we guard against a typo
    silently breaking logging by only accepting an int result.
    """
    name = os.environ.get(LEVEL_ENV_VAR, "").strip().upper()
    if not name:
        return None
    level = logging.getLevelName(name)
    return level if isinstance(level, int) else None
