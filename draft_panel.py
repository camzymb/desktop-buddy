"""The draft-replies panel that floats on the desktop.

A small, professional pink card — the same family as the weekly-plan panel —
that lists the buddy's drafted email replies. Each draft shows who it's to, the
subject, the drafted text (selectable, so it can be copied), and an "Open in
Gmail" button that opens a prefilled Gmail compose window in the browser. Camille
reviews each one and sends it herself; the buddy never sends.

The shared card behaviour — draggable header, click-to-minimize, edge/corner
resizing, and remembering its dragged position AND chosen size between launches —
lives in `CardPanel`. This file adds only the scrolling list of draft cards,
their styling, and the fit-to-content opening height: with no saved size yet the
card opens just tall enough for its drafts (capped to most of the screen, past
which the slim scrollbar takes over).
"""

# === IMPORTS ===

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from card_panel import SHADOW_MARGIN_PX, PINK_SOFT, TEXT, TEXT_SOFT, CardPanel


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent

# Remembered drag position AND window size (only on-screen numbers — no personal
# data). Kept out of the repo; see .gitignore.
PANEL_STATE_PATH = PROJECT_DIR / "draft_panel_state.json"

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

# Accent colours for the "Open in Gmail" button (specific to this card).
BUTTON_PINK = "#f4a9be"
BUTTON_PINK_HOVER = "#ef93ad"


# === DRAFT PANEL ===

class DraftPanel(CardPanel):
    """A small, draggable, minimizable, RESIZABLE card listing drafted replies.

    The owner supplies two callbacks: `on_geometry_change` (handled by the base)
    keeps the overlay's click-through mask in sync as the card moves, collapses,
    or resizes, and `on_open_draft` is invoked with a Gmail compose URL when a
    draft's "Open in Gmail" button is clicked.
    """

    def __init__(
        self,
        parent: QWidget,
        on_geometry_change: Callable[[], None],
        on_open_draft: Callable[[str], None],
    ) -> None:
        # Stored before the base builds the UI, since each card's button wires to it.
        self._on_open_draft = on_open_draft
        super().__init__(
            parent,
            on_geometry_change,
            state_path=PANEL_STATE_PATH,
            title="Draft Replies 🤍",
            resizable=True,
        )

    # --- construction (card-specific body + styling + sizing) ---

    def _configure_card(self, card: QWidget) -> None:
        """Let the card fill the (resizable) window, down to a sensible minimum."""
        # No longer a FIXED width — the card fills the resizable window, so
        # dragging an edge makes the whole card grow/shrink.
        card.setMinimumWidth(MIN_WIDTH_PX - 2 * SHADOW_MARGIN_PX)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _body_stretch_factor(self) -> int:
        """The body absorbs all extra height so the draft list fills the window."""
        return 1

    def _default_size(self) -> QSize:
        """Opening size when there is no saved size and no drafts to measure yet."""
        return QSize(DEFAULT_WIDTH_PX, DEFAULT_HEIGHT_PX)

    def _size_limits(self) -> tuple[int, int, int]:
        """(min width, max width, min height) the window may be resized to."""
        return (MIN_WIDTH_PX, MAX_WIDTH_PX, MIN_HEIGHT_PX)

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
        # The scroll area FILLS the (resizable) window, so a taller window shows
        # more of the list; the scrollbar appears only when the drafts are taller.
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

    def _content_stylesheet(self) -> str:
        """Styling for the scroll area, the per-draft cards and the Gmail button."""
        return f"""
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
        self._status_label.setText(
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

    # --- fit-to-content sizing ---

    def _apply_initial_size(self) -> None:
        """Open at the saved size if there is one, else fitted to the drafts.

        A size you dragged before always wins, so manual sizing stays
        predictable. With no saved size yet, the height is fitted to the drafts
        so there's no empty space below them.
        """
        size = self._clamped_size(
            self._saved_size if self._saved_size is not None
            else self._fit_to_content_size()
        )
        self.resize(size)
        self._expanded_size = size

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
