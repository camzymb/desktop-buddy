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

import json
import math
import random
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QLockFile, QStandardPaths, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPixmap,
    QRegion,
    QResizeEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from audio import SoundPlayer
# Every tunable constant, the Direction/State enums, and the sprite config live
# in buddy_config; imported wholesale so the overlay can reference them by name.
from buddy_config import *  # noqa: F401,F403
from calendar_sync import CalendarEvent, due_reminders, fetch_todays_events
from callout_panel import CalloutPanel
from content_planner import build_weekly_plan, load_plan_payload, write_plan
from draft_assistant import DraftBatch, draft_replies
from draft_panel import DraftPanel
from morning_brief import gather_brief, mock_brief
from notion_sync import page_url, publish_plan
from plan_panel import PlanPanel
from quotes import MOTIVATIONAL_QUOTES
from speech_bubble import SpeechBubble


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

    # Emitted from the background morning-brief thread; carries the composed brief
    # text (empty if gathering fell over) for safe display on the GUI thread.
    brief_ready = pyqtSignal(str)

    # Emitted from the background draft thread; carries the DraftBatch (drafts +
    # friendly status) for safe display on the GUI thread.
    draft_ready = pyqtSignal(object)

    # --- setup ---

    def __init__(
        self,
        *,
        simulate_reminder: bool = False,
        plan_week: bool = False,
        plan_week_mock: bool = False,
        brief_now: bool = False,
        brief_mock: bool = False,
        draft_now: bool = False,
        draft_mock: bool = False,
    ) -> None:
        super().__init__()
        self._simulate_reminder_on_start = simulate_reminder
        self._plan_week_on_start = plan_week
        self._plan_week_mock = plan_week_mock
        self._brief_now_on_start = brief_now
        self._brief_mock_on_start = brief_mock
        self._draft_now_on_start = draft_now
        self._draft_mock_on_start = draft_mock
        self._configure_window()

        # Preload every sprite already scaled to BUDDY_HEIGHT_PX tall.
        # Saves disk reads on every leg-swap during a walk.
        self._pixmaps = self._load_pixmaps()
        self._sprite_label = QLabel(self)
        # Let mouse events fall through the sprite to the overlay, which handles
        # picking her up and dragging her (the sprite itself never needs clicks).
        self._sprite_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._speech_bubble = SpeechBubble(self)
        # Proof-of-concept daily-summary panel. It refreshes the overlay mask
        # on every animation frame via the callback so it stays visible while
        # the rest of the desktop remains click-through.
        self._callout_panel = CalloutPanel(self, self._update_input_mask)
        # The card's ✕ control asks us to retract it into the buddy; 'P' reopens it.
        self._callout_panel.close_requested.connect(self._retract_callout_panel)
        self._callout_panel.set_checklists(list(PANEL_MUST_DO_ITEMS), list(PANEL_GOAL_ITEMS))
        self._callout_panel.set_note(PANEL_NOTE)
        # Compact weekly-plan overview card; links to the full plan in Notion.
        self._plan_panel = PlanPanel(self, self._update_input_mask, self._open_notion)
        # True once the plan card has real content, so its key can reopen it after
        # the ✕ button closes it — without ever popping an empty "no plan yet" card.
        self._plan_has_content = False
        # Draft-replies card; each draft's button opens a prefilled Gmail compose.
        self._draft_panel = DraftPanel(self, self._update_input_mask, self._open_draft)
        self._sound_player = SoundPlayer(SOUNDS_DIR)

        # Walk state. Position is initialized later in showEvent() once the
        # window has its real size from the compositor.
        self._feet_x: float = 0.0
        # Her feet's Y. Normally the ground line (bottom), but dragging can set it
        # anywhere, and she then walks left/right along that height.
        self._feet_y: float = 0.0
        self._ground_y: int = 0
        self._state: State = State.IDLE
        self._direction: Direction = Direction.LEFT
        self._target_x: float = 0.0
        self._frame_index: int = 0
        self._distance_since_last_step: float = 0.0
        self._has_started: bool = False

        # Drag-to-reposition state. A press on her arms a possible drag; once the
        # cursor moves past the threshold she's "picked up" (walking pauses) and
        # follows the cursor until release. _drag_grab_dx/dy keep her steady under
        # the cursor (offset from the click point to her feet coordinate).
        self._drag_armed: bool = False
        self._dragging_buddy: bool = False
        self._drag_press_x: int = 0
        self._drag_press_y: int = 0
        self._drag_grab_dx: float = 0.0
        self._drag_grab_dy: float = 0.0

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
        self.brief_ready.connect(self._on_brief_ready)
        self.draft_ready.connect(self._on_draft_ready)

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
        self._feet_y = self._ground_y  # start on the floor

        self._show_sprite(IDLE_SPRITE)
        self._begin_walking()

        # Once she's settled: in test mode, preview a reminder; otherwise give
        # the normal startup greeting (which then resumes the recurring talk
        # cycle via _on_bubble_hidden()).
        if self._simulate_reminder_on_start:
            QTimer.singleShot(SIMULATE_REMINDER_DELAY_MS, self._simulate_reminder)
        elif (
            self._brief_now_on_start
            or self._brief_mock_on_start
            or self._claim_todays_brief()
        ):
            # First launch of the day (or a --brief-now/--brief-mock test flag):
            # the morning brief stands in for the plain welcome-back greeting.
            # Order matters — a test flag short-circuits before _claim_todays_brief
            # so forcing the brief never consumes the real once-a-day marker.
            QTimer.singleShot(STARTUP_GREETING_DELAY_MS, self._deliver_startup_brief)
        else:
            self._startup_timer.start(STARTUP_GREETING_DELAY_MS)

        # The content plan, once she's settled (independent of the greeting):
        # with --plan-week she researches a fresh plan; on a normal launch she
        # just shows the last saved plan from disk — no API call, no cost.
        if self._plan_week_on_start:
            QTimer.singleShot(PLAN_WEEK_DELAY_MS, self._start_weekly_plan)
        else:
            QTimer.singleShot(PLAN_PANEL_SHOW_DELAY_MS, self._show_saved_plan_panel)

        # Draft-replies test flags: with --draft-mock she drafts from free sample
        # data (no API, no Gmail); with --draft-now she runs the real (paid) path.
        # Without a flag, drafting only ever happens when Camille presses "D".
        if self._draft_now_on_start or self._draft_mock_on_start:
            QTimer.singleShot(
                DRAFT_DELAY_MS,
                lambda: self._start_drafts(use_mock=self._draft_mock_on_start),
            )

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
        self._feet_y = self._ground_y  # a resize re-anchors her to the floor

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
        """Move the sprite label to the current feet coordinate and refresh the input mask.

        While a speech bubble is showing, re-anchor it to her too, so it follows
        in real time as she walks or is dragged (not just when it first appears).
        """
        sprite_width = self._sprite_label.width()
        sprite_height = self._sprite_label.height()
        left_x = int(self._feet_x - sprite_width / 2)
        top_y = int(self._feet_y - sprite_height)
        self._sprite_label.move(left_x, top_y)
        if self._speech_bubble.isVisible():
            self._position_bubble()
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
        if self._draft_panel.isVisible():
            region = region.united(QRegion(self._draft_panel.geometry()))
        self.setMask(region)

    # --- dragging the buddy ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Arm a possible pick-up when she's pressed (the cards handle their own clicks).

        A left-press landing on her sprite arms a drag whether she's idle,
        walking, or mid-speech — when she's talking the bubble simply comes
        along (see mouseMoveEvent). Nothing moves yet: a bare click (no drag)
        leaves her undisturbed.
        """
        point = event.position().toPoint()
        on_buddy = self._sprite_label.geometry().contains(point)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and on_buddy
            and self._state in (State.IDLE, State.WALKING, State.TALKING)
        ):
            self._drag_armed = True
            self._dragging_buddy = False
            self._drag_press_x = point.x()
            self._drag_press_y = point.y()
            self._drag_grab_dx = self._feet_x - point.x()
            self._drag_grab_dy = self._feet_y - point.y()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Once the press travels past the threshold, pick her up and follow the cursor."""
        if not self._drag_armed:
            super().mouseMoveEvent(event)
            return
        point = event.position().toPoint()
        if not self._dragging_buddy:
            moved = abs(point.x() - self._drag_press_x) + abs(point.y() - self._drag_press_y)
            if moved < BUDDY_DRAG_THRESHOLD_PX:
                return
            # Crossed the threshold: pick her up.
            self._dragging_buddy = True
            self._idle_timer.stop()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._state == State.TALKING:
                # Picked up mid-sentence: keep the bubble showing and pause its
                # countdown so the talk doesn't fade out while she's being moved;
                # it resumes when she's dropped (see mouseReleaseEvent).
                self._bubble_hold_timer.stop()
            else:
                # Picked up while walking/resting: pause the wander and show the
                # idle pose so she reads as "held" rather than mid-stride.
                self._move_timer.stop()
                self._state = State.IDLE
                self._show_sprite(IDLE_SPRITE)
        self._feet_x = self._clamp_feet_x(point.x() + self._drag_grab_dx)
        self._feet_y = self._clamp_feet_y(point.y() + self._drag_grab_dy)
        self._reposition_sprite()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Drop her where released and resume from that spot.

        If she was mid-speech when picked up, restart the bubble's hold so she
        finishes her sentence from the new spot; otherwise settle into a rest
        and pick up her normal wander again.
        """
        if self._drag_armed:
            was_dragging = self._dragging_buddy
            self._drag_armed = False
            self._dragging_buddy = False
            if was_dragging:
                self.unsetCursor()
                if self._state == State.TALKING:
                    self._bubble_hold_timer.start(BUBBLE_HOLD_MS)
                else:
                    self._begin_resting()  # settle, then wander again
            return
        super().mouseReleaseEvent(event)

    def _clamp_feet_x(self, feet_x: float) -> float:
        """Keep her horizontally on-screen (feet point is her horizontal centre)."""
        half = self._sprite_label.width() / 2
        return max(half, min(feet_x, self.width() - half))

    def _clamp_feet_y(self, feet_y: float) -> float:
        """Keep her vertically on-screen (feet point is the bottom of the sprite)."""
        height = self._sprite_label.height()
        return max(height, min(feet_y, self.height()))

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
        if self._state == State.TALKING or self._dragging_buddy:
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
        """Anchor the speech bubble to the buddy's CURRENT head position, on-screen.

        Centred just above her head by default. Anchoring to her live feet/head
        position (not the fixed ground line) is what lets the bubble follow her
        as she walks or is dragged anywhere on screen. Two edge cases keep it
        fully visible: near the left/right edge it's nudged inward, and near the
        top — with no room above her — it flips to sit just below her with the
        tail pointing up at her instead of being clipped.
        """
        bubble_width = self._speech_bubble.width()
        bubble_height = self._speech_bubble.height()
        sprite_top_y = self._feet_y - self._sprite_label.height()

        # Horizontal: centre on her, then nudge fully on-screen.
        left_x = int(self._feet_x - bubble_width / 2)
        max_left_x = self.width() - EDGE_MARGIN_PX - bubble_width
        left_x = max(EDGE_MARGIN_PX, min(left_x, max_left_x))

        # Vertical: prefer just above her head; flip below if it wouldn't fit.
        above_top_y = int(sprite_top_y - bubble_height - BUBBLE_GAP_ABOVE_HEAD_PX)
        if above_top_y >= EDGE_MARGIN_PX:
            self._speech_bubble.set_tail_pointing_up(False)
            top_y = above_top_y
        else:
            self._speech_bubble.set_tail_pointing_up(True)
            max_top_y = self.height() - EDGE_MARGIN_PX - bubble_height
            top_y = min(int(self._feet_y + BUBBLE_GAP_ABOVE_HEAD_PX), max_top_y)

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

    # --- daily-summary panel ---

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

    def _retract_callout_panel(self) -> None:
        """Retract the daily-summary card into the buddy (its ✕ button); 'P' reopens."""
        if self._callout_panel.is_open:
            self._callout_panel.retract(self._sprite_label.geometry().center())

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

    # --- morning brief ---

    def _claim_todays_brief(self) -> bool:
        """True the first time she launches on a new day — and marks today claimed.

        Compares today's date against the date stored in a small local state file
        (gitignored) and, on the first launch of a new day, rewrites it with
        today's so later relaunches the same day return False and skip the brief.
        Any read/write hiccup is treated as "not done yet", so the worst case is
        the brief showing again rather than a crash or a silently swallowed day.
        """
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        try:
            saved = json.loads(BRIEF_STATE_PATH.read_text(encoding="utf-8"))
            already_today = saved.get("last_brief_date") == today
        except (OSError, ValueError):
            already_today = False
        if already_today:
            return False
        try:
            BRIEF_STATE_PATH.write_text(
                json.dumps({"last_brief_date": today}), encoding="utf-8"
            )
        except OSError:
            pass
        return True

    def _run_morning_brief(self) -> None:
        """Gather today's brief in the background and speak it in her bubble.

        The reusable core shared by the first-launch auto-brief and the manual
        "B" key. Gathering touches the network (weather + calendar + Gmail), so it
        runs off the GUI thread to keep her from freezing mid-step; the composed
        words come back via the brief_ready signal (see _on_brief_ready), with a
        fresh weather/calendar/email fetch each time it's called. It deliberately
        never touches the once-a-day marker, so pressing "B" any number of times
        today has no effect on tomorrow's automatic morning brief — only the
        first-launch path (_claim_todays_brief) ever claims the day.
        """
        threading.Thread(
            target=self._gather_brief_worker, name="morning-brief", daemon=True
        ).start()

    def _deliver_startup_brief(self) -> None:
        """First-launch path: speak the brief and auto-open the post-it.

        Wraps the shared brief core with the post-it pop the normal welcome-back
        greeting also does, so the day's first brief shows the card too. The
        manual "B" key calls the core alone — bubble and voice only, no panel.
        """
        self._run_morning_brief()
        self._startup_panel_timer.start(STARTUP_PANEL_DELAY_MS)

    def _gather_brief_worker(self) -> None:
        """Compose the brief off the GUI thread and hand the words back via a signal.

        --brief-mock uses fixed sample data (no calls, no cost); otherwise she
        gathers live weather/calendar/email. The brief already drops any single
        source that fails on its own; we still guard the unexpected here so a bad
        morning can never take the buddy down at startup — worst case she simply
        skips the brief (an empty string, handled in _on_brief_ready).
        """
        try:
            brief = mock_brief() if self._brief_mock_on_start else gather_brief()
        except Exception:  # noqa: BLE001 — a startup nicety must never crash the app
            brief = ""
        self.brief_ready.emit(brief)

    def _on_brief_ready(self, brief: str) -> None:
        """Speak the gathered brief in her bubble + recorded voice (GUI thread).

        Reached via the brief_ready signal once the background gather finishes. An
        empty string means gathering fell over entirely — she just stays quiet
        rather than popping a blank bubble. Otherwise the words appear in the
        bubble while her recorded "good morning" clip plays alongside, and the
        normal talk cycle resumes afterwards via _on_bubble_hidden().
        """
        if brief:
            self._begin_talking(brief, voice=BRIEF_VOICE_FILENAME)

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

    def _show_saved_plan_panel(self) -> None:
        """On a normal launch, quietly show the last saved plan — no API, no talk.

        Reads weekly_plan.json from disk and pops the panel in its remembered
        spot. If nothing's been planned yet, it shows nothing (no empty card).
        """
        self._populate_plan_panel(load_plan_payload())

    def _populate_plan_panel(self, plan: dict) -> bool:
        """Fill the panel from a plan dict and show it; return True if it had a plan.

        Shows nothing when the plan has no pieces (none saved yet, or a failed
        run), so an empty card never pops onto the desktop. Reused by the launch
        path and the --plan-week generation path.
        """
        pieces = plan.get("pieces") or []
        if not pieces:
            return False
        rows = [
            (piece.get("day", ""), piece.get("format", ""),
             piece.get("topic") or piece.get("idea", ""))
            for piece in pieces
        ]
        self._plan_panel.set_overview(plan.get("week_of", ""), rows)
        self._plan_has_content = True
        if self._plan_panel.is_open:
            self._plan_panel.raise_()
            self._update_input_mask()
        else:
            self._plan_panel.show_panel()
        return True

    def _on_plan_ready(self, status: str) -> None:
        """Show the freshly generated overview panel and give a gentle spoken update.

        `status` is empty on full success, or a friendly message describing a
        problem. When the plan itself was built (it has pieces) the panel is
        shown regardless, so a Notion-only hiccup still leaves the overview up
        with the issue explained out loud.
        """
        had_plan = self._populate_plan_panel(load_plan_payload())
        if not had_plan:
            message = status or PLAN_FAILED_MESSAGE
        elif status:
            message = status
        elif self._plan_week_mock:
            message = PLAN_MOCK_READY_MESSAGE
        else:
            message = PLAN_READY_MESSAGE
        self._begin_talking(message, play_voice=False)

    def _toggle_plan_panel(self) -> None:
        """The 'W' key: reopen the plan card if closed, else minimize/restore it.

        Reopening only happens once a plan has actually been loaded, so pressing
        'W' on a fresh launch with nothing planned never pops an empty card.
        """
        if self._plan_panel.is_open:
            self._plan_panel.toggle_minimized()
        elif self._plan_has_content:
            self._plan_panel.show_panel()

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

    # --- email draft assistant ---

    def _start_drafts(self, use_mock: bool = False) -> None:
        """Give a gentle heads-up and draft replies in the background.

        The "D" key calls this with the real path (use_mock=False); the
        --draft-mock launch flag passes use_mock=True for a free, no-API/no-Gmail
        preview. Either way the work runs off the GUI thread so she keeps strolling
        while the inbox is read and the (one-per-email) drafts are written.
        """
        self._begin_talking(DRAFT_WORKING_MESSAGE, play_voice=False)
        threading.Thread(
            target=self._draft_worker, args=(use_mock,), name="draft-replies", daemon=True
        ).start()

    def _draft_worker(self, use_mock: bool) -> None:
        """Draft replies off the GUI thread and hand the batch back via a signal.

        draft_replies already turns every expected problem (missing key, offline,
        a draft call that fails) into a friendly message or a skipped email rather
        than raising, so there's always something kind to show. We still guard the
        unexpected here so a bad inbox can never take the buddy down.
        """
        try:
            batch = draft_replies(use_mock=use_mock)
        except Exception:  # noqa: BLE001 — a background nicety must never crash the app
            batch = DraftBatch(drafts=[], message=DRAFT_FAILED_MESSAGE)
        self.draft_ready.emit(batch)

    def _on_draft_ready(self, batch: DraftBatch) -> None:
        """Show the drafts in the panel and give a gentle spoken update (GUI thread).

        When there are drafts, the panel is filled and shown and she says how many
        are ready. Otherwise (nothing to reply to, missing key, offline) she simply
        speaks the friendly note the batch carries — no empty card pops up.
        """
        if batch.drafts:
            rows = [
                (draft.sender_name, draft.subject, draft.draft_body, draft.gmail_url)
                for draft in batch.drafts
            ]
            self._draft_panel.set_drafts(rows)
            if self._draft_panel.is_open:
                self._draft_panel.raise_()
                self._update_input_mask()
            else:
                self._draft_panel.show_panel()
            count = len(batch.drafts)
            message = (
                DRAFT_READY_MESSAGE_ONE
                if count == 1
                else DRAFT_READY_MESSAGE_MANY.format(count=count)
            )
            self._begin_talking(message, play_voice=False)
        else:
            self._begin_talking(batch.message or DRAFT_FAILED_MESSAGE, play_voice=False)

    def _open_draft(self, url: str) -> None:
        """Open a prefilled Gmail compose window for one draft (the panel's button).

        She only ever OPENS a compose window — Camille reviews and sends it
        herself. A friendly message stands in if no browser can be opened.
        """
        try:
            opened = webbrowser.open(url)
        except OSError:
            opened = False
        if not opened:
            self._begin_talking(DRAFT_OPEN_FAILED_MESSAGE, play_voice=False)

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
        """Handle keys: Escape closes; Space talks; P pops the panel; G replays the greeting; B re-shows today's brief; D drafts email replies; R previews a reminder; W reopens/minimizes the plan panel.

        All require the overlay to hold keyboard focus — clicking the buddy
        gives it focus. Spacebar triggers the same talk as the timer; "P"
        toggles the daily-summary panel;
        "G" replays the startup greeting + panel; "B" re-shows today's morning
        brief on demand (re-fetching live weather, without affecting tomorrow's
        automatic one); "D" reads today's important emails (read-only) and drafts
        a reply for each to review and send herself; "R" previews an event
        reminder (bubble + post-it) without waiting for a real calendar event;
        "W" reopens the weekly-plan panel when closed, otherwise minimizes/restores it.
        """
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_Space:
            self._begin_talking()
        elif event.key() == Qt.Key.Key_P:
            self._toggle_panel()
        elif event.key() == Qt.Key.Key_G:
            self._run_startup_greeting()
        elif event.key() == Qt.Key.Key_B:
            self._run_morning_brief()
        elif event.key() == Qt.Key.Key_D:
            self._start_drafts()
        elif event.key() == Qt.Key.Key_R:
            self._simulate_reminder()
        elif event.key() == Qt.Key.Key_W:
            self._toggle_plan_panel()
        else:
            super().keyPressEvent(event)


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
