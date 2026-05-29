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

import random
import sys
import threading
import webbrowser
from enum import Enum, auto
from http.server import ThreadingHTTPServer
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
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
from callout_panel import CalloutPanel
from callout_server import HOST, PORT, create_server
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

# A warm hello a few seconds after launch, then spontaneous talks on a gentle
# recurring timer. Each interval is randomised within the range so she doesn't
# speak like clockwork. She can also be triggered on demand with the spacebar
# (handy for testing without waiting for the timer).
FIRST_TALK_DELAY_MS = 4000
TALK_INTERVAL_MIN_MS = 20 * 60 * 1000
TALK_INTERVAL_MAX_MS = 30 * 60 * 1000

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

    # --- setup ---

    def __init__(self) -> None:
        super().__init__()
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

        self._voice_delay_timer = QTimer(self)
        self._voice_delay_timer.setSingleShot(True)
        self._voice_delay_timer.timeout.connect(self._sound_player.play_random_voice)

        self._bubble_hold_timer = QTimer(self)
        self._bubble_hold_timer.setSingleShot(True)
        self._bubble_hold_timer.timeout.connect(self._end_talking)

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

        # First warm hello shortly after launch; later talks are queued by
        # _on_bubble_hidden() once each one finishes.
        self._talk_timer.start(FIRST_TALK_DELAY_MS)

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
            self._callout_panel.reposition(self._callout_panel.left_slot_rect(self.height()))
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

    def _begin_talking(self, message: str | None = None, *, play_voice: bool = True) -> None:
        """Pause wandering to show a speech bubble and emote, optionally with voice.

        With no message she shares a random encouragement and plays the
        attention pop followed by a voice clip. Callers can pass a specific
        message (e.g. a friendly error) and set play_voice=False for a silent
        bubble. _bubble_hold_timer later fires _end_talking() to fade the
        bubble out and resume her normal wander.

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
        """Pop the proof-of-concept daily-summary panel out of the buddy, or retract it.

        The panel grows out of (and retracts into) her current on-screen
        center, then parks against the left edge. Toggling mid-animation just
        reverses smoothly because the animation is restarted from wherever the
        card currently is.
        """
        seed_center = self._sprite_label.geometry().center()
        if self._callout_panel.is_open:
            self._callout_panel.retract(seed_center)
        else:
            final_rect = self._callout_panel.left_slot_rect(self.height())
            self._callout_panel.pop_out(seed_center, final_rect)

    # --- input ---

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keys: Escape closes, Spacebar talks, "C" opens the summary, "P" pops the panel.

        All require the overlay to hold keyboard focus — clicking the buddy
        gives it focus. Spacebar triggers the same talk as the timer; "C" opens
        the callout in the default browser; "P" toggles the proof-of-concept
        daily-summary panel that grows out of her.
        """
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_Space:
            self._begin_talking()
        elif event.key() == Qt.Key.Key_C:
            self._open_callout()
        elif event.key() == Qt.Key.Key_P:
            self._toggle_panel()
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
    callout_server = _start_callout_server()
    overlay = BuddyOverlay()
    overlay.showMaximized()
    try:
        return app.exec()
    finally:
        # Shut the server down so no thread or socket is left behind on exit.
        if callout_server is not None:
            callout_server.shutdown()
            callout_server.server_close()


if __name__ == "__main__":
    sys.exit(main())
