"""The desktop "post-it" daily-summary panel that grows out of the buddy.

A tall pixel-art planner (postit_design.png) is drawn as the panel background,
pinned to the left edge of the overlay, and today's live content is painted on
top in its sections:

  * the date,
  * today's real Google Calendar events (via calendar_sync),
  * a Must-Do list and Top 3 Goals (placeholder items for now), and
  * a short note from the buddy.

Events and checklist items are click-to-toggle: clicking one strikes it through
and fades it ("done"), matching the browser callout. Events that have already
ended start done. The panel animates its own geometry from a small seed near
the buddy out to its parked slot, so it looks like it grows out of her.

It can be dragged anywhere (grab an empty area) and resized like a window: grab
the top/bottom edge or a corner to make it shorter or taller. The planner is
painted at its full size, so the text stays the same readable size; when the
window is shorter than the planner the content scrolls (mouse wheel), with a slim
scrollbar. Its dragged position and chosen height are remembered between launches.

Privacy: calendar data is held only in memory for painting and is never written
to disk or logged, per the project's security rules.

Font: "Fredoka" by Hanken Design Co., licensed under the SIL Open Font
License 1.1 and bundled in assets/fonts/ (see assets/fonts/OFL.txt). A
system-font fallback is used if the bundled file is ever missing.
"""

# === IMPORTS ===

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QEnterEvent,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QPushButton, QWidget

from calendar_sync import CalendarEvent, CalendarSyncError, fetch_todays_events


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent

# Tall pixel-art planner used as the panel background (project root).
BACKGROUND_PATH = PROJECT_DIR / "postit_design.png"

# Bundled cute rounded font (SIL OFL). System fallbacks if the file is missing.
FONT_PATH = PROJECT_DIR / "assets" / "fonts" / "Fredoka-VariableFont.ttf"
PANEL_FONT_FALLBACK_FAMILIES = ["Quicksand", "Comfortaa", "Nunito", "Sans Serif"]

# --- Palette: crisp near-black text for readability on the pink pixel-art ---
TEXT_COLOR = QColor(34, 24, 28)         # near-black for normal text
TIME_COLOR = QColor(58, 42, 48)         # very dark, faintly warm, for event times
DATE_COLOR = QColor(34, 24, 28)
NOTE_COLOR = QColor(34, 24, 28)
DONE_COLOR = QColor(120, 108, 112)      # muted grey: faded "done" items
CHECK_COLOR = QColor(176, 40, 70)       # deep rose tick inside checkboxes
CHECK_BOX_BORDER_COLOR = QColor(214, 110, 138)  # outline of drawn checkboxes

# --- Panel sizing and parking ---
# The panel height is a fraction of the overlay height; width follows the
# design's aspect ratio so the pixel-art is never distorted.
PANEL_HEIGHT_FRAC = 0.92
PANEL_LEFT_MARGIN_PX = 28

# --- Font sizes, as a fraction of the panel HEIGHT (so they scale together) ---
# Bigger now that the design has roomy empty boxes instead of ruled lines.
DATE_FONT_FRAC = 0.0150
EVENT_FONT_FRAC = 0.0185
CHECK_FONT_FRAC = 0.0185
NOTE_FONT_FRAC = 0.0175

# --- Section boxes, as (x, y, w, h) fractions of panel width/height ---
# Measured from postit_design.png (1536x2752): the empty pink box under each
# header. Live text is laid out INSIDE these, evenly spaced with padding.
DATE_BOX_FRAC = (0.447, 0.143, 0.234, 0.027)
EVENTS_BOX_FRAC = (0.093, 0.2195, 0.813, 0.1408)
MUSTDO_BOX_FRAC = (0.093, 0.4148, 0.813, 0.1412)
GOALS_BOX_FRAC = (0.093, 0.6096, 0.813, 0.1409)
NOTE_BOX_FRAC = (0.093, 0.8032, 0.813, 0.1417)

# Inner padding inside each content box before text starts.
BOX_PAD_X_FRAC = 0.030       # of panel width (left/right breathing room)
BOX_PAD_Y_FRAC = 0.012       # of panel height (top/bottom breathing room)

# Most items to show per section before the box runs out of comfortable room.
EVENTS_MAX_ROWS = 5
MUSTDO_MAX_ITEMS = 5
GOALS_MAX_ITEMS = 3

# Drawn checkbox for Must-Do / Top 3 Goals items: a square outline with the
# label to its right; a tick is drawn inside when the item is done.
CHECK_BOX_SIZE_FRAC = 0.024      # side length as a fraction of panel height
CHECK_BOX_BORDER_PX = 3
CHECK_BOX_GAP_FRAC = 0.018       # of panel width, gap between box and label

# --- Interaction / messages ---
EVENTS_LOADING_MESSAGE = "Loading your day…"
EVENTS_EMPTY_MESSAGE = "Nothing on your calendar today. 🤍"
DATE_FORMAT = "%a, %b %-d"   # compact for the small date box, e.g. "Fri, May 29"

# --- "Grow out of the buddy" pop ---
PANEL_SEED_SIZE_PX = 24
PANEL_POP_MS = 420
PANEL_RETRACT_MS = 300

# --- Dragging, resizing & remembered geometry ---
# The panel is click-draggable (drag any empty part to move it) and height-
# resizable (see below). Its last position AND height are remembered in a tiny
# local JSON file kept OUT of the repo (see .gitignore) — it holds only on-screen
# geometry, never calendar or other personal data — so reopening matches.
PANEL_STATE_PATH = PROJECT_DIR / "panel_state.json"

