"""The compact weekly-plan panel that floats on the desktop.

A small, professional pink card — much smaller and tidier than the daily
post-it — that shows the week's content at a glance: each day, its format, and
its topic. It carries a link that opens the full, detailed plan in Notion.

The card is draggable (grab the header), minimizes/maximizes by clicking its
header (or pressing a key), and stays put in the background while the buddy goes
about her day. Like the post-it, it remembers where it was last dragged.

Styling matches the rest of the buddy — cream/pink palette and the bundled
Fredoka font — with a soft drop shadow for a gentle 3-D lift and a little heart
in the header for character. It is built with Qt widgets and a stylesheet rather
than hand-painted, so the layout stays small and easy to read.
"""

# === IMPORTS ===

import json
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from callout_panel import FONT_PATH, PANEL_FONT_FALLBACK_FAMILIES


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent

# Remembered drag position (only an on-screen coordinate — no personal data).
# Kept out of the repo; see .gitignore.
PANEL_STATE_PATH = PROJECT_DIR / "plan_panel_state.json"

# Compact, fixed card width for a neat rectangle; height follows its content.
CARD_WIDTH_PX = 320

# Breathing room around the card so the drop shadow isn't clipped by the widget
# bounds (the overlay's click-through mask uses the whole widget rect).
SHADOW_MARGIN_PX = 16

# Default parked spot: top-right of the overlay, inset by this margin.
PARK_MARGIN_PX = 36

# A drag must move at least this far before a header press counts as a drag
# rather than a click that minimizes/maximizes the card.
DRAG_THRESHOLD_PX = 4

# Palette — the shared cream/pink tokens, matching styles.css and the post-it.
CREAM = "#fdf6ec"
PINK_FRAME = "#f4a9be"
PINK_HEADER = "#f7aec0"
PINK_SOFT = "#ffd7e3"
TEXT = "#6e4b4b"
TEXT_SOFT = "#a98a8a"
LINK = "#d6668a"

# Header text when expanded vs. minimized (the chevron hints which way it goes).
CHEVRON_OPEN = "⌄"
CHEVRON_CLOSED = "›"

# Family the bundled font registers as, resolved once on first construction.
_loaded_font_family: str | None = None


def _font_family() -> str:
    """Register the bundled Fredoka font once and return its family name.

    Falls back to a system rounded font if the bundled file is ever missing, so
    the panel always renders with something friendly.
    """
    global _loaded_font_family
    if _loaded_font_family is None:
        font_id = QFontDatabase.addApplicationFont(str(FONT_PATH))
        families = QFontDatabase.applicationFontFamilies(font_id)
        _loaded_font_family = families[0] if families else ""
    return _loaded_font_family or PANEL_FONT_FALLBACK_FAMILIES[0]


# === PLAN PANEL ===

