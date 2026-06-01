"""Desktop Buddy: a transparent, always-on-top companion that paces along the bottom of the screen.

The buddy lives on a fullscreen, transparent overlay because Wayland compositors
(including COSMIC on Pop!_OS) refuse to honor client-side window repositioning.
The overlay window itself never moves; the sprite is a child label we
reposition inside it. An input mask shrinks the window's "clickable" region
to the sprite rect (plus the speech bubble when it shows), so clicks outside
her body pass through to whatever is underneath on the desktop.

Every so often she pauses to "talk": a soft speech bubble with a warm message
fades in above her head, an attention pop plays followed by a recorded voice
clip, and she switches to a friendly expression before resuming her wander.
"""

# === IMPORTS ===

import math
import random
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from enum import Enum, auto
from http.server import ThreadingHTTPServer
from pathlib import Path

from PyQt6.QtCore import QLockFile, QStandardPaths, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QGuiApplication,
    QKeyEvent,
    QPixmap,
    QRegion,
    QResizeEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from audio import SoundPlayer
from calendar_sync import CalendarEvent, due_reminders, fetch_todays_events
from callout_panel import CalloutPanel
from callout_server import HOST, PORT, create_server
from content_planner import build_weekly_plan, load_plan_payload, write_plan
from notion_sync import page_url, publish_plan
from plan_panel import PlanPanel
from quotes import MOTIVATIONAL_QUOTES
from speech_bubble import SpeechBubble


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent
SPRITES_DIR = PROJECT_DIR / "sprites"
SOUNDS_DIR = PROJECT_DIR / "sounds"

# How tall the buddy appears on screen. Width is derived from each sprite's
# aspect ratio at load time.
BUDDY_HEIGHT_PX = 200

# Safety padding from screen edges so the buddy never clips a corner.
EDGE_MARGIN_PX = 20

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

# How long the speech bubble stays fully visible between fade-in and fade-out.
BUBBLE_HOLD_MS = 7000

# Gap between the top of her head and the bottom (tail) of the speech bubble.
BUBBLE_GAP_ABOVE_HEAD_PX = 6

# --- Daily summary callout ---

# Pressing "C" opens the callout in the default browser. The callout server
# serves the callout/ folder as its root, so the page lives at the server
# root; the URL is built from the server's host/port to stay in sync.
CALLOUT_URL = f"http://{HOST}:{PORT}/"
CALLOUT_OPEN_FAILED_MESSAGE = "I couldn't open your daily summary — sorry! 🤍"

# Pressing "P" pops the daily-summary panel out of the buddy and parks it
# against the left edge; pressing it again retracts it. The panel fetches real
# calendar events itself; the Must-Do/Goals lists are placeholders for now
# (working checkboxes), and the note is a fixed warm message.
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


# === BUDDY OVERLAY ===

