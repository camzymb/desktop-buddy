"""Tunable settings and static data for the desktop buddy.

Every knob the buddy reads — timings, screen geometry, the fixed messages she
speaks, launch-flag names, and the sprite filenames — lives here in one place,
so behavior can be tuned without touching the logic in buddy_overlay.py. This
module holds only data and the two small behavior enums; it imports nothing from
the rest of the app, so anything may import it without risk of a cycle.
"""

# === IMPORTS ===

from enum import Enum, auto
from pathlib import Path


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent
SPRITES_DIR = PROJECT_DIR / "sprites"
SOUNDS_DIR = PROJECT_DIR / "sounds"

# App icon shown in the taskbar/dock (the watercolor chibi-girl rounded square).
APP_ICON_PATH = PROJECT_DIR / "assets" / "app-icon.png"
# Matches the autostart entry's filename (desktop-buddy.desktop) so Wayland can
# associate the window with that .desktop and reuse its icon.
DESKTOP_FILE_NAME = "desktop-buddy"

# How tall the buddy appears on screen. Width is derived from each sprite's
# aspect ratio at load time.
BUDDY_HEIGHT_PX = 200

# Safety padding from screen edges so the buddy never clips a corner.
EDGE_MARGIN_PX = 20

# A press on the buddy must travel at least this far before it counts as picking
# her up to drag (rather than a bare click, which leaves her walking undisturbed).
BUDDY_DRAG_THRESHOLD_PX = 4

# Movement-loop cadence and step size. 33ms ≈ 30 FPS; 2.5 px/tick yields a
# gentle stroll across both 1080p and 4K displays.
MOVE_TICK_MS = 33
SPEED_PX = 2.5

# Distance the buddy must travel before advancing to the next walk frame.
# Tied to actual motion (NOT a timer), which is what makes the gait look
# anchored to the ground instead of her legs flipping in place while her
# body slides. With a 4-frame cycle, ~28px per frame lets all four poses get
# their turn over a natural step rather than only the first one or two showing.
STRIDE_PX = 28

# How long she stands still in the idle pose after reaching a destination
# before picking the next one.
MIN_IDLE_MS = 2000
MAX_IDLE_MS = 3000

# Every trip must cover at least this much horizontal distance, so each
# walk feels like a real journey rather than a shuffle.
MIN_TRIP_DISTANCE_PX = 600

# --- Talking ---

# Spontaneous talks on a gentle recurring timer. Each interval is randomised
# within the range so she doesn't speak like clockwork. She can also be
# triggered on demand with the spacebar (handy for testing without waiting).
TALK_INTERVAL_MIN_MS = 20 * 60 * 1000
TALK_INTERVAL_MAX_MS = 30 * 60 * 1000

# --- Startup greeting ---

# On launch (e.g. autostart at login), she settles in, gives a fixed
# welcome-back greeting, then auto-opens the daily post-it once so you see your
# day. The panel opens a beat AFTER the greeting bubble so the two don't pop at
# once.
STARTUP_GREETING_DELAY_MS = 3000
STARTUP_PANEL_DELAY_MS = 1400

# The login moment is deliberately fixed and consistent — unlike the random
# quotes and sounds she shares the rest of the time. It pairs one set line with
# the matching recorded clip in sounds/.
LOGIN_GREETING = "Welcome back, Camille. Take it gentle today."
LOGIN_VOICE_FILENAME = "voice_welcomeBack.mp3"

# The morning brief stands in for the plain welcome-back line the first time she
# launches each day (its words are gathered live — see the Morning brief section
# below). Like the login moment, it pairs the bubble text with one fixed recorded
# clip: her warm "good morning" in her own voice (audio.py plays the clip; the
# day's actual weather/calendar/email show in the bubble, never sent anywhere).
BRIEF_VOICE_FILENAME = "voice_morning.mp3"

# How long the speech bubble stays fully visible between fade-in and fade-out.
BUBBLE_HOLD_MS = 7000

# Gap between the top of her head and the bottom (tail) of the speech bubble.
BUBBLE_GAP_ABOVE_HEAD_PX = 6

# --- Daily summary panel ---