class PlanPanel(QWidget):
    """A small, draggable, minimizable card showing the week at a glance.

    The owner supplies two callbacks: `on_geometry_change` keeps the overlay's
    click-through mask in sync as the card moves or collapses, and
    `on_open_notion` is invoked when the "open in Notion" link is clicked.
    """

    def __init__(
        self,
        parent: QWidget,
        on_geometry_change: Callable[[], None],
        on_open_notion: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._on_geometry_change = on_geometry_change
        self._on_open_notion = on_open_notion

        self._minimized = False
        self._dragging = False
        self._drag_offset = QPoint()
        self._saved_top_left: QPoint | None = self._load_saved_position()

        # Transparent host so the card's rounded corners and shadow read cleanly
        # against whatever is on the desktop behind the overlay.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFont(QFont(_font_family()))

        self._build_ui()
        self.hide()

    # --- construction ---

    def _build_ui(self) -> None:
        """Assemble the card: a header bar, the week's rows, and the Notion link."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            SHADOW_MARGIN_PX, SHADOW_MARGIN_PX, SHADOW_MARGIN_PX, SHADOW_MARGIN_PX
        )

        self._card = QFrame(self)
        self._card.setObjectName("card")
        self._card.setFixedWidth(CARD_WIDTH_PX)
        self._card.setStyleSheet(self._stylesheet())
        self._card.setGraphicsEffect(self._shadow())
        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        card_layout.addWidget(self._build_header())
        card_layout.addWidget(self._build_body())

    def _build_header(self) -> QFrame:
        """The pink title bar — the drag handle and minimize/maximize toggle."""
        self._header = QFrame(self._card)
        self._header.setObjectName("header")
        self._header.setCursor(Qt.CursorShape.OpenHandCursor)

        row = QHBoxLayout(self._header)
        row.setContentsMargins(14, 9, 12, 9)
        title = QLabel("Weekly Plan 🤍", self._header)
        title.setObjectName("title")
        self._week_label = QLabel("", self._header)
        self._week_label.setObjectName("week")
        self._chevron = QLabel(CHEVRON_OPEN, self._header)
        self._chevron.setObjectName("chevron")

        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self._week_label)
        row.addWidget(self._chevron)
        return self._header

    def _build_body(self) -> QWidget:
        """The collapsible part: the week's rows and the 'open in Notion' link."""
        self._body = QWidget(self._card)
        layout = QVBoxLayout(self._body)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self._rows = QGridLayout()
        self._rows.setHorizontalSpacing(10)
        self._rows.setVerticalSpacing(9)
        self._rows.setColumnStretch(1, 1)
        layout.addLayout(self._rows)

        self._notion_link = QLabel("🔗 Open full plan in Notion ↗", self._body)
        self._notion_link.setObjectName("notionLink")
        self._notion_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._notion_link.mousePressEvent = self._handle_link_click
        layout.addWidget(self._notion_link)
        return self._body

    def _shadow(self) -> QGraphicsDropShadowEffect:
        """A soft pink drop shadow for a gentle 3-D lift."""
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(214, 142, 162, 130))
        return shadow

    def _stylesheet(self) -> str:
        """The card's cozy pastel styling (header radius depends on minimized state)."""
        header_radius = "13px" if self._minimized else "13px 13px 0 0"
        return f"""
            #card {{ background: {CREAM}; border: 1px solid {PINK_FRAME};
                     border-radius: 14px; }}
            #header {{ background: {PINK_HEADER}; border-radius: {header_radius}; }}
            #title {{ color: #ffffff; font-size: 13px; font-weight: 600; }}
            #week {{ color: #fff3f7; font-size: 10px; }}
            #chevron {{ color: #ffffff; font-size: 13px; font-weight: 600; }}
            QLabel[class="day"] {{ background: {PINK_SOFT}; color: {TEXT};
                    border-radius: 8px; font-size: 11px; font-weight: 600;
                    padding: 2px 9px; }}
            QLabel[class="topic"] {{ color: {TEXT}; font-size: 12px; }}
            #notionLink {{ color: {LINK}; font-size: 11px; font-weight: 600; }}
            #empty {{ color: {TEXT_SOFT}; font-size: 12px; }}
        """

    # --- public API ---

    def set_overview(self, week_of: str, rows: list[tuple[str, str, str]]) -> None:
        """Fill the card with the week label and one line per piece (day, format, topic)."""
        self._week_label.setText(week_of)
        self._clear_rows()
        if not rows:
            empty = QLabel("No plan yet. 🤍", self._body)
            empty.setObjectName("empty")
            self._rows.addWidget(empty, 0, 0, 1, 2)
            return
        for index, (day, fmt, topic) in enumerate(rows):
            day_label = QLabel(day, self._body)
            day_label.setProperty("class", "day")
            day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            text = QLabel(f"{fmt} — {topic}" if fmt else topic, self._body)
            text.setProperty("class", "topic")
            text.setWordWrap(True)

            self._rows.addWidget(day_label, index, 0, Qt.AlignmentFlag.AlignTop)
            self._rows.addWidget(text, index, 1)
        self._restyle()

    def show_panel(self) -> None:
        """Place the card at its remembered (or default) spot and show it."""
        self.adjustSize()
        self.move(self._initial_top_left())
        self.show()
        self.raise_()
        self._on_geometry_change()

    def toggle_minimized(self) -> None:
        """Collapse to just the header, or expand back to the full card."""
        self._minimized = not self._minimized
        self._body.setVisible(not self._minimized)
        self._chevron.setText(CHEVRON_CLOSED if self._minimized else CHEVRON_OPEN)
        self._restyle()
        self.adjustSize()
        self._clamp_into_parent()
        self._on_geometry_change()

    @property
    def is_open(self) -> bool:
        """True while the card is on screen (expanded or minimized)."""
        return self.isVisible()

    # --- interaction ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start a possible drag when the header is pressed."""
        if event.button() == Qt.MouseButton.LeftButton and self._on_header(event):
            self._dragging = False
            self._press_pos = event.position().toPoint()
            self._drag_offset = event.position().toPoint()
            self._header.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Move the card once the press has travelled past the drag threshold."""
        if not hasattr(self, "_press_pos"):
            return
        point = event.position().toPoint()
        if not self._dragging and (point - self._press_pos).manhattanLength() >= DRAG_THRESHOLD_PX:
            self._dragging = True
        if self._dragging:
            target = self.mapToParent(point - self._drag_offset)
            self.move(target)
            self._clamp_into_parent()
            self._on_geometry_change()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """A drag saves the new spot; a plain header click minimizes/maximizes."""
        if not hasattr(self, "_press_pos"):
            super().mouseReleaseEvent(event)
            return
        self._header.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._dragging:
            self._saved_top_left = self.pos()
            self._save_position()
        else:
            self.toggle_minimized()
        del self._press_pos
        self._dragging = False

    def _handle_link_click(self, _event: QMouseEvent) -> None:
        """Open the full plan in Notion (delegated to the owner)."""
        self._on_open_notion()

    def _on_header(self, event: QMouseEvent) -> bool:
        """True when a press landed on the header bar (the drag/toggle handle)."""
        return self._header.geometry().contains(
            self._header.parentWidget().mapFromParent(event.position().toPoint())
        )

    # --- layout helpers ---

    def _clear_rows(self) -> None:
        """Remove any previously laid-out rows before filling in a fresh plan."""
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _restyle(self) -> None:
        """Re-apply the stylesheet so class-based and state-based rules refresh."""
        self._card.setStyleSheet(self._stylesheet())

    def _initial_top_left(self) -> QPoint:
        """The remembered spot if any, else the default top-right park, clamped."""
        if self._saved_top_left is not None:
            return self._clamped(self._saved_top_left)
        parent = self.parentWidget()
        if parent is None:
            return QPoint(PARK_MARGIN_PX, PARK_MARGIN_PX)
        x = parent.width() - self.width() - PARK_MARGIN_PX
        return self._clamped(QPoint(x, PARK_MARGIN_PX))

    def _clamp_into_parent(self) -> None:
        """Keep the whole card inside the overlay after a move or a resize."""
        self.move(self._clamped(self.pos()))

    def _clamped(self, point: QPoint) -> QPoint:
        """Nudge a top-left so the panel stays fully within the overlay bounds."""
        parent = self.parentWidget()
        if parent is None:
            return point
        max_x = max(0, parent.width() - self.width())
        max_y = max(0, parent.height() - self.height())
        return QPoint(min(max(0, point.x()), max_x), min(max(0, point.y()), max_y))

    # --- remembered position ---

    def _load_saved_position(self) -> QPoint | None:
        """Read the remembered top-left, or None if there isn't a usable one."""
        try:
            data = json.loads(PANEL_STATE_PATH.read_text(encoding="utf-8"))
            return QPoint(int(data["x"]), int(data["y"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save_position(self) -> None:
        """Persist the current top-left (best-effort; only an on-screen coordinate)."""
        position = self.pos()
        try:
            PANEL_STATE_PATH.write_text(
                json.dumps({"x": position.x(), "y": position.y()}), encoding="utf-8"
            )
        except OSError:
            pass
