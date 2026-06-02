"""The draft-replies panel that floats on the desktop.

A small, professional pink card — the same family as the weekly-plan panel —
that lists the buddy's drafted email replies. Each draft shows who it's to, the
subject, the drafted text (selectable, so it can be copied), and an "Open in
Gmail" button that opens a prefilled Gmail compose window in the browser. Camille
reviews each one and sends it herself; the buddy never sends.

Like the other cards it is draggable (grab the header), minimizes/maximizes by
clicking its header, remembers where it was last dragged, and matches the
buddy's cream/pink palette and bundled Fredoka font. It is also a resizable
WINDOW: grab any edge or corner (in the soft-shadow border) to make it wider or
taller so more of a draft shows at once. When the drafts are taller than the
window the list scrolls, with the same slim scrollbar as before. Its dragged
position AND chosen size are remembered between launches (the same approach as
the "Camille's Day" card), in a gitignored local state file.
"""

# === IMPORTS ===

import json
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from callout_panel import FONT_PATH, PANEL_FONT_FALLBACK_FAMILIES


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent

# Remembered drag position AND window size (only on-screen numbers — no personal
# data). Kept out of the repo; see .gitignore.
PANEL_STATE_PATH = PROJECT_DIR / "draft_panel_state.json"

# Breathing room around the card so the drop shadow isn't clipped by the widget
# bounds (the overlay's click-through mask uses the whole widget rect). This soft
# halo is also the only child-free zone, so it doubles as the resize grab border.
SHADOW_MARGIN_PX = 16

# Default opening size of the whole panel (card + halo). Tuned to match the old
# fixed look: a ~360px-wide card with a comfortable run of draft showing.
DEFAULT_WIDTH_PX = 392
DEFAULT_HEIGHT_PX = 540

# Resize limits, so the window stays usable. Height's upper bound is the overlay
# itself (handled by clamping to the parent), so only a floor is set here.
MIN_WIDTH_PX = 300
MAX_WIDTH_PX = 760
MIN_HEIGHT_PX = 240

# Fit-to-content opening height: with no saved size yet, the panel opens just
# tall enough for its drafts (no empty grey below them). It's capped so a big
# batch can't fill the screen — past the cap the scrollbar takes over.
MAX_FIT_HEIGHT_PX = 900  # absolute ceiling on the auto-fitted height
FIT_HEIGHT_SCREEN_FRACTION = 0.9  # also never exceed this share of the overlay
FIT_HEIGHT_SLACK_PX = 2  # tiny cushion so rounding can't trigger a stray scrollbar

# Inner layout metrics, kept as named constants because the fit-to-content
# measurement re-creates the layout's math and must stay in step with the
# build methods that use these same values.
BODY_MARGIN_PX = 12  # padding around the scroll area inside the card body
LIST_SPACING_PX = 12  # gap between stacked draft cards
DRAFT_CARD_MARGINS = (12, 11, 12, 12)  # left, top, right, bottom inside a draft card
DRAFT_CARD_SPACING_PX = 7  # gap between the lines within one draft card

# Default parked spot: top-right of the overlay, inset by this margin.
PARK_MARGIN_PX = 36

# A drag must move at least this far before a header press counts as a drag
# rather than a click that minimizes/maximizes the card.
DRAG_THRESHOLD_PX = 4