# Pressing "P" pops the daily-summary panel out of the buddy and parks it
# against the left edge; pressing it again retracts it. The panel fetches real
# calendar events itself; the Must-Do/Goals lists are a fixed default set (the
# checkboxes toggle, but the items themselves don't change), and the note is a
# fixed warm message.
PANEL_MUST_DO_ITEMS: tuple[str, ...] = (
    "Reply to messages",
    "Finish portfolio section",
    "Tidy the desk",
    "Drink some water",
)
PANEL_GOAL_ITEMS: tuple[str, ...] = (
    "Ship the desktop buddy",
    "Rest without guilt",
    "Move my body each day",
)
PANEL_NOTE: str = "You're doing so well. Take today one gentle step at a time."

# --- Event reminders ---

# Lead time: how far ahead of an event she gives a gentle heads-up. THIS is the
# headline setting for the feature — change this one number to nudge earlier or
# later.
REMINDER_LEAD_MINUTES = 15

# How often she checks the clock against today's events. Once a minute is plenty
# for minute-resolution reminders and costs almost nothing.
REMINDER_CHECK_INTERVAL_MS = 60 * 1000

# How often she quietly re-pulls today's calendar in the background, so events
# added or changed after launch still get their reminder. Kept separate from the
# check tick above so the network fetch stays occasional.
REMINDER_REFRESH_INTERVAL_MS = 10 * 60 * 1000

# A reminder pairs a gentle bubble with a fitting recorded clip (a soft "heads
# up", not an alarm). The 🌸 and the wording keep her kind-friend tone — a nudge,
# never hustle. {title} is the real event name, {minutes}/{unit} the time left.
REMINDER_VOICE_FILENAME = "voice_headsUp.mp3"
REMINDER_MESSAGE_TEMPLATE = "{title} in {minutes} {unit} 🌸"

# Test affordance: the "R" key and the --simulate-reminder launch flag both fire
# a fake reminder so the bubble + post-it can be previewed without waiting for a
# real event. The flag fires once, this long after she's settled on screen.
SIMULATE_REMINDER_FLAG = "--simulate-reminder"
SIMULATED_EVENT_TITLE = "Coffee with a friend"
SIMULATE_REMINDER_DELAY_MS = 3000

# --- Weekly content planner ---

# The --plan-week launch flag asks her to research and draft a week of content
# (one low-volume Anthropic API call with web search), write the full plan to
# Notion, and show a compact overview panel on the desktop. Pair it with --mock
# for a free SAMPLE plan with NO API call and NO Notion write — for testing the
# panel and wiring at zero cost. It's a launch flag rather than a keypress
# because key handling is unreliable on Wayland.
PLAN_WEEK_FLAG = "--plan-week"
PLAN_MOCK_FLAG = "--mock"

# --- Morning brief ---

# The brief normally fires on its own the first time she launches each new day.
# These launch flags force it immediately for testing, so you don't wait for
# tomorrow morning: --brief-now gathers REAL live data (weather + calendar +
# email); --brief-mock uses fixed sample data with NO network or Gmail calls,
# free to run. (Plain --mock is already the planner's, so the brief has its own.)
# Forcing the brief does NOT consume the once-a-day marker below, so a real first
# launch still greets you — testing never "uses up" your morning.
BRIEF_NOW_FLAG = "--brief-now"
BRIEF_MOCK_FLAG = "--brief-mock"

# Remembers the date she last delivered the brief, so it fires once per day and
# not on every relaunch. Machine-specific (and personal-adjacent) — gitignored,
# never shared; same local-state pattern as the panels' remembered positions.
BRIEF_STATE_PATH = PROJECT_DIR / "brief_state.json"

# She gives a gentle heads-up while researching, then speaks up when ready.
PLAN_WORKING_MESSAGE = "Working on your weekly content plan… 🌸"
PLAN_READY_MESSAGE = "Your content plan's ready 🌸 — tap the panel for the full version in Notion."
PLAN_MOCK_READY_MESSAGE = "Here's a sample of your weekly plan 🌸 (test mode — nothing was sent to Notion)."
PLAN_FAILED_MESSAGE = "I hit a snag making your plan — mind trying again? 🤍"
PLAN_NOTION_UNSET_MESSAGE = "Add your Notion page id to .env (NOTION_PAGE_ID) and I'll link you straight there. 🤍"
PLAN_NOTION_OPEN_FAILED_MESSAGE = "I couldn't open Notion just now — sorry! 🤍"

# Pressing "W" minimizes/maximizes the plan panel (clicking its header does too).
# Fire the plan once, a beat after she's settled (mirrors the reminder preview).
PLAN_WEEK_DELAY_MS = 3500