class BuddyOverlay(QWidget):
    """Fullscreen transparent overlay that hosts a wandering buddy sprite.

    The overlay window covers the entire primary screen and never moves.
    A child QLabel holds the current sprite frame and gets repositioned
    along the bottom of the screen each movement tick. The window's input
    mask is updated to match the sprite's current rect, so clicks anywhere
    else fall through to the desktop below.
    """

    # Emitted from the background reminder-fetch thread; delivered on the GUI
    # thread so the latest calendar snapshot is swapped in safely.
    reminder_events_loaded = pyqtSignal(list)

    # Emitted from the background content-plan thread; carries an error string
    # ("" on success) so the result is handled safely on the GUI thread.
    plan_ready = pyqtSignal(str)

    # --- setup ---

    def __init__(
        self,
        *,
        simulate_reminder: bool = False,
        plan_week: bool = False,
        plan_week_mock: bool = False,
    ) -> None:
        super().__init__()
        self._simulate_reminder_on_start = simulate_reminder
        self._plan_week_on_start = plan_week
        self._plan_week_mock = plan_week_mock
        self._configure_window()

        # Preload every sprite already scaled to BUDDY_HEIGHT_PX tall.
        # Saves disk reads on every leg-swap during a walk.
        self._pixmaps = self._load_pixmaps()
        self._sprite_label = QLabel(self)
        self._speech_bubble = SpeechBubble(self)
        # Proof-of-concept daily-summary panel. It refreshes the overlay mask
        # on every animation frame via the callback so it stays visible while
        # the rest of the desktop remains click-through.
        self._callout_panel = CalloutPanel(self, self._update_input_mask)
        self._callout_panel.set_checklists(list(PANEL_MUST_DO_ITEMS), list(PANEL_GOAL_ITEMS))
        self._callout_panel.set_note(PANEL_NOTE)
        # Compact weekly-plan overview card; links to the full plan in Notion.
        self._plan_panel = PlanPanel(self, self._update_input_mask, self._open_notion)
        self._sound_player = SoundPlayer(SOUNDS_DIR)

        # Walk state. Position is initialized later in showEvent() once the
        # window has its real size from the compositor.
        self._feet_x: float = 0.0
        self._ground_y: int = 0
        self._state: State = State.IDLE
        self._direction: Direction = Direction.LEFT
        self._target_x: float = 0.0
        self._frame_index: int = 0
        self._distance_since_last_step: float = 0.0
        self._has_started: bool = False

        # Single ~30 FPS timer drives both position updates and stride-based
        # leg animation. When she's resting, this timer is stopped.
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(MOVE_TICK_MS)
        self._move_timer.timeout.connect(self._on_move_tick)

        # One-shot timer that ends the standing-still rest between walks.
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._begin_walking)

        # Talking timers. _talk_timer triggers a spontaneous talk and is
        # rescheduled after each one. _voice_delay_timer starts the voice clip
        # after the pop, and _bubble_hold_timer ends the bubble after its hold.
        self._talk_timer = QTimer(self)
        self._talk_timer.setSingleShot(True)
        self._talk_timer.timeout.connect(self._begin_talking)

        # The voice clip queued for the current talk: None means "pick a random
        # one" (her spontaneous default); a filename means play that specific
        # clip (the fixed login welcome-back greeting).
        self._pending_voice: str | None = None
        self._voice_delay_timer = QTimer(self)
        self._voice_delay_timer.setSingleShot(True)
        self._voice_delay_timer.timeout.connect(self._play_pending_voice)

        self._bubble_hold_timer = QTimer(self)
        self._bubble_hold_timer.setSingleShot(True)
        self._bubble_hold_timer.timeout.connect(self._end_talking)

        # Startup-greeting timers: one to give the greeting after she settles,
        # one to auto-open the post-it a beat later. Both fire once at launch.
        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self._run_startup_greeting)

        self._startup_panel_timer = QTimer(self)
        self._startup_panel_timer.setSingleShot(True)
        self._startup_panel_timer.timeout.connect(self._open_panel)

        # Event reminders. _reminder_events is the latest calendar snapshot the
        # refresh thread hands over; _reminded_event_ids remembers which events
        # already nudged so each one fires only once. One timer re-pulls the
        # calendar in the background, the other checks the clock against it.
        self._reminder_events: list[CalendarEvent] = []
        self._reminded_event_ids: set[str] = set()
        self.reminder_events_loaded.connect(self._on_reminder_events_loaded)
        self.plan_ready.connect(self._on_plan_ready)

        self._reminder_check_timer = QTimer(self)
        self._reminder_check_timer.setInterval(REMINDER_CHECK_INTERVAL_MS)
        self._reminder_check_timer.timeout.connect(self._check_due_reminders)

        self._reminder_refresh_timer = QTimer(self)
        self._reminder_refresh_timer.setInterval(REMINDER_REFRESH_INTERVAL_MS)
        self._reminder_refresh_timer.timeout.connect(self._refresh_reminder_events)

    def _configure_window(self) -> None:
        """Make the window frameless, transparent, always on top, and overlay-shaped.

        The Qt.WindowType.Tool flag is what keeps this surface out of the
        taskbar and (best effort) above other windows. WindowStaysOnTopHint
        requests always-on-top, but note this is only a *hint* on Wayland —
        COSMIC ultimately controls stacking order (see the note in main()).

        WA_ShowWithoutActivating shows/maximizes the overlay without stealing
        keyboard focus from whatever the user is doing, which also avoids the
        focus churn that can make a Tool window hide itself.

        The compositor decides the overlay's real size and delivers it after
        show(), so the window is maximized in main() and re-anchored in
        resizeEvent(). All coordinate math uses self.width() / self.height()
        at runtime so the buddy stays inside whatever overlay we receive.
        """
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # A full-screen geometry as a starting hint. Wayland often ignores
        # client size requests, so showMaximized() in main() does the real
        # work of filling the screen; this just gives a sane initial rect.
        screen_geometry = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(screen_geometry)

    def _load_pixmaps(self) -> dict[str, QPixmap]:
        """Load every sprite we may use, each pre-scaled to BUDDY_HEIGHT_PX tall.

        Includes the reserved front/back walking frames and the unused
        head-turn frames so the asset pipeline stays intact and any missing
        file fails loudly here at startup rather than mid-feature.
        """
        filenames: set[str] = {
            IDLE_SPRITE,
            *RESERVED_SPRITES,
            *UNUSED_HEAD_TURN_FRAMES,
            *TALK_EXPRESSION_SPRITES,
        }
        for direction_frames in DIRECTION_FRAMES.values():
            filenames.update(direction_frames)

        scaled_pixmaps: dict[str, QPixmap] = {}
        for filename in filenames:
            sprite_path = SPRITES_DIR / filename
            raw_pixmap = QPixmap(str(sprite_path))
            if raw_pixmap.isNull():
                raise FileNotFoundError(f"Could not load sprite: {sprite_path}")
            scaled_pixmaps[filename] = raw_pixmap.scaledToHeight(
                BUDDY_HEIGHT_PX,
                Qt.TransformationMode.SmoothTransformation,
            )
        return scaled_pixmaps

    def showEvent(self, event: QShowEvent) -> None:
        """Start the buddy's life ONCE the window has its real size from the compositor.

        We can't trust self.width() / self.height() until the window has been
        shown, because Wayland compositors decide the actual size at show time.
        Reading dimensions here makes the buddy adapt to whatever overlay size
        we actually got.
        """
        super().showEvent(event)
        if self._has_started:
            return
        self._has_started = True

        # Ground line = bottom of the visible overlay, minus a safety margin.
        self._ground_y = self.height() - EDGE_MARGIN_PX

        # Spawn at a random X along the floor, inset by half a sprite width
        # on each side so she doesn't clip the edge.
        idle_pixmap = self._pixmaps[IDLE_SPRITE]
        sprite_half_width = idle_pixmap.width() / 2
        min_spawn_x = sprite_half_width + EDGE_MARGIN_PX
        max_spawn_x = self.width() - sprite_half_width - EDGE_MARGIN_PX
        self._feet_x = random.uniform(min_spawn_x, max_spawn_x)

        self._show_sprite(IDLE_SPRITE)
        self._begin_walking()

        # Once she's settled: in test mode, preview a reminder; otherwise give
        # the normal startup greeting (which then resumes the recurring talk
        # cycle via _on_bubble_hidden()).
        if self._simulate_reminder_on_start:
            QTimer.singleShot(SIMULATE_REMINDER_DELAY_MS, self._simulate_reminder)
        else:
            self._startup_timer.start(STARTUP_GREETING_DELAY_MS)

        # If asked at launch, research and open this week's content plan once
        # she's settled (independent of the greeting above).
        if self._plan_week_on_start:
            QTimer.singleShot(PLAN_WEEK_DELAY_MS, self._start_weekly_plan)

        # Start watching the calendar for upcoming events: fetch today's now,
        # then keep it fresh and check the clock on their own gentle timers.
        self._refresh_reminder_events()
        self._reminder_check_timer.start()
        self._reminder_refresh_timer.start()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-anchor the buddy to the floor whenever the overlay's size changes.

        Wayland compositors decide the overlay's real size and usually deliver
        it *after* the initial show (e.g. once we maximize to fill the screen).
        Without re-anchoring here, the buddy would stay placed for the tiny
        pre-maximize size and sit off-screen until a manual resize — which is
        exactly the "invisible until I drag the window bigger" bug. Recomputing
        the ground line and clamping her into the new bounds makes her appear
        the instant the real size arrives.
        """
        super().resizeEvent(event)
        if not self._has_started:
            return

        self._ground_y = self.height() - EDGE_MARGIN_PX

        sprite_half_width = self._sprite_label.width() / 2
        min_x = sprite_half_width + EDGE_MARGIN_PX
        max_x = self.width() - sprite_half_width - EDGE_MARGIN_PX
        self._feet_x = max(min_x, min(self._feet_x, max_x))

        if self._state == State.TALKING:
            self._position_bubble()
        if self._callout_panel.is_open:
            self._callout_panel.reposition(self._callout_panel.parked_rect(self.height()))
        self._reposition_sprite()

    # --- rendering ---

    def _show_sprite(self, sprite_name: str) -> None:
        """Swap to the named sprite and refresh the on-screen position + click mask."""
        pixmap = self._pixmaps[sprite_name]
        self._sprite_label.setPixmap(pixmap)
        self._sprite_label.resize(pixmap.size())
        self._reposition_sprite()

    def _reposition_sprite(self) -> None:
        """Move the sprite label to the current feet coordinate and refresh the input mask."""
        sprite_width = self._sprite_label.width()
        sprite_height = self._sprite_label.height()
        left_x = int(self._feet_x - sprite_width / 2)
        top_y = int(self._ground_y - sprite_height)
        self._sprite_label.move(left_x, top_y)
        self._update_input_mask()

    def _update_input_mask(self) -> None:
        """Clip the overlay to the buddy — plus the speech bubble while it shows.

        The mask is what enables click-through: anywhere outside this region
        the overlay is both invisible and ignores mouse input, so clicks reach
        the windows underneath. The speech bubble and the daily-summary panel
        sit outside the sprite rect, so each must be unioned in while visible
        (the panel on every animation frame) or the mask would clip it away.
        """
        region = QRegion(self._sprite_label.geometry())
        if self._speech_bubble.isVisible():
            region = region.united(QRegion(self._speech_bubble.geometry()))
        if self._callout_panel.isVisible():
            region = region.united(QRegion(self._callout_panel.geometry()))
        if self._plan_panel.isVisible():
            region = region.united(QRegion(self._plan_panel.geometry()))
        self.setMask(region)

    # --- state transitions ---

    def _begin_walking(self) -> None:
        """Pick a fresh horizontal destination and start the walk loop."""
        self._target_x = self._pick_destination_x()
        self._direction = (
            Direction.RIGHT if self._target_x > self._feet_x else Direction.LEFT
        )
        self._frame_index = 0
        self._distance_since_last_step = 0.0
        self._state = State.WALKING
        self._show_sprite(DIRECTION_FRAMES[self._direction][0])
        self._move_timer.start()

    def _begin_resting(self) -> None:
        """Stop moving, show idle pose, and schedule the next walk."""
        self._state = State.IDLE
        self._move_timer.stop()
        self._show_sprite(IDLE_SPRITE)
        pause_duration_ms = random.randint(MIN_IDLE_MS, MAX_IDLE_MS)
        self._idle_timer.start(pause_duration_ms)

    # --- talking ---

    def _begin_talking(
        self,
        message: str | None = None,
        *,
        play_voice: bool = True,
        voice: str | None = None,
    ) -> None:
        """Pause wandering to show a speech bubble and emote, optionally with voice.

        With no message she shares a random encouragement and plays the
        attention pop followed by a voice clip. Callers can pass a specific
        message (e.g. a friendly error) and set play_voice=False for a silent
        bubble. Passing voice=<filename> plays that specific clip after the pop
        instead of a random one (used for the fixed login greeting); leaving it
        None keeps her usual random pick. _bubble_hold_timer later fires
        _end_talking() to fade the bubble out and resume her normal wander.

        Re-triggers while she's already talking (a stray timer tick or an
        eager key press) are ignored so a bubble in progress isn't reset.
        """
        if self._state == State.TALKING:
            return

        self._move_timer.stop()
        self._idle_timer.stop()
        self._state = State.TALKING

        self._show_sprite(random.choice(TALK_EXPRESSION_SPRITES))

        spoken = message if message is not None else random.choice(MOTIVATIONAL_QUOTES)
        self._speech_bubble.set_message(spoken)
        self._position_bubble()
        self._speech_bubble.fade_in()
        self._update_input_mask()

        if play_voice:
            # Pop first; start the voice clip once the pop has finished so they
            # don't talk over each other (length is 0 when audio is unavailable).
            self._pending_voice = voice
            pop_length_ms = int(self._sound_player.play_pop() * 1000)
            self._voice_delay_timer.start(pop_length_ms)

        self._bubble_hold_timer.start(BUBBLE_HOLD_MS)

    def _end_talking(self) -> None:
        """Fade the speech bubble out; resume wandering once it's fully hidden."""
        self._speech_bubble.fade_out(self._on_bubble_hidden)

    def _on_bubble_hidden(self) -> None:
        """Restore the click-through mask, queue the next talk, and walk again."""
        self._update_input_mask()
        self._schedule_next_talk()
        self._begin_resting()

    def _schedule_next_talk(self) -> None:
        """Queue her next spontaneous talk 20-30 minutes from now."""
        interval_ms = random.randint(TALK_INTERVAL_MIN_MS, TALK_INTERVAL_MAX_MS)
        self._talk_timer.start(interval_ms)

    def _play_pending_voice(self) -> None:
        """Play the clip queued for the current talk, once the pop has finished.

        A specific filename (the fixed login greeting) plays that exact clip;
        None — her spontaneous default — plays a random one.
        """
        if self._pending_voice is None:
            self._sound_player.play_random_voice()
        else:
            self._sound_player.play_voice(self._pending_voice)

    def _position_bubble(self) -> None:
        """Center the speech bubble just above the buddy's head, kept on-screen."""
        bubble_width = self._speech_bubble.width()
        bubble_height = self._speech_bubble.height()
        sprite_top_y = self._ground_y - self._sprite_label.height()

        left_x = int(self._feet_x - bubble_width / 2)
        max_left_x = self.width() - EDGE_MARGIN_PX - bubble_width
        left_x = max(EDGE_MARGIN_PX, min(left_x, max_left_x))

        top_y = sprite_top_y - bubble_height - BUBBLE_GAP_ABOVE_HEAD_PX
        top_y = max(EDGE_MARGIN_PX, top_y)

        self._speech_bubble.move(left_x, top_y)

    # --- movement loop ---

    def _on_move_tick(self) -> None:
        """Advance toward the target each tick; step the walk frame every STRIDE_PX."""
        distance_remaining = self._target_x - self._feet_x

        # Arrived (or close enough): snap exactly and start the rest.
        if abs(distance_remaining) <= SPEED_PX:
            self._feet_x = self._target_x
            self._reposition_sprite()
            self._begin_resting()
            return

        # Take one tick's step in the direction of the target.
        step = SPEED_PX if distance_remaining > 0 else -SPEED_PX
        self._feet_x += step
        self._distance_since_last_step += SPEED_PX

        # Stride-based animation: only advance the walk cycle once we've
        # covered enough ground. This keeps the gait visually anchored to her
        # motion. The index wraps through the direction's frames in order.
        if self._distance_since_last_step >= STRIDE_PX:
            self._distance_since_last_step -= STRIDE_PX
            walk_frames = DIRECTION_FRAMES[self._direction]
            self._frame_index = (self._frame_index + 1) % len(walk_frames)
            self._show_sprite(walk_frames[self._frame_index])
        else:
            self._reposition_sprite()

    # --- destination picking ---

    def _pick_destination_x(self) -> float:
        """Choose a random X coordinate far enough away to be a real trip.

        Bounds are derived from the OVERLAY's actual size (self.width()), not
        the screen size, so the buddy stays inside the visible window even
        when the compositor gives us a smaller overlay than we asked for.
        """
        sprite_half_width = self._sprite_label.width() / 2
        min_x = sprite_half_width + EDGE_MARGIN_PX
        max_x = self.width() - sprite_half_width - EDGE_MARGIN_PX

        # Reject candidates closer than MIN_TRIP_DISTANCE_PX so each walk
        # crosses a meaningful chunk of the screen.
        for _ in range(30):
            candidate_x = random.uniform(min_x, max_x)
            if abs(candidate_x - self._feet_x) >= MIN_TRIP_DISTANCE_PX:
                return candidate_x

        # Fallback: if the screen is unusually small, head to whichever
        # edge is farther from her current position.
        screen_mid_x = (min_x + max_x) / 2
        return max_x if self._feet_x < screen_mid_x else min_x

    # --- callout ---

    def _open_callout(self) -> None:
        """Open the daily summary callout in the user's default web browser.

        If no browser can be opened, she shows a friendly message instead of
        the app crashing.
        """
        try:
            opened = webbrowser.open(CALLOUT_URL)
        except OSError:
            opened = False
        if not opened:
            self._begin_talking(CALLOUT_OPEN_FAILED_MESSAGE, play_voice=False)

    def _toggle_panel(self) -> None:
        """Pop the daily-summary panel out of the buddy, or retract it if open.

        The panel grows out of (and retracts into) her current on-screen
        center, then parks against the left edge. Toggling mid-animation just
        reverses smoothly because the animation is restarted from wherever the
        card currently is.
        """
        if self._callout_panel.is_open:
            self._callout_panel.retract(self._sprite_label.geometry().center())
        else:
            self._open_panel()

    def _open_panel(self) -> None:
        """Pop the daily-summary panel out of the buddy (no-op if already open)."""
        if self._callout_panel.is_open:
            return
        seed_center = self._sprite_label.geometry().center()
        final_rect = self._callout_panel.parked_rect(self.height())
        self._callout_panel.pop_out(seed_center, final_rect)

    # --- startup greeting ---

    def _run_startup_greeting(self) -> None:
        """Greet with the fixed welcome-back line + clip, then open the post-it.

        Unlike her spontaneous talks (a random quote and a random sound), the
        login moment is deliberately consistent: the same warm line and the same
        recorded clip every time. It still goes through _begin_talking(), so the
        normal recurring talk cycle resumes after it (via _on_bubble_hidden()).
        """
        self._begin_talking(LOGIN_GREETING, voice=LOGIN_VOICE_FILENAME)
        self._startup_panel_timer.start(STARTUP_PANEL_DELAY_MS)

    # --- weekly content planner ---

    def _start_weekly_plan(self) -> None:
        """Give a gentle heads-up and research this week's plan in the background."""
        self._begin_talking(PLAN_WORKING_MESSAGE, play_voice=False)
        threading.Thread(
            target=self._generate_plan_worker, name="weekly-plan", daemon=True
        ).start()

    def _generate_plan_worker(self) -> None:
        """Build the plan off the GUI thread, save it, publish it, and report back.

        build_weekly_plan and publish_plan both handle expected problems (missing
        key/token, offline, an unparseable reply, an unshared page) by returning a
        friendly message rather than raising, so there's always something kind to
        show. We still guard the unexpected so a failure here can never take the
        buddy down. The plan is saved for the panel to read; the signal carries a
        status string ("" on success) to the GUI thread.
        """
        try:
            plan = build_weekly_plan(use_mock=self._plan_week_mock)
        except Exception:  # noqa: BLE001 — a background nicety must never crash the app
            plan = {"error": PLAN_FAILED_MESSAGE}
        write_plan(plan)

        if "error" in plan:
            status = plan["error"]          # generation failed (e.g. missing key)
        elif self._plan_week_mock:
            status = ""                      # mock: panel only, never touch Notion
        else:
            status = publish_plan(plan)      # write the full plan to Notion
        self.plan_ready.emit(status)

    def _on_plan_ready(self, status: str) -> None:
        """Show the compact overview panel and give a gentle spoken update.

        `status` is empty on full success, or a friendly message describing a
        problem. When the plan itself was built (it has pieces) the panel is
        shown regardless, so a Notion-only hiccup still leaves the overview up
        with the issue explained out loud.
        """
        plan = load_plan_payload()
        pieces = plan.get("pieces") or []
        if pieces:
            rows = [
                (piece.get("day", ""), piece.get("format", ""),
                 piece.get("topic") or piece.get("idea", ""))
                for piece in pieces
            ]
            self._plan_panel.set_overview(plan.get("week_of", ""), rows)
            if self._plan_panel.is_open:
                self._plan_panel.raise_()
                self._update_input_mask()
            else:
                self._plan_panel.show_panel()

        if not pieces:
            message = status or PLAN_FAILED_MESSAGE
        elif status:
            message = status
        elif self._plan_week_mock:
            message = PLAN_MOCK_READY_MESSAGE
        else:
            message = PLAN_READY_MESSAGE
        self._begin_talking(message, play_voice=False)

    def _toggle_plan_panel(self) -> None:
        """Minimize/maximize the plan panel if it's on screen (the 'W' key)."""
        if self._plan_panel.is_open:
            self._plan_panel.toggle_minimized()

    def _open_notion(self) -> None:
        """Open the full plan in Notion (the panel's link), with friendly fallbacks."""
        url = page_url()
        if not url:
            self._begin_talking(PLAN_NOTION_UNSET_MESSAGE, play_voice=False)
            return
        try:
            opened = webbrowser.open(url)
        except OSError:
            opened = False
        if not opened:
            self._begin_talking(PLAN_NOTION_OPEN_FAILED_MESSAGE, play_voice=False)

    # --- event reminders ---

    def _refresh_reminder_events(self) -> None:
        """Kick off a background re-pull of today's calendar (timer fires this)."""
        threading.Thread(
            target=self._fetch_reminder_events_worker,
            name="reminder-events",
            daemon=True,
        ).start()

    def _fetch_reminder_events_worker(self) -> None:
        """Fetch today's events off the GUI thread and hand them back via signal.

        Reminders are a quiet background nicety, so any calendar problem
        (offline, missing/expired sign-in) is swallowed: she simply keeps the
        events she already had and tries again on the next refresh, never
        interrupting with an error. Event data is only passed back for in-memory
        scheduling — never written or logged.
        """
        try:
            events = fetch_todays_events()
        except Exception:  # noqa: BLE001 — a background nicety must never crash the app
            return
        self.reminder_events_loaded.emit(events)

    def _on_reminder_events_loaded(self, events: list) -> None:
        """Store the latest calendar snapshot for the checker (on the GUI thread)."""
        self._reminder_events = events

    def _check_due_reminders(self) -> None:
        """Nudge for the soonest event now within the lead window (once each).

        She gives one gentle reminder at a time: if she's already mid-bubble, or
        several events come due together, the rest simply wait for the next tick
        (a minute later) — so an event is only ever marked reminded once it has
        actually been shown.
        """
        if self._state == State.TALKING:
            return
        now = datetime.now().astimezone()
        lead = timedelta(minutes=REMINDER_LEAD_MINUTES)
        due = due_reminders(self._reminder_events, now, lead, self._reminded_event_ids)
        if not due:
            return
        event = due[0]
        self._reminded_event_ids.add(event.event_id)
        self._fire_reminder(event.title, event.start_dt, now)

    def _fire_reminder(self, title: str, start_dt: datetime, now: datetime) -> None:
        """Show the gentle heads-up bubble + clip and pop the post-it for one event.

        Reuses her normal talking path (bubble + attention pop + the heads-up
        voice clip) and the existing daily post-it, so a reminder looks and
        sounds just like the rest of her, only with calendar-aware wording.
        """
        minutes = max(1, math.ceil((start_dt - now).total_seconds() / 60))
        unit = "minute" if minutes == 1 else "minutes"
        message = REMINDER_MESSAGE_TEMPLATE.format(title=title, minutes=minutes, unit=unit)
        self._begin_talking(message, voice=REMINDER_VOICE_FILENAME)
        self._open_panel()

    def _simulate_reminder(self) -> None:
        """Fire a fake reminder right now to preview the bubble + post-it together.

        Builds a throwaway event starting one lead-time from now and runs it
        through the real reminder path, so what you see is exactly what a genuine
        calendar reminder looks like — no waiting for an actual event. Triggered
        by the "R" key or the --simulate-reminder launch flag.
        """
        now = datetime.now().astimezone()
        start_dt = now + timedelta(minutes=REMINDER_LEAD_MINUTES)
        self._fire_reminder(SIMULATED_EVENT_TITLE, start_dt, now)

    # --- input ---

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keys: Escape closes; Space talks; C opens the browser summary; P pops the panel; G replays the greeting; R previews a reminder; W minimizes the plan panel.

        All require the overlay to hold keyboard focus — clicking the buddy
        gives it focus. Spacebar triggers the same talk as the timer; "C" opens
        the callout in the default browser; "P" toggles the daily-summary panel;
        "G" replays the startup greeting + panel; "R" previews an event reminder
        (bubble + post-it) without waiting for a real calendar event; "W"
        minimizes/maximizes the weekly-plan panel.
        """
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_Space:
            self._begin_talking()
        elif event.key() == Qt.Key.Key_C:
            self._open_callout()
        elif event.key() == Qt.Key.Key_P:
            self._toggle_panel()
        elif event.key() == Qt.Key.Key_G:
            self._run_startup_greeting()
        elif event.key() == Qt.Key.Key_R:
            self._simulate_reminder()
        elif event.key() == Qt.Key.Key_W:
            self._toggle_plan_panel()
        else:
            super().keyPressEvent(event)


# === ENTRY POINT ===

def _start_callout_server() -> ThreadingHTTPServer | None:
    """Start the callout web server on a background daemon thread.

    Returns the running server so it can be shut down cleanly on exit, or None
    if it couldn't bind (e.g. the port is already in use, meaning a server is
    likely already running). Either way the buddy keeps working; the "C"
    shortcut just opens whatever is serving that address. Using a daemon
    thread — not a subprocess — means there is no separate process to orphan.
    """
    try:
        server = create_server()
    except OSError:
        return None
    threading.Thread(
        target=server.serve_forever, name="callout-server", daemon=True
    ).start()
    return server


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
    """Boot the Qt event loop, start the callout server, and show the buddy.

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

    # Single instance: if a buddy is already running, bow out quietly. This is
    # what keeps autostart-on-login from ever spawning a second girl.
    instance_lock = _acquire_single_instance_lock()
    if instance_lock is None:
        print("Desktop Buddy is already running — not starting another.")
        return 0

    callout_server = _start_callout_server()
    overlay = BuddyOverlay(
        simulate_reminder=SIMULATE_REMINDER_FLAG in sys.argv,
        plan_week=PLAN_WEEK_FLAG in sys.argv,
        plan_week_mock=PLAN_MOCK_FLAG in sys.argv,
    )
    overlay.showMaximized()
    try:
        return app.exec()
    finally:
        # Shut the server down so no thread or socket is left behind on exit.
        if callout_server is not None:
            callout_server.shutdown()
            callout_server.server_close()
        instance_lock.unlock()


if __name__ == "__main__":
    sys.exit(main())
