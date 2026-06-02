"""The compact weekly-plan panel that floats on the desktop.

A small, professional pink card — much smaller and tidier than the daily
post-it — that shows the week's content at a glance: each day, its format, and
its topic. It carries a link that opens the full, detailed plan in Notion.

The card is draggable (grab the header), minimizes/maximizes by clicking its
header (or pressing a key), and remembers where it was last dragged. All of that
shared card behaviour lives in `CardPanel`; this file adds only the week's rows,
the Notion link, and their styling. Unlike the Draft Replies card it is a fixed
width whose height follows its content, and it is not resizable.

Styling matches the rest of the buddy — cream/pink palette and the bundled
Fredoka font — with a soft drop shadow and a little heart in the header. It is
built with Qt widgets and a stylesheet rather than hand-painted, so the layout
stays small and easy to read.
"""

# === IMPORTS ===

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from card_panel import PINK_SOFT, TEXT, TEXT_SOFT, CardPanel
from collections.abc import Callable


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent

# Remembered drag position (only an on-screen coordinate — no personal data).
# Kept out of the repo; see .gitignore.
PANEL_STATE_PATH = PROJECT_DIR / "plan_panel_state.json"

# Compact, fixed card width for a neat rectangle; height follows its content.
CARD_WIDTH_PX = 320

# Accent colour for the "open in Notion" link (specific to this card).
LINK = "#d6668a"


# === PLAN PANEL ===

class PlanPanel(CardPanel):
    """A small, draggable, minimizable card showing the week at a glance.

    The owner supplies two callbacks: `on_geometry_change` (handled by the base)
    keeps the overlay's click-through mask in sync as the card moves or
    collapses, and `on_open_notion` is invoked when the "open in Notion" link is
    clicked.
    """

    def __init__(
        self,
        parent: QWidget,
        on_geometry_change: Callable[[], None],
        on_open_notion: Callable[[], None],
    ) -> None:
        # Stored before the base builds the UI, since the body wires the link to it.
        self._on_open_notion = on_open_notion
        super().__init__(
            parent,
            on_geometry_change,
            state_path=PANEL_STATE_PATH,
            title="Weekly Plan 🤍",
            resizable=False,
        )

    # --- construction (card-specific body + styling) ---

    def _configure_card(self, card: QWidget) -> None:
        """A fixed, compact width for a neat rectangle; the height follows content."""
        card.setFixedWidth(CARD_WIDTH_PX)

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

    def _content_stylesheet(self) -> str:
        """Styling for the day chips, topic text, the Notion link and empty state."""
        return f"""
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
        self._status_label.setText(week_of)
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

    # --- interaction ---

    def _handle_link_click(self, _event: QMouseEvent) -> None:
        """Open the full plan in Notion (delegated to the owner)."""
        self._on_open_notion()

    # --- layout helpers ---

    def _clear_rows(self) -> None:
        """Remove any previously laid-out rows before filling in a fresh plan."""
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
