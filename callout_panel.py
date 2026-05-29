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

Privacy: calendar data is held only in memory for painting and is never written
to disk or logged, per the project's security rules.

Font: "Fredoka" by Hanken Design Co., licensed under the SIL Open Font
License 1.1 and bundled in assets/fonts/ (see assets/fonts/OFL.txt). A
system-font fallback is used if the bundled file is ever missing.
"""

# === IMPORTS ===

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import QWidget

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

        self.events_loaded.connect(self._on_events_loaded)

        # Animates the QRect geometry for the grow/retract pop.
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

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
        """Return the parked geometry against the left edge, vertically centred."""
        height = int(overlay_height * PANEL_HEIGHT_FRAC)
        width = self._width_for_height(height)
        top_y = max(0, (overlay_height - height) // 2)
        return QRect(PANEL_LEFT_MARGIN_PX, top_y, width, height)

    def pop_out(self, seed_center: QPoint, final_rect: QRect) -> None:
        """Grow from a small seed at seed_center out to final_rect, with a pop."""
        self._is_open = True
        self._final_rect = final_rect
        self._rescale_background(final_rect.size().width(), final_rect.size().height())
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
            self._rescale_background(final_rect.width(), final_rect.height())
            self.setGeometry(final_rect)
            self._on_geometry_change()

    # --- sizing helpers ---

    def _width_for_height(self, height: int) -> int:
        """Width that preserves the background image's aspect ratio."""
        if self._background.isNull() or self._background.height() == 0:
            return height // 2
        return int(height * self._background.width() / self._background.height())

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

    # --- interaction ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Toggle the 'done' state of whichever row was clicked."""
        if not self._is_open:
            super().mousePressEvent(event)
            return
        point = event.position().toPoint()
        for row in self._interactive_rows():
            if row.hit_rect.contains(point):
                row.item.done = not row.item.done
                self.update()
                return
        super().mousePressEvent(event)

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

        width = self.width()
        height = self.height()
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
        """Draw the artwork background, then (once grown) today's content."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if not self._background_scaled.isNull():
            painter.drawPixmap(self.rect(), self._background_scaled)
        elif not self._background.isNull():
            painter.drawPixmap(self.rect(), self._background)

        grown_enough = (
            self.width() >= self._final_rect.width() * PANEL_CONTENT_REVEAL_FRACTION
            and self.height() >= self._final_rect.height() * PANEL_CONTENT_REVEAL_FRACTION
        )
        if grown_enough and not self._final_rect.isEmpty():
            self._paint_content(painter)

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
        font = _panel_font(int(self.height() * DATE_FONT_FRAC), bold=True)
        painter.setFont(font)
        painter.setPen(DATE_COLOR)
        painter.drawText(self._box_rect(DATE_BOX_FRAC), int(Qt.AlignmentFlag.AlignCenter), self._date_text)

    def _box_rect(self, box_frac: tuple[float, float, float, float]) -> QRect:
        """Convert a (x, y, w, h) fractional box to a pixel QRect at the current size."""
        x_frac, y_frac, w_frac, h_frac = box_frac
        return QRect(
            int(self.width() * x_frac), int(self.height() * y_frac),
            int(self.width() * w_frac), int(self.height() * h_frac),
        )

    def _paint_events(self, painter: QPainter) -> None:
        """Draw event rows inside the events box, or a friendly message."""
        font = _panel_font(int(self.height() * EVENT_FONT_FRAC), bold=True)
        if self._events_state != "ok":
            painter.setFont(font)
            painter.setPen(TEXT_COLOR)
            box_x, box_y, box_w, box_h = EVENTS_BOX_FRAC
            pad_x = int(self.width() * BOX_PAD_X_FRAC)
            pad_y = int(self.height() * BOX_PAD_Y_FRAC)
            message_rect = QRect(
                int(self.width() * box_x) + pad_x, int(self.height() * box_y) + pad_y,
                int(self.width() * box_w) - 2 * pad_x, int(self.height() * box_h) - 2 * pad_y,
            )
            painter.drawText(
                message_rect,
                int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self._events_message,
            )
            return

        done_font = _panel_font(int(self.height() * EVENT_FONT_FRAC), bold=True, strike=True)
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

        font = _panel_font(int(self.height() * CHECK_FONT_FRAC), bold=True, strike=item.done)
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
        pad_x = int(self.width() * BOX_PAD_X_FRAC)
        pad_y = int(self.height() * BOX_PAD_Y_FRAC)
        note_rect = self._box_rect(NOTE_BOX_FRAC).adjusted(pad_x, pad_y, -pad_x, -pad_y)
        painter.setFont(_panel_font(int(self.height() * NOTE_FONT_FRAC), bold=True))
        painter.setPen(NOTE_COLOR)
        painter.drawText(
            note_rect,
            int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._note_text,
        )
