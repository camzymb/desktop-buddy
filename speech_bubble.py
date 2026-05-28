"""A soft, rounded speech bubble that floats above the buddy's head.

The bubble paints its own cream-coloured body with a little tail pointing
down toward the character, word-wraps a short message, and sizes itself to
fit. It fades in and out via an opacity effect for a gentle appear/disappear
that matches her watercolour aesthetic.
"""

# === IMPORTS ===

from collections.abc import Callable

from PyQt6.QtCore import QPropertyAnimation, QRect, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget


# === CONSTANTS ===

# Soft watercolour palette: warm cream fill, muted taupe border, cocoa text.
BUBBLE_FILL_COLOR = QColor(255, 250, 240)
BUBBLE_BORDER_COLOR = QColor(214, 197, 178)
BUBBLE_TEXT_COLOR = QColor(92, 78, 64)

# Friendly rounded fonts first, with graceful fallbacks if none are installed.
BUBBLE_FONT_FAMILIES = ["Nunito", "Quicksand", "Comic Sans MS", "Sans Serif"]
BUBBLE_FONT_POINT_SIZE = 15

# Inner breathing room around the text and how round the corners are.
BUBBLE_PADDING_PX = 18
BUBBLE_CORNER_RADIUS_PX = 22
BUBBLE_BORDER_WIDTH_PX = 2

# The little pointer at the bottom of the bubble, aimed at her head.
BUBBLE_TAIL_WIDTH_PX = 26
BUBBLE_TAIL_HEIGHT_PX = 16

# Longest the text may run before it wraps onto another line.
BUBBLE_MAX_TEXT_WIDTH_PX = 280

# Fade-in / fade-out duration in milliseconds.
BUBBLE_FADE_MS = 400

# Combined flags for laying out and drawing centred, word-wrapped text.
_TEXT_FLAGS = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignCenter)


# === SPEECH BUBBLE ===

class SpeechBubble(QWidget):
    """A self-painting, self-sizing speech bubble with fade in/out."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        # Clicks pass straight through the bubble to whatever is underneath.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._text: str = ""
        self._font = QFont()
        self._font.setFamilies(BUBBLE_FONT_FAMILIES)
        self._font.setPointSize(BUBBLE_FONT_POINT_SIZE)

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
        """Draw the rounded body, the downward tail, and the centred text."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        body_height = self.height() - BUBBLE_TAIL_HEIGHT_PX
        body_rect = QRectF(0, 0, self.width(), body_height)

        bubble_path = QPainterPath()
        bubble_path.addRoundedRect(
            body_rect, BUBBLE_CORNER_RADIUS_PX, BUBBLE_CORNER_RADIUS_PX
        )

        # A triangle tail centred along the bottom edge, merged into the body.
        tail_center_x = self.width() / 2
        tail_top_y = body_height - 1  # slight overlap so the join is seamless
        tail_path = QPainterPath()
        tail_path.moveTo(tail_center_x - BUBBLE_TAIL_WIDTH_PX / 2, tail_top_y)
        tail_path.lineTo(tail_center_x, body_height + BUBBLE_TAIL_HEIGHT_PX)
        tail_path.lineTo(tail_center_x + BUBBLE_TAIL_WIDTH_PX / 2, tail_top_y)
        tail_path.closeSubpath()

        painter.setPen(QPen(BUBBLE_BORDER_COLOR, BUBBLE_BORDER_WIDTH_PX))
        painter.setBrush(BUBBLE_FILL_COLOR)
        painter.drawPath(bubble_path.united(tail_path))

        painter.setPen(BUBBLE_TEXT_COLOR)
        painter.setFont(self._font)
        text_area = body_rect.adjusted(
            BUBBLE_PADDING_PX, BUBBLE_PADDING_PX,
            -BUBBLE_PADDING_PX, -BUBBLE_PADDING_PX,
        )
        painter.drawText(text_area, _TEXT_FLAGS, self._text)