# --- Resizing (browser-style window + scroll) ---
# The planner is painted at its full natural size (so the text stays the same,
# readable size); the card is a resizable WINDOW onto it. Grab any edge or
# corner (within this margin) to make the window narrower/wider or shorter/
# taller; when it's smaller than the full planner, the content scrolls (mouse
# wheel vertically, Shift+wheel horizontally), with slim scrollbars. The full
# planner size is the default and the maximum (no scrollbars at full size).
RESIZE_MARGIN_PX = 12
# Smallest the window may get in each dimension, as a fraction of the full
# planner size (keeps it usable); the largest is the full planner (the default).
PANEL_MIN_VIEW_FRAC = 0.32
# Pixels scrolled per mouse-wheel notch.
SCROLL_STEP_PX = 90
# Slim scrollbar shown on the right when the window is shorter than the planner.
SCROLLBAR_WIDTH_PX = 5
SCROLLBAR_MARGIN_PX = 4
SCROLLBAR_MIN_THUMB_PX = 28
SCROLLBAR_COLOR = QColor(120, 108, 112, 130)

# --- Window controls (hover-reveal buttons) ---
# Two small buttons (restore-to-full, close) fade in at the top-right when the
# pointer is over the card, and fade out otherwise — so the hand-painted art is
# left untouched whenever it's just being looked at. They're positioned by
# fraction of the window, landing in the plain-pink band right of the "Date:" box,
# clear of the corner flowers and the heart border.
CONTROL_BUTTON_SIZE_PX = 22
CONTROL_BUTTON_SPACING_PX = 6
CONTROL_TOP_FRAC = 0.085       # top inset, just below the flower/heart/title row
CONTROL_RIGHT_FRAC = 0.07      # right inset, clear of the right edge
CONTROL_FADE_MS = 140          # gentle fade in/out
MAXIMIZE_GLYPH = "□"
CLOSE_GLYPH = "✕"
# Glyph colour for the controls: the same deep rose as the checkbox ticks, so the
# buttons feel part of the art rather than bolted on.
CONTROL_GLYPH_COLOR = "#b02846"   # matches CHECK_COLOR

# Hold off painting overlaid text until the card has nearly finished growing,
# so the seed reads as a clean nub rather than clipped text.
PANEL_CONTENT_REVEAL_FRACTION = 0.85

# Combined alignment flag for a single left-aligned, vertically-centred line.
_LINE_FLAGS = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

# Family name the bundled font registers as, resolved once on first use.
_loaded_font_family: str | None = None


def _panel_font(pixel_size: int, *, bold: bool = False, strike: bool = False) -> QFont:
    """Return the bundled Fredoka font at a pixel size, loading it once.

    Pixel sizing (not point sizing) keeps the overlaid text scaling in lockstep
    with the background image. Requires a running QApplication, so it is called
    when the panel is built, never at import time.
    """
    global _loaded_font_family
    if _loaded_font_family is None:
        font_id = QFontDatabase.addApplicationFont(str(FONT_PATH))
        families = QFontDatabase.applicationFontFamilies(font_id)
        _loaded_font_family = families[0] if families else ""

    font = QFont()
    if _loaded_font_family:
        font.setFamily(_loaded_font_family)
    else:
        font.setFamilies(PANEL_FONT_FALLBACK_FAMILIES)
    font.setPixelSize(max(1, pixel_size))
    font.setBold(bold)
    font.setStrikeOut(strike)
    return font


# === CONTENT MODEL ===

@dataclass
class EventRow:
    """One calendar event as shown in the panel; `done` toggles on click."""
    title: str
    time_label: str
    done: bool


@dataclass
class ChecklistItem:
    """One Must-Do/Goal line; `done` toggles its checkbox and strike-through."""
    label: str
    done: bool = False


@dataclass
class _InteractiveRow:
    """A laid-out, clickable row: where to draw it and which item it toggles."""
    item: EventRow | ChecklistItem
    hit_rect: QRect
    label_rect: QRect
    box_rect: QRect | None   # checkbox square, or None for event rows
    time_label: str | None   # event time, or None for checklist rows


# === CALLOUT PANEL ===

