"""Shared base for the small pink desktop cards (Weekly Plan, Draft Replies).

These two cards are near-identical twins: a cream/pink rounded `QFrame` with a
soft drop shadow, a draggable pink header bar with a chevron that toggles
minimize/expand, and a remembered on-screen position. Draft Replies additionally
resizes like a window. Before this base existed, all of that plumbing was
copy-pasted into both files; `CardPanel` now owns it once and each card supplies
only its own body content, title, header status text, and content styling.

What lives here (shared):
  * the card frame, drop shadow and rounded corners,
  * the header bar (title + status label + chevron) as the drag/minimize handle,
  * click-to-drag and click-to-minimize behaviour,
  * optional window-style edge/corner resizing (enabled per card),
  * remembering the card's position — and size, when resizable — in a small,
    gitignored local state file (only on-screen geometry, never personal data).

What each subclass supplies (unique):
  * `_build_body()` — the card's actual content widget,
  * `_content_stylesheet()` — styling for that content,
  * `_configure_card()` — fixed vs. flexible width,
  * sizing hooks (`_apply_initial_size`, `_default_size`, `_size_limits`) when it
    needs more than the default "size to content".

The pixel-art "Camille's Day" post-it (callout_panel.py) is deliberately NOT
built on this base: it has no header, no minimize and no card styling — it is
hand-painted artwork, a fundamentally different design.

Font: "Fredoka" by Hanken Design Co., SIL Open Font License 1.1, bundled in
assets/fonts/ (see assets/fonts/OFL.txt); a system fallback is used if missing.
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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# The bundled-font location and fallback list are owned by callout_panel; reuse
# them here so there is a single source of truth for the buddy's font.
from callout_panel import FONT_PATH, PANEL_FONT_FALLBACK_FAMILIES


# === CONSTANTS ===

# Breathing room around the card so the drop shadow isn't clipped by the widget
# bounds (the overlay's click-through mask uses the whole widget rect). For a
# resizable card this soft halo is also the only child-free zone, so it doubles
# as the resize grab border.
SHADOW_MARGIN_PX = 16

# Default parked spot: top-right of the overlay, inset by this margin.
PARK_MARGIN_PX = 36

# A drag must move at least this far before a header press counts as a drag
# rather than a click that minimizes/maximizes the card.
DRAG_THRESHOLD_PX = 4

# How close to an edge/corner a press must land to start a resize. Set equal to
# the shadow halo so the whole soft border (right up to the visible card edge) is
# grabbable — and so the grab lands on the panel itself, not a child widget.
RESIZE_MARGIN_PX = 16

# Palette — the shared cream/pink tokens, matching styles.css and the post-it.
# (Card-specific accents like the Notion link or Gmail button live in each card.)
CREAM = "#fdf6ec"
PINK_FRAME = "#f4a9be"
PINK_HEADER = "#f7aec0"
PINK_SOFT = "#ffd7e3"
TEXT = "#6e4b4b"
TEXT_SOFT = "#a98a8a"

# Header text when expanded vs. minimized (the chevron hints which way it goes).
CHEVRON_OPEN = "⌄"
CHEVRON_CLOSED = "›"

# Family the bundled font registers as, resolved once on first construction.
_loaded_font_family: str | None = None


def _font_family() -> str:
    """Register the bundled Fredoka font once and return its family name.

    Falls back to a system rounded font if the bundled file is ever missing, so
    the cards always render with something friendly.
    """
    global _loaded_font_family
    if _loaded_font_family is None:
        font_id = QFontDatabase.addApplicationFont(str(FONT_PATH))
        families = QFontDatabase.applicationFontFamilies(font_id)
        _loaded_font_family = families[0] if families else ""
    return _loaded_font_family or PANEL_FONT_FALLBACK_FAMILIES[0]


# === CARD PANEL BASE ===

class CardPanel(QWidget):
    """A small, draggable, minimizable cream/pink card with a header bar.

    Subclasses fill in their own body content and styling; this base provides
    the frame, header (drag + minimize), optional resizing, and position/size
    persistence. The owner supplies `on_geometry_change`, called whenever the
    card moves, collapses or resizes so the overlay can keep its click-through
    mask in sync.
    """

    def __init__(
        self,
        parent: QWidget,
        on_geometry_change: Callable[[], None],
        *,
        state_path: Path,
        title: str,
        resizable: bool,
    ) -> None:
        super().__init__(parent)
        self._on_geometry_change = on_geometry_change
        self._state_path = state_path
        self._title = title
        self._resizable = resizable

        self._minimized = False
        self._dragging = False
        self._drag_offset = QPoint()

        if resizable:
            # Resizing: grab any edge/corner (in the shadow halo) to change the
            # size. _expanded_size is the size to restore to when un-minimizing.
            self._resizing = False
            self._resize_moved = False
            self._resize_edges: tuple[bool, bool, bool, bool] = (False, False, False, False)
            self._resize_start_rect = QRect()
            self._resize_start_mouse = QPoint()

        # Saved position (and size, when resizable) is remembered across launches.
        self._saved_top_left, self._saved_size = self._load_saved_state()
        if resizable:
            self._expanded_size = (
                self._saved_size if self._saved_size is not None else self._default_size()
            )

        # Transparent host so the card's rounded corners and shadow read cleanly
        # against whatever is on the desktop behind the overlay.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFont(QFont(_font_family()))
        if resizable:
            # Track the cursor with no button held, so the halo shows a resize arrow.
            self.setMouseTracking(True)

        self._build_ui()
        self.hide()

    # --- construction ---

    def _build_ui(self) -> None:
        """Assemble the card: the framed shell, its header, and the subclass body."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            SHADOW_MARGIN_PX, SHADOW_MARGIN_PX, SHADOW_MARGIN_PX, SHADOW_MARGIN_PX
        )

        self._card = QFrame(self)
        self._card.setObjectName("card")
        self._configure_card(self._card)
        self._card.setStyleSheet(self._stylesheet())
        self._card.setGraphicsEffect(self._shadow())
        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        card_layout.addWidget(self._build_header())
        card_layout.addWidget(self._build_body(), self._body_stretch_factor())

    def _build_header(self) -> QFrame:
        """The pink title bar — the drag handle and minimize/maximize toggle."""
        self._header = QFrame(self._card)
        self._header.setObjectName("header")
        self._header.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._resizable:
            # Fixed height so all extra vertical space goes to the body, not here.
            self._header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self._header)
        row.setContentsMargins(14, 9, 12, 9)
        title = QLabel(self._title, self._header)
        title.setObjectName("title")
        # A small per-card status line (e.g. the week label, or "3 ready").
        self._status_label = QLabel("", self._header)
        self._status_label.setObjectName("status")
        self._chevron = QLabel(CHEVRON_OPEN, self._header)
        self._chevron.setObjectName("chevron")

        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self._status_label)
        row.addWidget(self._chevron)
        return self._header

    def _shadow(self) -> QGraphicsDropShadowEffect:
        """A soft pink drop shadow for a gentle 3-D lift."""
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(214, 142, 162, 130))
        return shadow

    def _stylesheet(self) -> str:
        """Common card/header styling plus the subclass's content rules.

        The header's corner radius depends on the minimized state (square all
        round when collapsed, rounded only on top when the body shows beneath it).
        """
        header_radius = "13px" if self._minimized else "13px 13px 0 0"
        base = f"""
            #card {{ background: {CREAM}; border: 1px solid {PINK_FRAME};
                     border-radius: 14px; }}
            #header {{ background: {PINK_HEADER}; border-radius: {header_radius}; }}
            #title {{ color: #ffffff; font-size: 13px; font-weight: 600; }}
            #status {{ color: #fff3f7; font-size: 10px; }}
            #chevron {{ color: #ffffff; font-size: 13px; font-weight: 600; }}
        """
        return base + self._content_stylesheet()

    # --- subclass hooks ---

    def _build_body(self) -> QWidget:
        """Build and return the card's content widget. Subclasses must override."""
        raise NotImplementedError

    def _content_stylesheet(self) -> str:
        """Extra stylesheet rules for the subclass's body content (default: none)."""
        return ""

    def _configure_card(self, card: QFrame) -> None:
        """Set the card's width/size policy (e.g. fixed vs. flexible). Default: none."""

    def _body_stretch_factor(self) -> int:
        """Layout stretch given to the body (1 lets it absorb extra height)."""
        return 0

    def _apply_initial_size(self) -> None:
        """Size the card before it's first shown (default: size to its content)."""
        self.adjustSize()

    def _default_size(self) -> QSize:
        """Opening size for a resizable card with no saved size (resizable cards)."""
        return QSize(320, 320)

    def _size_limits(self) -> tuple[int, int, int]:
        """(min width, max width, min height) for a resizable card."""
        return (240, 760, 200)

    # --- public API ---

    def show_panel(self) -> None:
        """Size the card (via the sizing hook), place it, and show it."""
        self._apply_initial_size()
        self.move(self._initial_top_left())
        self.show()
        self.raise_()
        self._on_geometry_change()

    def toggle_minimized(self) -> None:
        """Collapse to just the header, or expand back to the full card."""
        self._minimized = not self._minimized
        self._chevron.setText(CHEVRON_CLOSED if self._minimized else CHEVRON_OPEN)
        if self._resizable:
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
        else:
            self._body.setVisible(not self._minimized)
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
        """Start a resize (edge/corner, resizable cards) or a possible header drag."""
        self.raise_()
        self._on_geometry_change()
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            # An edge/corner grab in the halo starts a resize (only when expanded);
            # it takes precedence over the header drag below.
            if self._resizable and not self._minimized:
                edges = self._edges_at(point)
                if any(edges):
                    self._resizing = True
                    self._resize_moved = False
                    self._resize_edges = edges
                    self._resize_start_rect = self.geometry()
                    self._resize_start_mouse = self.mapToParent(point)
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
        if self._resizable and self._resizing:
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
        # Idle hover (resizable only): a resize arrow over the halo edges.
        if self._resizable and not self._minimized:
            self.setCursor(self._cursor_for_edges(self._edges_at(point)))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish a resize or drag and remember the new geometry for next time."""
        if self._resizable and self._resizing:
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

    # --- resizing (resizable cards only) ---

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
        kept inside the overlay. The inner layout reflows to fill the new size.
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
        min_width, max_width, min_height = self._size_limits()
        width = max(min_width, min(size.width(), max_width))
        max_height = size.height()
        parent = self.parentWidget()
        if parent is not None:
            max_height = parent.height()
        height = max(min_height, min(size.height(), max_height))
        return QSize(width, height)

    # --- placement & clamping ---

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

    def _restyle(self) -> None:
        """Re-apply the stylesheet so class-based and state-based rules refresh."""
        self._card.setStyleSheet(self._stylesheet())

    def _load_saved_state(self) -> tuple[QPoint | None, QSize | None]:
        """Read the remembered top-left, and the size for resizable cards.

        Best-effort and tolerant: a missing/unreadable file — or an older one
        that saved only the position — just means 'use the default' for whatever's
        absent, so a fresh checkout never errors. Only on-screen geometry is
        stored, never any personal data.
        """
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, None
        try:
            point = QPoint(int(data["x"]), int(data["y"]))
        except (KeyError, TypeError, ValueError):
            point = None
        size = None
        if self._resizable:
            try:
                size = QSize(int(data["w"]), int(data["h"]))
                if size.width() <= 0 or size.height() <= 0:
                    size = None
            except (KeyError, TypeError, ValueError):
                size = None
        return point, size

    def _save_state(self) -> None:
        """Persist the current position (and size, if resizable); best-effort only."""
        rect = self.geometry()
        data = {"x": rect.x(), "y": rect.y()}
        if self._resizable:
            data["w"] = rect.width()
            data["h"] = rect.height()
        try:
            self._state_path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass
