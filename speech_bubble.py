"""A soft, kawaii speech bubble that floats above the buddy's head.

The bubble paints its own soft, flat baby-pink rounded body (borderless,
comic-style) with a little pointed tail aimed down at the character, tucks
small daisy flowers into two corners and doodles tiny "sparkle" dash accents
near the other two, and word-wraps a short message in a cute rounded font. It
fades in and out via an opacity effect for a gentle appear/disappear that
matches her watercolour aesthetic.

Font: "Fredoka" by Hanken Design Co., licensed under the SIL Open Font
License 1.1 and bundled in assets/fonts/ (see assets/fonts/OFL.txt). Loading
it locally keeps rendering consistent and removes any internet dependency; a
system-font fallback is used if the bundled file is ever missing.
"""

# === IMPORTS ===

import math
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QLineF, QPointF, QPropertyAnimation, QRect, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget


# === CONSTANTS ===

# Kawaii palette: soft, flat baby-pink fill (borderless, comic-style), with a
# slightly deeper rose for the little decorative accents and warm-brown text.
BUBBLE_FILL_COLOR = QColor(250, 198, 209)
BUBBLE_ACCENT_COLOR = QColor(244, 166, 190)
BUBBLE_TEXT_COLOR = QColor(99, 63, 60)

# Bundled cute rounded font (SIL OFL). System fallbacks if the file is missing.
FONT_PATH = Path(__file__).resolve().parent / "assets" / "fonts" / "Fredoka-VariableFont.ttf"
BUBBLE_FONT_FALLBACK_FAMILIES = ["Quicksand", "Comfortaa", "Nunito", "Sans Serif"]
BUBBLE_FONT_POINT_SIZE = 15

# Inner breathing room around the text and how round the corners are. The
# generous radius gives the soft, pillowy comic-bubble silhouette.
BUBBLE_PADDING_PX = 24
BUBBLE_CORNER_RADIUS_PX = 30

# The little pointed tail at the bottom of the bubble, aimed down at her head.
# Kept narrow and tall for the comic "speech" look in the reference art.
BUBBLE_TAIL_WIDTH_PX = 22
BUBBLE_TAIL_HEIGHT_PX = 20

# Decorative daisy flowers tucked into two diagonal corners: deeper-pink petals
# around a warm-yellow center. FLOWER_RADIUS_PX scales the whole flower.
FLOWER_PETAL_COLOR = QColor(255, 158, 190)
FLOWER_CENTER_COLOR = QColor(255, 206, 92)
FLOWER_PETAL_COUNT = 5
FLOWER_RADIUS_PX = 9
FLOWER_CORNER_INSET_PX = 18

# Tiny comic "sparkle" dash accents near the other two corners: a pair of short
# rounded strokes, like the little marks doodled around the reference bubble.
ACCENT_DASH_COUNT = 2
ACCENT_DASH_LENGTH_PX = 11
ACCENT_DASH_WIDTH_PX = 3
ACCENT_DASH_GAP_PX = 7
ACCENT_CORNER_INSET_PX = 15

# Longest the text may run before it wraps onto another line.
BUBBLE_MAX_TEXT_WIDTH_PX = 280

# Fade-in / fade-out duration in milliseconds.
BUBBLE_FADE_MS = 400

# Combined flags for laying out and drawing centred, word-wrapped text.
_TEXT_FLAGS = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignCenter)

# Family name the bundled font registers as, resolved once on first use.
_loaded_font_family: str | None = None