class CalloutPanel(QWidget):
    """The pixel-art daily-summary panel that pops out from the buddy.

    It paints the planner artwork as a background and overlays today's date,
    live calendar events, placeholder checklists, and a note. Rows are click-to-
    toggle (strike-through + fade). The widget animates its own geometry between
    a small seed near the buddy and a slot pinned to the left edge; the owner's
    `on_geometry_change` callback fires each frame so the overlay can keep its
    click-through mask in sync.
    """

    # Emitted from the background fetch thread; delivered on the GUI thread.
    events_loaded = pyqtSignal(list, str)
    # Emitted when the ✕ control is clicked, so the owner can retract the card
    # into the buddy (keeping the pretty animation, and letting 'P' reopen it).
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget, on_geometry_change: Callable[[], None]) -> None:
        super().__init__(parent)

        self._background = QPixmap(str(BACKGROUND_PATH))
        self._background_scaled = QPixmap()

        # Content. Events arrive asynchronously; checklists/note are set by the
        # owner. _events_state drives whether we show rows or a message.
        self._date_text: str = ""
        self._events: list[EventRow] = []
        self._events_state: str = "loading"
        self._events_message: str = EVENTS_LOADING_MESSAGE
        self._events_requested: bool = False
        self._must_do: list[ChecklistItem] = []
        self._goals: list[ChecklistItem] = []
        self._note_text: str = ""

        self._on_geometry_change = on_geometry_change
        self._is_open: bool = False
        self._final_rect = QRect()
        self._fetch_thread: threading.Thread | None = None

        # Dragging: the panel can be picked up from any empty area and moved.
        # _saved_top_left (loaded from disk) is where it reopens; None means use
        # the default left slot. _drag_moved guards against saving on a bare
        # click that didn't actually move it.
        self._dragging: bool = False
        self._drag_moved: bool = False
        self._drag_offset: QPoint = QPoint()
        self._saved_top_left, self._saved_view_size = self._load_saved_state()

        # Resizing: grab any edge or corner to change the window's width and/or
        # height; the planner is painted full-size and scrolled inside it.
        # _saved_view_size (loaded above) is remembered across launches; the
        # _scroll_* are the current scroll offsets into the full-size planner.
        self._resizing: bool = False
        self._resize_moved: bool = False
        self._resize_edges: tuple[bool, bool, bool, bool] = (False, False, False, False)
        self._resize_start_rect: QRect = QRect()
        self._resize_start_mouse: QPoint = QPoint()
        self._scroll_x: int = 0
        self._scroll_y: int = 0
        # Track the cursor even with no button held, so edges show a resize arrow.
        self.setMouseTracking(True)

        self.events_loaded.connect(self._on_events_loaded)

        # Animates the QRect geometry for the grow/retract pop.
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

        # The hover-reveal window controls (restore-to-full and close).
        self._build_controls()

    # --- public API ---

    def set_checklists(self, must_do: list[str], goals: list[str]) -> None:
        """Set the placeholder Must-Do and Top 3 Goals items (all start undone)."""
        self._must_do = [ChecklistItem(label) for label in must_do[:MUSTDO_MAX_ITEMS]]
        self._goals = [ChecklistItem(label) for label in goals[:GOALS_MAX_ITEMS]]
        self.update()

    def set_note(self, text: str) -> None:
        """Set the short 'note from your buddy' message."""
        self._note_text = text
        self.update()

    @property
    def is_open(self) -> bool:
        """True while the panel is open (popped out), even mid-animation."""
        return self._is_open

    def left_slot_rect(self, overlay_height: int) -> QRect:
        """Return the default parked geometry against the left edge, vertically centred."""
        height = int(overlay_height * PANEL_HEIGHT_FRAC)
        width = self._width_for_height(height)
        top_y = max(0, (overlay_height - height) // 2)
        return QRect(PANEL_LEFT_MARGIN_PX, top_y, width, height)

    def parked_rect(self, overlay_height: int) -> QRect:
        """Where the panel parks when open: the user's saved spot and size, else the
        default left slot (the full planner — the original size).

        The window is a resizable viewport onto the full-size planner; its width
        and height are both remembered. A saved size is clamped to the min/full-
        planner range, and the position is clamped back on-screen, in case the
        display changed since it was set.
        """
        default = self.left_slot_rect(overlay_height)  # full planner (the max / original)
        size = self._clamped_view_size(
            self._saved_view_size if self._saved_view_size is not None else default.size(),
            default.size(),
        )
        top_left = self._saved_top_left if self._saved_top_left is not None else default.topLeft()
        return self._clamp_to_parent(QRect(top_left, size))

    def pop_out(self, seed_center: QPoint, final_rect: QRect) -> None:
        """Grow from a small seed at seed_center out to final_rect, with a pop."""
        self._is_open = True
        self._hide_controls_immediately()
        self._final_rect = final_rect
        self._scroll_x = 0  # always open scrolled to the top-left
        self._scroll_y = 0
        content_w, content_h = self._content_size()
        self._rescale_background(content_w, content_h)
        self._refresh_date()
        self._request_events_once()
        self.setGeometry(self._seed_rect(seed_center))
        self.show()
        self.raise_()
        self._animate(final_rect, PANEL_POP_MS, QEasingCurve.Type.OutBack)

    def retract(self, seed_center: QPoint) -> None:
        """Shrink back into a small seed at seed_center, then hide on finish."""
        self._is_open = False
        self._animate(self._seed_rect(seed_center), PANEL_RETRACT_MS, QEasingCurve.Type.InBack)

    def reposition(self, final_rect: QRect) -> None:
        """Snap to a freshly computed slot (e.g. after the overlay resizes)."""
        self._final_rect = final_rect
        if self._is_open and self._anim.state() != QAbstractAnimation.State.Running:
            content_w, content_h = self._content_size()
            self._rescale_background(content_w, content_h)
            self.setGeometry(final_rect)
            self._clamp_scroll()
            self._on_geometry_change()

    # --- sizing helpers ---

    def _width_for_height(self, height: int) -> int:
        """Width that preserves the background image's aspect ratio."""
        if self._background.isNull() or self._background.height() == 0:
            return height // 2
        return int(height * self._background.width() / self._background.height())

    def _height_for_width(self, width: int) -> int:
        """Height that preserves the background image's aspect ratio for a width."""
        if self._background.isNull() or self._background.width() == 0:
            return width * 2
        return int(width * self._background.height() / self._background.width())

    def _clamped_view_size(self, size: QSize, full_size: QSize) -> QSize:
        """Clamp a window size between the minimum and the full planner size."""
        min_w = int(full_size.width() * PANEL_MIN_VIEW_FRAC)
        min_h = int(full_size.height() * PANEL_MIN_VIEW_FRAC)
        width = max(min_w, min(size.width(), full_size.width()))
        height = max(min_h, min(size.height(), full_size.height()))
        return QSize(width, height)

    def _content_size(self) -> tuple[int, int]:
        """Full natural (width, height) of the planner, sized to the overlay height.

        This is fixed by the screen, NOT the window, so the planner — and its
        text — stay one constant size while the window resizes around them.
        """
        parent = self.parentWidget()
        overlay_height = parent.height() if parent is not None else self.height()
        height = int(overlay_height * PANEL_HEIGHT_FRAC)
        return self._width_for_height(height), height

    def _content_height(self) -> int:
        """Full painted height of the planner (content space)."""
        return self._content_size()[1]

    def _content_width(self) -> int:
        """Full painted width of the planner (content space)."""
        return self._content_size()[0]

    def _max_scroll(self) -> tuple[int, int]:
        """How far the content can scroll horizontally and vertically."""
        content_w, content_h = self._content_size()
        return max(0, content_w - self.width()), max(0, content_h - self.height())

    def _clamp_scroll(self) -> None:
        """Keep both scroll offsets within range (e.g. after a resize)."""
        max_x, max_y = self._max_scroll()
        self._scroll_x = max(0, min(self._scroll_x, max_x))
        self._scroll_y = max(0, min(self._scroll_y, max_y))

    def _rescale_background(self, width: int, height: int) -> None:
        """Cache the artwork scaled to the parked size for crisp, cheap repaints."""
        if self._background.isNull() or width <= 0 or height <= 0:
            return
        self._background_scaled = self._background.scaled(
            width, height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    # --- date & events ---

    def _refresh_date(self) -> None:
        """Recompute today's date label (cheap; done each time the panel opens)."""
        self._date_text = datetime.now().strftime(DATE_FORMAT)

    def _request_events_once(self) -> None:
        """Kick off the one-time background calendar fetch on first open."""
        if self._events_requested:
            return
        self._events_requested = True
        self._events_state = "loading"
        self._events_message = EVENTS_LOADING_MESSAGE
        self._fetch_thread = threading.Thread(
            target=self._fetch_events_worker, name="callout-events", daemon=True
        )
        self._fetch_thread.start()

    def _fetch_events_worker(self) -> None:
        """Fetch today's events off the GUI thread and report via the signal.

        Any failure is reported as a friendly message rather than crashing the
        thread, so the panel always shows something sensible. Event data is only
        passed back for in-memory painting — never written or logged.
        """
        try:
            events = fetch_todays_events()
            self.events_loaded.emit(events, "")
        except CalendarSyncError as error:
            self.events_loaded.emit([], str(error))
        except Exception:  # noqa: BLE001 — keep the UI robust to any I/O failure
            self.events_loaded.emit([], "Couldn't load your events right now.")

    def _on_events_loaded(self, events: list[CalendarEvent], error: str) -> None:
        """Receive fetched events on the GUI thread and refresh the panel."""
        if error:
            self._events_state = "message"
            self._events_message = error
        elif not events:
            self._events_state = "message"
            self._events_message = EVENTS_EMPTY_MESSAGE
        else:
            self._events_state = "ok"
            self._events = [
                EventRow(
                    title=event.title,
                    time_label="All day" if event.all_day else event.start,
                    done=event.past,
                )
                for event in events[:EVENTS_MAX_ROWS]
            ]
        self.update()

    # --- animation ---

    def _animate(self, end_rect: QRect, duration_ms: int, easing: QEasingCurve.Type) -> None:
        """Animate the widget geometry from its current rect to end_rect."""
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(end_rect)
        self._anim.setDuration(duration_ms)
        self._anim.setEasingCurve(easing)
        self._anim.start()

    def _seed_rect(self, center: QPoint) -> QRect:
        """A tiny square centred on the buddy that the card grows out of."""
        half = PANEL_SEED_SIZE_PX // 2
        return QRect(
            center.x() - half, center.y() - half,
            PANEL_SEED_SIZE_PX, PANEL_SEED_SIZE_PX,
        )

    def _on_anim_value_changed(self, _value: object) -> None:
        """Keep the overlay's click-through mask in sync as the card moves."""
        self._on_geometry_change()

    def _on_anim_finished(self) -> None:
        """Settle on the parked slot when opened, or hide once fully retracted."""
        if self._is_open:
            self.setGeometry(self._final_rect)  # OutBack overshoots; settle exactly
        else:
            self.hide()
        self._on_geometry_change()

    # --- window controls (hover-reveal buttons) ---

    def _build_controls(self) -> None:
        """Create the hover-reveal control cluster: full-size and close.

        The buttons share one container so a single opacity animation fades them
        in and out together. They start hidden; `enterEvent` reveals them and
        `leaveEvent` tucks them away, leaving the art untouched at rest.
        """
        self._controls = QWidget(self)
        row = QHBoxLayout(self._controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(CONTROL_BUTTON_SPACING_PX)
        self._maximize_button = self._make_control_button(MAXIMIZE_GLYPH, "Full size", self._on_maximize)
        self._close_button = self._make_control_button(CLOSE_GLYPH, "Close", self._on_close)
        row.addWidget(self._maximize_button)
        row.addWidget(self._close_button)
        self._controls.adjustSize()

        # One opacity effect + animation drives the gentle fade for all three.
        self._controls_opacity = QGraphicsOpacityEffect(self._controls)
        self._controls_opacity.setOpacity(0.0)
        self._controls.setGraphicsEffect(self._controls_opacity)
        self._controls_fade = QPropertyAnimation(self._controls_opacity, b"opacity", self)
        self._controls_fade.setDuration(CONTROL_FADE_MS)
        self._controls_fade.finished.connect(self._on_controls_fade_finished)
        self._controls.hide()

    def _make_control_button(
        self, glyph: str, tooltip: str, handler: "Callable[[], None]"
    ) -> QPushButton:
        """Build one small, round, semi-transparent control button over the art."""
        button = QPushButton(glyph, self._controls)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(CONTROL_BUTTON_SIZE_PX, CONTROL_BUTTON_SIZE_PX)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # don't steal the overlay's key focus
        button.setStyleSheet(
            f"""
            QPushButton {{ color: {CONTROL_GLYPH_COLOR};
                    background: rgba(255, 255, 255, 0.72);
                    border: 1px solid rgba(176, 40, 70, 0.35);
                    border-radius: {CONTROL_BUTTON_SIZE_PX // 2}px;
                    font-size: 12px; font-weight: 600; padding: 0; }}
            QPushButton:hover {{ background: rgba(255, 255, 255, 0.96); }}
            """
        )
        button.clicked.connect(lambda _checked=False: handler())
        return button

    def _position_controls(self) -> None:
        """Place the control cluster in the plain-pink band at the top-right."""
        self._controls.adjustSize()
        x = int(self.width() * (1 - CONTROL_RIGHT_FRAC)) - self._controls.width()
        y = int(self.height() * CONTROL_TOP_FRAC)
        self._controls.move(max(0, x), max(0, y))

    def enterEvent(self, event: QEnterEvent) -> None:
        """Reveal the controls when the pointer moves over the open, full card."""
        self._show_controls()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Hide the controls when the pointer truly leaves the card.

        Moving onto a child button fires leaveEvent on the card too, so only hide
        when the cursor is actually outside the card's bounds.
        """
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._hide_controls()
        super().leaveEvent(event)

    def _show_controls(self) -> None:
        """Fade the controls in — but not while the card is closed or animating."""
        if not self._is_open:
            return
        if self._anim.state() == QAbstractAnimation.State.Running:
            return
        self._position_controls()
        self._controls.show()
        self._controls.raise_()
        self._fade_controls_to(1.0)

    def _hide_controls(self) -> None:
        """Fade the controls out; they hide fully on finish so clicks stop landing."""
        if not self._controls.isVisible():
            return
        self._fade_controls_to(0.0)

    def _hide_controls_immediately(self) -> None:
        """Snap the controls to hidden with no fade (e.g. on open/close)."""
        self._controls_fade.stop()
        self._controls_opacity.setOpacity(0.0)
        self._controls.hide()

    def _fade_controls_to(self, target: float) -> None:
        """Animate the cluster opacity toward target (0 hidden … 1 fully shown)."""
        self._controls_fade.stop()
        self._controls_fade.setStartValue(self._controls_opacity.opacity())
        self._controls_fade.setEndValue(target)
        self._controls_fade.start()

    def _on_controls_fade_finished(self) -> None:
        """Once faded to transparent, hide so the buttons stop catching clicks."""
        if self._controls_opacity.opacity() <= 0.01:
            self._controls.hide()

    def _on_maximize(self) -> None:
        """Grow the card back to its full default post-it size, at its current spot."""
        parent = self.parentWidget()
        full_size = (
            self.left_slot_rect(parent.height()).size() if parent is not None else self.size()
        )
        self._apply_full_size(QRect(self.pos(), full_size))

    def _on_close(self) -> None:
        """Ask the owner to retract the card into the buddy (so 'P' reopens it)."""
        self._hide_controls_immediately()
        self.close_requested.emit()

    def _apply_full_size(self, rect: QRect) -> None:
        """Settle into rect (clamped on-screen) and repaint — used by the □ button."""
        rect = self._clamp_to_parent(rect)
        self._final_rect = rect
        content_w, content_h = self._content_size()
        self._rescale_background(content_w, content_h)
        self.setGeometry(rect)
        self._clamp_scroll()
        self._on_geometry_change()
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the hover controls glued to the top-right as the window resizes."""
        self._position_controls()
        super().resizeEvent(event)

    # --- interaction ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Toggle the clicked row's 'done' state, or pick the panel up to drag it.

        Clicking directly on an event/checklist row toggles it (as before);
        clicking any empty part of the post-it instead begins a drag, so the two
        gestures never fight each other.
        """
        if not self._is_open:
            super().mousePressEvent(event)
            return
        # Pressing the card brings it above the other desktop cards.
        self.raise_()
        self._on_geometry_change()
        point = event.position().toPoint()

        # Any edge or corner grab starts a resize (precedence over the row toggle
        # and drag, but only in the thin border).
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(point)
            if any(edges):
                self._anim.stop()
                self._resizing = True
                self._resize_moved = False
                self._resize_edges = edges
                self._resize_start_rect = self.geometry()
                self._resize_start_mouse = self.mapToParent(point)
                return

        # Rows are laid out in full-planner (content) coordinates, so map the
        # click by the scroll offset before testing which row it hit.
        content_point = QPoint(point.x() + self._scroll_x, point.y() + self._scroll_y)
        for row in self._interactive_rows():
            if row.hit_rect.contains(content_point):
                row.item.done = not row.item.done
                self.update()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            # Empty space: pick the panel up. Cancel any in-progress pop so the
            # drag takes over cleanly, and remember the grab point so the panel
            # stays under the cursor as it moves.
            self._anim.stop()
            self._dragging = True
            self._drag_moved = False
            self._drag_offset = point
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Resize or drag the panel, or show the right cursor when just hovering."""
        point = event.position().toPoint()
        if self._resizing:
            self._perform_resize(self.mapToParent(point))
            return
        if self._dragging:
            self._drag_moved = True
            cursor_in_parent = self.mapToParent(point)
            target = QRect(cursor_in_parent - self._drag_offset, self.size())
            self.move(self._clamp_to_parent(target).topLeft())
            self._on_geometry_change()
            return
        # Idle hover: a resize arrow near the edges, the normal cursor elsewhere.
        if self._is_open:
            self.setCursor(self._cursor_for_edges(self._edges_at(point)))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish a resize or drag and remember the new geometry for next time."""
        if self._resizing:
            self._resizing = False
            if self._resize_moved:
                self._saved_view_size = self.size()
                self._saved_top_left = self.pos()
                self._final_rect = self.geometry()
                self._save_state()
            return
        if self._dragging:
            self._dragging = False
            if self._drag_moved:
                self._saved_top_left = self.pos()
                self._final_rect = QRect(self.pos(), self.size())
                self._save_state()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Scroll the planner inside the window: wheel vertical, Shift+wheel horizontal."""
        max_x, max_y = self._max_scroll()
        if not self._is_open or (max_x == 0 and max_y == 0):
            super().wheelEvent(event)
            return
        notches_y = event.angleDelta().y() / 120.0  # one notch ≈ 120
        notches_x = event.angleDelta().x() / 120.0
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._scroll_x -= int(notches_y * SCROLL_STEP_PX)
        else:
            self._scroll_y -= int(notches_y * SCROLL_STEP_PX)
            self._scroll_x -= int(notches_x * SCROLL_STEP_PX)
        self._clamp_scroll()
        self.update()

    def _edges_at(self, point: QPoint) -> tuple[bool, bool, bool, bool]:
        """Which edges (left, right, top, bottom) the point is within grab range of."""
        margin = RESIZE_MARGIN_PX
        return (
            point.x() <= margin,
            point.x() >= self.width() - margin,
            point.y() <= margin,
            point.y() >= self.height() - margin,
        )

    @staticmethod
    def _cursor_for_edges(edges: tuple[bool, bool, bool, bool]) -> Qt.CursorShape:
        """Pick the resize cursor for the active edge/corner, or the normal arrow."""
        left, right, top, bottom = edges
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def _perform_resize(self, cursor_in_parent: QPoint) -> None:
        """Resize the window's width and/or height as an edge or corner is dragged.

        The planner is painted at its full size; the window is just a viewport, so
        each dimension is clamped between the minimum and the full planner size.
        The un-dragged edges stay anchored and the scroll offsets are re-clamped so
        the content stays in view.
        """
        self._resize_moved = True
        left, right, top, bottom = self._resize_edges
        start = self._resize_start_rect
        dx = cursor_in_parent.x() - self._resize_start_mouse.x()
        dy = cursor_in_parent.y() - self._resize_start_mouse.y()

        new_w, new_h = start.width(), start.height()
        if right:
            new_w = start.width() + dx
        if left:
            new_w = start.width() - dx
        if bottom:
            new_h = start.height() + dy
        if top:
            new_h = start.height() - dy

        content_w, content_h = self._content_size()
        size = self._clamped_view_size(QSize(new_w, new_h), QSize(content_w, content_h))
        new_x = (start.right() + 1 - size.width()) if left else start.x()
        new_y = (start.bottom() + 1 - size.height()) if top else start.y()
        new_rect = self._clamp_to_parent(QRect(QPoint(new_x, new_y), size))

        self._final_rect = new_rect
        self.setGeometry(new_rect)
        self._clamp_scroll()
        self._on_geometry_change()
        self.update()

    def _clamp_to_parent(self, rect: QRect) -> QRect:
        """Nudge a rect so the whole panel stays within the overlay bounds."""
        parent = self.parentWidget()
        if parent is None:
            return rect
        max_x = max(0, parent.width() - rect.width())
        max_y = max(0, parent.height() - rect.height())
        x = min(max(0, rect.x()), max_x)
        y = min(max(0, rect.y()), max_y)
        return QRect(x, y, rect.width(), rect.height())

    # --- remembered position ---

    def _load_saved_state(self) -> tuple[QPoint | None, QSize | None]:
        """Read the remembered panel position and window size from the state file.

        Best-effort and tolerant: a missing/unreadable file — or an older one that
        saved only the position — just means 'use the default' for whatever's
        absent, so a fresh checkout never errors. Only on-screen geometry is
        stored, never calendar data.
        """
        try:
            data = json.loads(PANEL_STATE_PATH.read_text())
        except (OSError, ValueError):
            return None, None
        try:
            point = QPoint(int(data["x"]), int(data["y"]))
        except (KeyError, TypeError, ValueError):
            point = None
        try:
            size = QSize(int(data["w"]), int(data["h"]))
            if size.width() <= 0 or size.height() <= 0:
                size = None
        except (KeyError, TypeError, ValueError):
            size = None
        return point, size

    def _save_state(self) -> None:
        """Write the current panel position and window size to the state file.

        Stores only on-screen geometry. Never raises: if the file can't be
        written, the panel simply won't remember its spot or size next time.
        """
        rect = self.geometry()
        try:
            PANEL_STATE_PATH.write_text(
                json.dumps({"x": rect.x(), "y": rect.y(), "w": rect.width(), "h": rect.height()})
            )
        except OSError:
            pass

    # --- layout ---

    def _interactive_rows(self) -> list[_InteractiveRow]:
        """Lay out every clickable row from the current size (single source of truth)."""
        rows: list[_InteractiveRow] = []
        if self._events_state == "ok":
            rows.extend(self._section_rows(self._events, EVENTS_BOX_FRAC, with_checkbox=False))
        rows.extend(self._section_rows(self._must_do, MUSTDO_BOX_FRAC, with_checkbox=True))
        rows.extend(self._section_rows(self._goals, GOALS_BOX_FRAC, with_checkbox=True))
        return rows

    def _section_rows(
        self,
        items: list,
        box_frac: tuple[float, float, float, float],
        *,
        with_checkbox: bool,
    ) -> list[_InteractiveRow]:
        """Lay out a section's items evenly inside its empty box.

        Items are distributed with equal spacing down the box interior (after
        padding) so they sit comfortably whether there are two or five. Checklist
        sections get a drawn checkbox at the left with the label beside it.
        """
        rows: list[_InteractiveRow] = []
        if not items:
            return rows

        width, height = self._content_size()  # full planner size; rows live in content space
        box_x, box_y, box_w, box_h = box_frac
        pad_x = int(width * BOX_PAD_X_FRAC)
        pad_y = int(height * BOX_PAD_Y_FRAC)
        left = int(width * box_x) + pad_x
        right = int(width * (box_x + box_w)) - pad_x
        top = int(height * box_y) + pad_y
        bottom = int(height * (box_y + box_h)) - pad_y

        slot_h = (bottom - top) / len(items)
        box_side = int(height * CHECK_BOX_SIZE_FRAC)
        gap = int(width * CHECK_BOX_GAP_FRAC)
        for index, item in enumerate(items):
            center_y = int(top + (index + 0.5) * slot_h)
            row_h = int(min(slot_h, height * CHECK_BOX_SIZE_FRAC * 2))
            if with_checkbox:
                box_rect = QRect(left, center_y - box_side // 2, box_side, box_side)
                label_left = left + box_side + gap
            else:
                box_rect = None
                label_left = left
            label_rect = QRect(label_left, center_y - row_h // 2, right - label_left, row_h)
            hit_rect = QRect(left, center_y - int(slot_h // 2), right - left, int(slot_h))
            time_label = getattr(item, "time_label", None)
            rows.append(_InteractiveRow(item, hit_rect, label_rect, box_rect, time_label))
        return rows

    # --- painting ---

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the full-size planner scrolled into the window, then a scrollbar.

        The artwork and text are painted at the planner's full natural height
        (so the text size never changes), shifted up by the scroll offset and
        clipped to the window — that's what makes the window scroll instead of
        zoom. A slim scrollbar is drawn on top when there's more to scroll to.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        content_w, content_h = self._content_size()
        painter.save()
        painter.translate(-self._scroll_x, -self._scroll_y)

        background = self._background_scaled if not self._background_scaled.isNull() else self._background
        if not background.isNull():
            painter.drawPixmap(QRect(0, 0, content_w, content_h), background)

        grown_enough = (
            self.width() >= self._final_rect.width() * PANEL_CONTENT_REVEAL_FRACTION
            and self.height() >= self._final_rect.height() * PANEL_CONTENT_REVEAL_FRACTION
        )
        if grown_enough and not self._final_rect.isEmpty():
            self._paint_content(painter)
        painter.restore()

        self._paint_scrollbars(painter, content_w, content_h)

    def _paint_scrollbars(self, painter: QPainter, content_w: int, content_h: int) -> None:
        """Draw slim scrollbars (right and/or bottom) when the planner exceeds the window."""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SCROLLBAR_COLOR)
        radius = SCROLLBAR_WIDTH_PX / 2
        view_w, view_h = self.width(), self.height()

        max_y = content_h - view_h
        if max_y > 0:
            thumb_h = max(SCROLLBAR_MIN_THUMB_PX, int(view_h * view_h / content_h))
            thumb_y = int((view_h - thumb_h) * (self._scroll_y / max_y))
            x = view_w - SCROLLBAR_WIDTH_PX - SCROLLBAR_MARGIN_PX
            painter.drawRoundedRect(QRectF(x, thumb_y + 2, SCROLLBAR_WIDTH_PX, thumb_h - 4), radius, radius)

        max_x = content_w - view_w
        if max_x > 0:
            thumb_w = max(SCROLLBAR_MIN_THUMB_PX, int(view_w * view_w / content_w))
            thumb_x = int((view_w - thumb_w) * (self._scroll_x / max_x))
            y = view_h - SCROLLBAR_WIDTH_PX - SCROLLBAR_MARGIN_PX
            painter.drawRoundedRect(QRectF(thumb_x + 2, y, thumb_w - 4, SCROLLBAR_WIDTH_PX), radius, radius)

    def _paint_content(self, painter: QPainter) -> None:
        """Paint the date, events, checklists and note over the artwork."""
        self._paint_date(painter)
        self._paint_events(painter)
        for row in self._interactive_rows():
            if row.box_rect is not None:
                self._paint_checklist_row(painter, row)
        self._paint_note(painter)

    def _paint_date(self, painter: QPainter) -> None:
        """Draw today's date centred inside the empty Date box."""
        font = _panel_font(int(self._content_height() * DATE_FONT_FRAC), bold=True)
        painter.setFont(font)
        painter.setPen(DATE_COLOR)
        painter.drawText(self._box_rect(DATE_BOX_FRAC), int(Qt.AlignmentFlag.AlignCenter), self._date_text)

    def _box_rect(self, box_frac: tuple[float, float, float, float]) -> QRect:
        """Convert a (x, y, w, h) fractional box to a pixel QRect in content space.

        Heights use the full planner height (content space), not the window
        height, so the boxes — and the text in them — keep a constant size as the
        window is resized; the scroll offset is applied by the painter transform.
        """
        x_frac, y_frac, w_frac, h_frac = box_frac
        content_w, content_h = self._content_size()
        return QRect(
            int(content_w * x_frac), int(content_h * y_frac),
            int(content_w * w_frac), int(content_h * h_frac),
        )

    def _paint_events(self, painter: QPainter) -> None:
        """Draw event rows inside the events box, or a friendly message."""
        font = _panel_font(int(self._content_height() * EVENT_FONT_FRAC), bold=True)
        if self._events_state != "ok":
            painter.setFont(font)
            painter.setPen(TEXT_COLOR)
            box_x, box_y, box_w, box_h = EVENTS_BOX_FRAC
            content_w, content_h = self._content_size()
            pad_x = int(content_w * BOX_PAD_X_FRAC)
            pad_y = int(content_h * BOX_PAD_Y_FRAC)
            message_rect = QRect(
                int(content_w * box_x) + pad_x, int(content_h * box_y) + pad_y,
                int(content_w * box_w) - 2 * pad_x, int(content_h * box_h) - 2 * pad_y,
            )
            painter.drawText(
                message_rect,
                int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self._events_message,
            )
            return

        done_font = _panel_font(int(self._content_height() * EVENT_FONT_FRAC), bold=True, strike=True)
        for row in self._interactive_rows():
            if row.time_label is None:
                continue
            event = row.item
            active_font = done_font if event.done else font
            color = DONE_COLOR if event.done else TIME_COLOR
            painter.setFont(active_font)

            # Time first (in its own colour), then the title after it.
            metrics = QFontMetrics(active_font)
            time_text = f"{row.time_label}  "
            painter.setPen(color)
            painter.drawText(row.label_rect, _LINE_FLAGS, time_text)

            title_left = row.label_rect.left() + metrics.horizontalAdvance(time_text)
            title_rect = QRect(
                title_left, row.label_rect.top(),
                row.label_rect.right() - title_left, row.label_rect.height(),
            )
            title = metrics.elidedText(event.title, Qt.TextElideMode.ElideRight, title_rect.width())
            painter.setPen(DONE_COLOR if event.done else TEXT_COLOR)
            painter.drawText(title_rect, _LINE_FLAGS, title)

    def _paint_checklist_row(self, painter: QPainter, row: _InteractiveRow) -> None:
        """Draw a checkbox + label for one item (struck through, ticked when done)."""
        item = row.item
        if row.box_rect is not None:
            painter.setPen(QPen(CHECK_BOX_BORDER_COLOR, CHECK_BOX_BORDER_PX))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            radius = row.box_rect.width() * 0.25
            painter.drawRoundedRect(QRectF(row.box_rect), radius, radius)

        font = _panel_font(int(self._content_height() * CHECK_FONT_FRAC), bold=True, strike=item.done)
        painter.setFont(font)
        painter.setPen(DONE_COLOR if item.done else TEXT_COLOR)
        metrics = QFontMetrics(font)
        label = metrics.elidedText(item.label, Qt.TextElideMode.ElideRight, row.label_rect.width())
        painter.drawText(row.label_rect, _LINE_FLAGS, label)

        if item.done and row.box_rect is not None:
            self._paint_tick(painter, row.box_rect)

    def _paint_tick(self, painter: QPainter, box_rect: QRect) -> None:
        """Draw a small check mark inside a drawn checkbox square."""
        pen = QPen(CHECK_COLOR, max(2, box_rect.width() // 6))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        left_x = box_rect.left() + box_rect.width() * 0.20
        mid_x = box_rect.left() + box_rect.width() * 0.42
        right_x = box_rect.left() + box_rect.width() * 0.84
        high_y = box_rect.top() + box_rect.height() * 0.22
        mid_y = box_rect.top() + box_rect.height() * 0.70
        low_y = box_rect.top() + box_rect.height() * 0.50
        tick = QPolygonF([
            QPointF(left_x, low_y),
            QPointF(mid_x, mid_y),
            QPointF(right_x, high_y),
        ])
        painter.drawPolyline(tick)

    def _paint_note(self, painter: QPainter) -> None:
        """Draw the short, word-wrapped note inside the note box, with padding."""
        content_w, content_h = self._content_size()
        pad_x = int(content_w * BOX_PAD_X_FRAC)
        pad_y = int(content_h * BOX_PAD_Y_FRAC)
        note_rect = self._box_rect(NOTE_BOX_FRAC).adjusted(pad_x, pad_y, -pad_x, -pad_y)
        painter.setFont(_panel_font(int(content_h * NOTE_FONT_FRAC), bold=True))
        painter.setPen(NOTE_COLOR)
        painter.drawText(
            note_rect,
            int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._note_text,
        )