# How close to an edge/corner a press must land to start a resize. Set equal to
# the shadow halo so the whole soft border (right up to the visible card edge) is
# grabbable — and so the grab lands on the panel itself, not a child widget.
RESIZE_MARGIN_PX = 16

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
    """A small, draggable, minimizable, RESIZABLE card listing drafted replies.

    The owner supplies two callbacks: `on_geometry_change` keeps the overlay's
    click-through mask in sync as the card moves, collapses, or resizes, and
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

        # Resizing: grab any edge/corner (in the shadow halo) to change the size.
        # _expanded_size is the size to restore to when un-minimizing. Saved
        # position and size (loaded below) are remembered across launches.
        self._resizing = False
        self._resize_moved = False
        self._resize_edges: tuple[bool, bool, bool, bool] = (False, False, False, False)
        self._resize_start_rect = QRect()
        self._resize_start_mouse = QPoint()
        self._expanded_size = QSize(DEFAULT_WIDTH_PX, DEFAULT_HEIGHT_PX)
        self._saved_top_left, self._saved_size = self._load_saved_state()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFont(QFont(_font_family()))
        # Track the cursor with no button held, so the halo shows a resize arrow.
        self.setMouseTracking(True)

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
        # No longer a FIXED width — the card fills the (resizable) window, down to
        # a sensible minimum, so dragging an edge makes the whole card grow/shrink.
        self._card.setMinimumWidth(MIN_WIDTH_PX - 2 * SHADOW_MARGIN_PX)
        self._card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._card.setStyleSheet(self._stylesheet())
        self._card.setGraphicsEffect(self._shadow())
        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        card_layout.addWidget(self._build_header())
        card_layout.addWidget(self._build_body(), 1)  # body takes the extra height

    def _build_header(self) -> QFrame:
        """The pink title bar — the drag handle and minimize/maximize toggle."""
        self._header = QFrame(self._card)
        self._header.setObjectName("header")
        self._header.setCursor(Qt.CursorShape.OpenHandCursor)
        # Fixed height so all extra vertical space goes to the draft list, not here.
        self._header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

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
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self._body)
        layout.setContentsMargins(
            BODY_MARGIN_PX, BODY_MARGIN_PX, BODY_MARGIN_PX, BODY_MARGIN_PX
        )
        layout.setSpacing(0)

        self._scroll = QScrollArea(self._body)
        self._scroll.setObjectName("scroll")
        self._scroll.setWidgetResizable(True)
        # The scroll area now FILLS the (resizable) window instead of a fixed cap,
        # so a taller window shows more of the list; the scrollbar appears only
        # when the drafts are taller than the window.
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._list = QWidget(self._scroll)
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(LIST_SPACING_PX)
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
        """Size the card, place it, and show it.

        A size you dragged before (and that was saved) always wins, so manual
        sizing stays predictable. With no saved size yet, the height is fitted
        to the drafts so there's no empty space below them — capped to most of
        the screen, past which the scrollbar takes over.
        """
        size = self._clamped_size(
            self._saved_size if self._saved_size is not None
            else self._fit_to_content_size()
        )
        self.resize(size)
        self._expanded_size = size
        self.move(self._initial_top_left())
        self.show()
        self.raise_()
        self._on_geometry_change()

    # --- fit-to-content sizing ---

    def _fit_to_content_size(self) -> QSize:
        """The opening size that hugs the drafts: default width, fitted height.

        The drafts live inside a scroll area, which by design reports a fixed
        size that ignores its contents — so to fit the height we measure the
        draft list ourselves (see `_layout_natural_height`) and add the header
        and the body's padding. The result is capped by `_max_fit_height`; the
        caller's `_clamped_size` then enforces the usual min/overlay bounds.
        """
        # Apply the stylesheet (and thus the real fonts) before measuring text.
        self.ensurePolished()
        list_width = DEFAULT_WIDTH_PX - 2 * SHADOW_MARGIN_PX - 2 * BODY_MARGIN_PX
        content_height = self._layout_natural_height(self._list_layout, list_width)
        chrome_height = (
            2 * SHADOW_MARGIN_PX  # the soft halo, top and bottom
            + self._header.sizeHint().height()
            + 2 * BODY_MARGIN_PX  # the body padding above and below the list
        )
        natural_height = chrome_height + content_height + FIT_HEIGHT_SLACK_PX
        return QSize(DEFAULT_WIDTH_PX, min(natural_height, self._max_fit_height()))

    def _max_fit_height(self) -> int:
        """The ceiling for the auto-fitted height: an absolute cap, and never
        more than a fraction of the overlay so a big batch can't fill the screen."""
        cap = MAX_FIT_HEIGHT_PX
        parent = self.parentWidget()
        if parent is not None:
            cap = min(cap, int(parent.height() * FIT_HEIGHT_SCREEN_FRACTION))
        return cap

    def _layout_natural_height(self, layout: QVBoxLayout, width: int) -> int:
        """Height a box layout needs at `width`, honoring word-wrap.

        Recurses into draft sub-cards and the button rows, summing each child's
        wrapped height (`heightForWidth` for wrapped labels) plus the layout's
        margins and inter-item spacing. Spacing is counted for every gap between
        items — including the gap before the trailing stretch — so the figure
        matches exactly what Qt will lay out, with no empty strip at the bottom.
        """
        left, top, right, bottom = layout.getContentsMargins()
        inner_width = width - left - right
        spacing = layout.spacing()
        child_heights: list[int] = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            child = item.widget()
            sub_layout = item.layout()
            if child is not None:
                child.ensurePolished()
                nested = child.layout()
                if nested is not None and child.objectName() == "draftCard":
                    child_heights.append(self._layout_natural_height(nested, inner_width))
                elif child.hasHeightForWidth():
                    child_heights.append(child.heightForWidth(inner_width))
                else:
                    child_heights.append(child.sizeHint().height())
            elif sub_layout is not None:
                child_heights.append(self._layout_natural_height(sub_layout, inner_width))
            # else: a stretch/spacer — adds no height of its own (just spacing).
        if not child_heights:
            return top + bottom
        # One spacing sits between each adjacent pair of items, spacers included.
        gaps = max(0, layout.count() - 1)
        return top + bottom + sum(child_heights) + spacing * gaps

    def toggle_minimized(self) -> None:
        """Collapse to just the header, or expand back to the last full size."""
        self._minimized = not self._minimized
        self._chevron.setText(CHEVRON_CLOSED if self._minimized else CHEVRON_OPEN)
        if self._minimized:
            # Remember the expanded size, hide the body, shrink to the header
            # (keeping the current width) so the collapsed bar matches.
            self._expanded_size = self.size()
            self._body.setVisible(False)
            self._restyle()
            self.adjustSize()
            self.resize(self._expanded_size.width(), self.height())
        else:
            self._body.setVisible(True)
            self._restyle()
            self.resize(self._expanded_size)
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
        layout.setContentsMargins(*DRAFT_CARD_MARGINS)
        layout.setSpacing(DRAFT_CARD_SPACING_PX)

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
        """Start a resize (edge/corner), or a possible drag (header press)."""
        self.raise_()
        self._on_geometry_change()
        if event.button() == Qt.MouseButton.LeftButton:
            # An edge/corner grab in the halo starts a resize (only when expanded);
            # it takes precedence over the header drag below.
            edges = self._edges_at(event.position().toPoint())
            if not self._minimized and any(edges):
                self._resizing = True
                self._resize_moved = False
                self._resize_edges = edges
                self._resize_start_rect = self.geometry()
                self._resize_start_mouse = self.mapToParent(event.position().toPoint())
                return
            if self._on_header(event):
                self._dragging = False
                self._press_pos = event.position().toPoint()
                self._drag_offset = event.position().toPoint()
                self._header.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Resize or drag the card, or show the right cursor when just hovering."""
        point = event.position().toPoint()
        if self._resizing:
            self._perform_resize(self.mapToParent(point))
            return
        if hasattr(self, "_press_pos"):
            if not self._dragging and (point - self._press_pos).manhattanLength() >= DRAG_THRESHOLD_PX:
                self._dragging = True
            if self._dragging:
                target = self.mapToParent(point - self._drag_offset)
                self.move(target)
                self._clamp_into_parent()
                self._on_geometry_change()
            return
        # Idle hover: a resize arrow over the halo edges, the normal cursor else.
        if not self._minimized:
            self.setCursor(self._cursor_for_edges(self._edges_at(point)))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish a resize or drag and remember the new geometry for next time."""
        if self._resizing:
            self._resizing = False
            if self._resize_moved:
                self._saved_size = self.size()
                self._expanded_size = self.size()
                self._saved_top_left = self.pos()
                self._save_state()
            return
        if hasattr(self, "_press_pos"):
            self._header.setCursor(Qt.CursorShape.OpenHandCursor)
            if self._dragging:
                self._saved_top_left = self.pos()
                self._save_state()
            else:
                self.toggle_minimized()
            del self._press_pos
            self._dragging = False
            return
        super().mouseReleaseEvent(event)

    def _on_header(self, event: QMouseEvent) -> bool:
        """True when a press landed on the header bar (the drag/toggle handle)."""
        return self._header.geometry().contains(
            self._header.parentWidget().mapFromParent(event.position().toPoint())
        )

    # --- resizing ---

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
        """Resize the window as an edge or corner is dragged, clamped and on-screen.

        The dragged edge follows the cursor while the opposite edge stays
        anchored; the size is clamped to the min/max range and the whole card is
        kept inside the overlay. The inner layout reflows so the draft list and
        its scrollbar fill the new size.
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

        size = self._clamped_size(QSize(new_w, new_h))
        new_x = (start.right() + 1 - size.width()) if left else start.x()
        new_y = (start.bottom() + 1 - size.height()) if top else start.y()
        self.setGeometry(self._clamp_rect_to_parent(QRect(QPoint(new_x, new_y), size)))
        self._on_geometry_change()

    def _clamped_size(self, size: QSize) -> QSize:
        """Clamp a window size to the min/max width and the min/overlay height."""
        width = max(MIN_WIDTH_PX, min(size.width(), MAX_WIDTH_PX))
        max_height = size.height()
        parent = self.parentWidget()
        if parent is not None:
            max_height = parent.height()
        height = max(MIN_HEIGHT_PX, min(size.height(), max_height))
        return QSize(width, height)

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

    def _clamp_rect_to_parent(self, rect: QRect) -> QRect:
        """Nudge a rect so the whole panel stays within the overlay bounds."""
        parent = self.parentWidget()
        if parent is None:
            return rect
        max_x = max(0, parent.width() - rect.width())
        max_y = max(0, parent.height() - rect.height())
        x = min(max(0, rect.x()), max_x)
        y = min(max(0, rect.y()), max_y)
        return QRect(x, y, rect.width(), rect.height())

    # --- remembered position and size ---

    def _load_saved_state(self) -> tuple[QPoint | None, QSize | None]:
        """Read the remembered top-left and window size, or None for each if absent.

        Best-effort and tolerant: a missing/unreadable file — or an older one that
        saved only the position — just means 'use the default' for whatever's
        absent, so a fresh checkout never errors. Only on-screen geometry is
        stored, never any email content.
        """
        try:
            data = json.loads(PANEL_STATE_PATH.read_text(encoding="utf-8"))
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
        """Persist the current position and size (best-effort; only on-screen numbers)."""
        rect = self.geometry()
        try:
            PANEL_STATE_PATH.write_text(
                json.dumps({"x": rect.x(), "y": rect.y(), "w": rect.width(), "h": rect.height()}),
                encoding="utf-8",
            )
        except OSError:
            pass