def _bubble_font() -> QFont:
    """Return the bundled Fredoka font, loading it once; fall back if missing.

    Requires a running QApplication, so it is called when the bubble is built
    (after the app starts), never at import time.
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
        font.setFamilies(BUBBLE_FONT_FALLBACK_FAMILIES)
    font.setPointSize(BUBBLE_FONT_POINT_SIZE)
    return font


# === SPEECH BUBBLE ===

class SpeechBubble(QWidget):
    """A self-painting, self-sizing kawaii speech bubble with fade in/out."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        # Clicks pass straight through the bubble to whatever is underneath.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._text: str = ""
        self._font = _bubble_font()

        # An opacity effect drives the fade animations.
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade.setDuration(BUBBLE_FADE_MS)
        self._fade.finished.connect(self._on_fade_finished)
        self._fade_target_opacity: float = 0.0
        self._on_hidden: Callable[[], None] | None = None

    # --- public API ---

    def set_message(self, text: str) -> None:
        """Set the bubble's text and resize the widget to fit it."""
        self._text = text
        self._resize_to_text()
        self.update()

    def fade_in(self) -> None:
        """Gently fade the bubble into view."""
        self.show()
        self._animate_opacity_to(1.0)

    def fade_out(self, on_hidden: Callable[[], None]) -> None:
        """Gently fade the bubble out, calling on_hidden once fully hidden."""
        self._on_hidden = on_hidden
        self._animate_opacity_to(0.0)

    # --- internals ---

    def _animate_opacity_to(self, target_opacity: float) -> None:
        """Animate the opacity effect from its current value to the target."""
        self._fade_target_opacity = target_opacity
        self._fade.stop()
        self._fade.setStartValue(self._opacity_effect.opacity())
        self._fade.setEndValue(target_opacity)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        """Hide the widget and notify the caller once a fade-out completes."""
        if self._fade_target_opacity > 0.0:
            return
        self.hide()
        if self._on_hidden is not None:
            callback = self._on_hidden
            self._on_hidden = None
            callback()

    def _resize_to_text(self) -> None:
        """Grow the widget to fit the wrapped text plus padding and the tail."""
        text_rect = QFontMetrics(self._font).boundingRect(
            QRect(0, 0, BUBBLE_MAX_TEXT_WIDTH_PX, 10_000),
            _TEXT_FLAGS,
            self._text,
        )
        body_width = text_rect.width() + 2 * BUBBLE_PADDING_PX
        body_height = text_rect.height() + 2 * BUBBLE_PADDING_PX
        self.resize(body_width, body_height + BUBBLE_TAIL_HEIGHT_PX)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the flat body and tail, corner accents and flowers, then text."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        body_height = self.height() - BUBBLE_TAIL_HEIGHT_PX
        body_rect = QRectF(0, 0, self.width(), body_height)

        bubble_path = QPainterPath()
        bubble_path.addRoundedRect(
            body_rect, BUBBLE_CORNER_RADIUS_PX, BUBBLE_CORNER_RADIUS_PX
        )

        # A narrow triangle tail centred along the bottom edge, merged into the
        # body. Centred so it always points straight down at her head.
        tail_center_x = self.width() / 2
        tail_top_y = body_height - 1  # slight overlap so the join is seamless
        tail_path = QPainterPath()
        tail_path.moveTo(tail_center_x - BUBBLE_TAIL_WIDTH_PX / 2, tail_top_y)
        tail_path.lineTo(tail_center_x, body_height + BUBBLE_TAIL_HEIGHT_PX)
        tail_path.lineTo(tail_center_x + BUBBLE_TAIL_WIDTH_PX / 2, tail_top_y)
        tail_path.closeSubpath()

        # Flat, borderless fill for the soft comic look from the reference art.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BUBBLE_FILL_COLOR)
        painter.drawPath(bubble_path.united(tail_path))

        self._draw_corner_accents(painter, body_height)
        self._draw_corner_flowers(painter, body_height)

        painter.setPen(BUBBLE_TEXT_COLOR)
        painter.setFont(self._font)
        text_area = body_rect.adjusted(
            BUBBLE_PADDING_PX, BUBBLE_PADDING_PX,
            -BUBBLE_PADDING_PX, -BUBBLE_PADDING_PX,
        )
        painter.drawText(text_area, _TEXT_FLAGS, self._text)

    def _draw_corner_flowers(self, painter: QPainter, body_height: float) -> None:
        """Tuck a small daisy into the top-left and bottom-right body corners."""
        inset = FLOWER_CORNER_INSET_PX
        corners = (
            QPointF(inset, inset),
            QPointF(self.width() - inset, body_height - inset),
        )
        for corner in corners:
            self._draw_flower(painter, corner)

    def _draw_corner_accents(self, painter: QPainter, body_height: float) -> None:
        """Doodle a pair of sparkle dashes near the top-right/bottom-left corners."""
        inset = ACCENT_CORNER_INSET_PX
        anchors = (
            QPointF(self.width() - inset, inset),
            QPointF(inset, body_height - inset),
        )
        for anchor in anchors:
            self._draw_accent_dashes(painter, anchor)

    def _draw_accent_dashes(self, painter: QPainter, center: QPointF) -> None:
        """Paint a little cluster of short, round-capped diagonal "/" strokes."""
        pen = QPen(BUBBLE_ACCENT_COLOR, ACCENT_DASH_WIDTH_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        half_length = ACCENT_DASH_LENGTH_PX / 2
        first_offset = -(ACCENT_DASH_COUNT - 1) / 2
        for dash_index in range(ACCENT_DASH_COUNT):
            offset_x = (first_offset + dash_index) * ACCENT_DASH_GAP_PX
            stroke = QLineF(
                center.x() + offset_x - half_length * 0.5, center.y() + half_length,
                center.x() + offset_x + half_length * 0.5, center.y() - half_length,
            )
            painter.drawLine(stroke)

    def _draw_flower(self, painter: QPainter, center: QPointF) -> None:
        """Paint one daisy: a ring of pink petals around a yellow center."""
        petal_radius = FLOWER_RADIUS_PX * 0.5
        petal_distance = FLOWER_RADIUS_PX * 0.55

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(FLOWER_PETAL_COLOR)
        for petal_index in range(FLOWER_PETAL_COUNT):
            angle = (2 * math.pi / FLOWER_PETAL_COUNT) * petal_index
            petal_center = QPointF(
                center.x() + petal_distance * math.cos(angle),
                center.y() + petal_distance * math.sin(angle),
            )
            painter.drawEllipse(petal_center, petal_radius, petal_radius)

        painter.setBrush(FLOWER_CENTER_COLOR)
        painter.drawEllipse(center, FLOWER_RADIUS_PX * 0.4, FLOWER_RADIUS_PX * 0.4)
