"""The draft-replies panel that floats on the desktop.

A small, professional pink card — the same family as the weekly-plan panel —
that lists the buddy's drafted email replies. Each draft shows who it's to, the
subject, the drafted text (selectable, so it can be copied), and an "Open in
Gmail" button that opens a prefilled Gmail compose window in the browser. Camille
reviews each one and sends it herself; the buddy never sends.

Like the other cards it is draggable (grab the header), minimizes/maximizes by
clicking its header, remembers where it was last dragged, and matches the
buddy's cream/pink palette and bundled Fredoka font. When there are several
drafts the list scrolls rather than growing off-screen.
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
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from callout_panel import FONT_PATH, PANEL_FONT_FALLBACK_FAMILIES


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent

# Remembered drag position (only an on-screen coordinate — no personal data).
# Kept out of the repo; see .gitignore.
PANEL_STATE_PATH = PROJECT_DIR / "draft_panel_state.json"

# A touch wider than the plan card so a few sentences of draft read comfortably.
CARD_WIDTH_PX = 360

# Past this height the draft list scrolls instead of pushing the card off-screen.
MAX_LIST_HEIGHT_PX = 440

# Breathing room around the card so the drop shadow isn't clipped by the widget
# bounds (the overlay's click-through mask uses the whole widget rect).
SHADOW_MARGIN_PX = 16

# Default parked spot: top-right of the overlay, inset by this margin.
PARK_MARGIN_PX = 36

# A drag must move at least this far before a header press counts as a drag
# rather than a click that minimizes/maximizes the card.
DRAG_THRESHOLD_PX = 4

# Palette — the shared cream/pink tokens, matching styles.css and the other cards.
CREAM = "#fdf6ec"
PINK_FRAME = "#f4a9be"
PINK_HEADER = "#f7aec0"
PINK_SOFT = "#ffd7e3"
TEXT = "#6e4b4b"
TEXT_SOFT = "#a98a8a"
BUTTON_PINK = "#f4a9be"
BUTTON_PINK_HOVER = "#ef93ad"

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


# === DRAFT PANEL ===

class DraftPanel(QWidget):
    """A small, draggable, minimizable card listing drafted email replies.

    The owner supplies two callbacks: `on_geometry_change` keeps the overlay's
    click-through mask in sync as the card moves or collapses, and
    `on_open_draft` is invoked with a Gmail compose URL when a draft's "Open in
    Gmail" button is clicked.
    """

    def __init__(
        self,
        parent: QWidget,
        on_geometry_change: Callable[[], None],
        on_open_draft: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._on_geometry_change = on_geometry_change
        self._on_open_draft = on_open_draft

        self._minimized = False
        self._dragging = False
        self._drag_offset = QPoint()
        self._saved_top_left: QPoint | None = self._load_saved_position()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFont(QFont(_font_family()))

        self._build_ui()
        self.hide()

    # --- construction ---

    def _build_ui(self) -> None:
        """Assemble the card: a header bar and a scrollable list of draft cards."""
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
        title = QLabel("Draft Replies 🤍", self._header)
        title.setObjectName("title")
        self._count_label = QLabel("", self._header)
        self._count_label.setObjectName("count")
        self._chevron = QLabel(CHEVRON_OPEN, self._header)
        self._chevron.setObjectName("chevron")

        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self._count_label)
        row.addWidget(self._chevron)
        return self._header

    def _build_body(self) -> QWidget:
        """The collapsible part: a scroll area holding one card per draft."""
        self._body = QWidget(self._card)
        layout = QVBoxLayout(self._body)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        self._scroll = QScrollArea(self._body)
        self._scroll.setObjectName("scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setMaximumHeight(MAX_LIST_HEIGHT_PX)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._list = QWidget(self._scroll)
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(12)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list)

        layout.addWidget(self._scroll)
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
            #count {{ color: #fff3f7; font-size: 10px; }}
            #chevron {{ color: #ffffff; font-size: 13px; font-weight: 600; }}
            #scroll {{ background: transparent; }}
            #draftCard {{ background: #fffaf3; border: 1px solid {PINK_SOFT};
                          border-radius: 11px; }}
            QLabel[class="to"] {{ color: {TEXT}; font-size: 12px; font-weight: 600; }}
            QLabel[class="subject"] {{ color: {TEXT_SOFT}; font-size: 11px; }}
            QLabel[class="draft"] {{ color: {TEXT}; font-size: 12px; }}
            QLabel[class="empty"] {{ color: {TEXT_SOFT}; font-size: 12px; }}
            QPushButton#openGmail {{ background: {BUTTON_PINK}; color: #ffffff;
                    border: none; border-radius: 9px; font-size: 11px;
                    font-weight: 600; padding: 6px 12px; }}
            QPushButton#openGmail:hover {{ background: {BUTTON_PINK_HOVER}; }}
        """

    # --- public API ---

    def set_drafts(self, drafts: list[tuple[str, str, str, str]]) -> None:
        """Fill the list with one card per draft: (sender, subject, body, gmail_url)."""
        self._clear_list()
        count = len(drafts)
        self._count_label.setText(
            "" if not count else f"{count} ready" if count != 1 else "1 ready"
        )
        if not drafts:
            empty = QLabel("No replies to draft right now. 🤍", self._list)
            empty.setProperty("class", "empty")
            self._list_layout.insertWidget(0, empty)
            self._restyle()
            return
        for index, (sender, subject, body, gmail_url) in enumerate(drafts):
            self._list_layout.insertWidget(index, self._build_draft_card(sender, subject, body, gmail_url))
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

    # --- draft card construction ---

    def _build_draft_card(self, sender: str, subject: str, body: str, gmail_url: str) -> QFrame:
        """One inner card: who it's to, the subject, the draft text, and the button."""
        card = QFrame(self._list)
        card.setObjectName("draftCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(7)

        to_label = QLabel(f"To {sender}", card)
        to_label.setProperty("class", "to")
        to_label.setWordWrap(True)
        layout.addWidget(to_label)

        subject_label = QLabel(f"Re: {subject}", card)
        subject_label.setProperty("class", "subject")
        subject_label.setWordWrap(True)
        layout.addWidget(subject_label)

        draft_label = QLabel(body, card)
        draft_label.setProperty("class", "draft")
        draft_label.setWordWrap(True)
        # Selectable so the draft can be copied by hand as a fallback.
        draft_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(draft_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        open_button = QPushButton("Open in Gmail ↗", card)
        open_button.setObjectName("openGmail")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Bind this card's URL so each button opens its own draft.
        open_button.clicked.connect(lambda _checked=False, url=gmail_url: self._on_open_draft(url))
        button_row.addWidget(open_button)
        layout.addLayout(button_row)
        return card

    # --- interaction ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start a possible drag when the header is pressed."""
        self.raise_()
        self._on_geometry_change()
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

    def _on_header(self, event: QMouseEvent) -> bool:
        """True when a press landed on the header bar (the drag/toggle handle)."""
        return self._header.geometry().contains(
            self._header.parentWidget().mapFromParent(event.position().toPoint())
        )

    # --- layout helpers ---

    def _clear_list(self) -> None:
        """Remove any previously laid-out draft cards before filling a fresh batch."""
        # Leave the trailing stretch in place; remove every widget item before it.
        for index in reversed(range(self._list_layout.count())):
            item = self._list_layout.itemAt(index)
            widget = item.widget()
            if widget is not None:
                self._list_layout.takeAt(index)
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