# On a normal launch she quietly shows the LAST SAVED plan (read locally — no API
# call), a moment after she's settled so it doesn't pop in before she appears.
PLAN_PANEL_SHOW_DELAY_MS = 1800

# --- Email draft assistant ---

# Pressing "D" asks her to read today's IMPORTANT emails (read-only — reusing the
# morning brief's Gmail access and its exact importance filter) and draft a warm,
# professional reply for each: exactly one cheap Haiku call per email. The drafts
# appear in a panel, each with an "Open in Gmail" button that opens a prefilled
# compose window in the browser. She NEVER sends — Camille reviews and sends each
# herself. Two launch flags help test it: --draft-now forces the real (paid) path
# at launch, and --draft-mock uses free SAMPLE emails/drafts with NO API call and
# NO Gmail access — the way to test the panel and the wording at zero cost. (The
# "D" key always uses the real path.)
DRAFT_NOW_FLAG = "--draft-now"
DRAFT_MOCK_FLAG = "--draft-mock"

# Fire the launch-flag draft once, a beat after she's settled (mirrors the others).
DRAFT_DELAY_MS = 3500

# She gives a gentle heads-up while drafting, then speaks up when the panel's up.
DRAFT_WORKING_MESSAGE = "Reading your inbox and drafting some replies… 🌸"
DRAFT_READY_MESSAGE_ONE = (
    "I drafted 1 reply for you 🌸 — open the panel to review and send it yourself."
)
DRAFT_READY_MESSAGE_MANY = (
    "I drafted {count} replies for you 🌸 — open the panel to review and send "
    "each one yourself."
)
DRAFT_FAILED_MESSAGE = "I hit a snag drafting your replies — mind trying again? 🤍"
DRAFT_OPEN_FAILED_MESSAGE = "I couldn't open Gmail just now — sorry! 🤍"

# --- Single instance ---

# A per-user lock so only one buddy ever runs at a time (e.g. if autostart and
# a manual launch both fire). Lives in the runtime dir, cleaned up on exit.
LOCK_FILE_NAME = "desktop-buddy.lock"


# === ENUMS ===

class Direction(Enum):
    """Which way the buddy is facing while walking."""
    LEFT = auto()
    RIGHT = auto()


class State(Enum):
    """High-level behavior state."""
    WALKING = auto()
    IDLE = auto()
    TALKING = auto()


# === SPRITE CONFIG ===

# The pose shown when standing still between walks.
IDLE_SPRITE: str = "idle_front.png"

# Four-frame walk cycles for each facing direction, advanced in order as the
# buddy covers ground (2 → 3 → 5 → 6 → loop). We deliberately skip frames 1
# and 4 of each set: those are high-knee poses where the character's head is
# turned backward, which reads as a glitchy direction "flip" mid-walk. The
# remaining frames keep her head facing her direction of travel throughout.
DIRECTION_FRAMES: dict[Direction, tuple[str, ...]] = {
    Direction.RIGHT: (
        "walk_right_2.png", "walk_right_3.png",
        "walk_right_5.png", "walk_right_6.png",
    ),
    Direction.LEFT: (
        "walk_left_2.png", "walk_left_3.png",
        "walk_left_5.png", "walk_left_6.png",
    ),
}

# Unused — head-turn frames (high-knee poses with the head facing backward).
# Kept in sprites/ and loaded at startup so the asset pipeline stays intact,
# but intentionally excluded from the walk cycle above.
UNUSED_HEAD_TURN_FRAMES: tuple[str, ...] = (
    "walk_right_1.png", "walk_right_4.png",
    "walk_left_1.png",  "walk_left_4.png",
)

# Preloaded but not used by Chunk B (which is left/right only along the
# floor). Front- and back-facing walk cycles are reserved for a future
# chunk that adds vertical movement; loading them now keeps the asset
# pipeline ready and surfaces missing files at startup instead of later.
RESERVED_SPRITES: tuple[str, ...] = (
    "walk_front_a.png", "walk_front_b.png",
    "walk_back_a.png",  "walk_back_b.png",
)

# Friendly faces shown while she's talking; one is chosen at random per
# message. The other expression sprites (surprised, sleepy) are reserved for
# future context-specific messages.
TALK_EXPRESSION_SPRITES: tuple[str, ...] = (
    "happy.png", "waving.png", "thinking.png",
)
