"""Desktop Buddy — Chunk A: a floating, transparent, always-on-top sprite."""

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

# Where the project's assets live. Using Path(__file__) means the script
# works no matter which folder you run it from.
PROJECT_DIR = Path(__file__).resolve().parent
SPRITES_DIR = PROJECT_DIR / "sprites"

# How tall the buddy should be, in pixels. Width is computed automatically
# to preserve the original aspect ratio of the sprite.
BUDDY_HEIGHT_PX = 200

# How far from the screen edges the buddy should sit.
EDGE_MARGIN_PX = 20

# The sprite shown at startup. Future chunks will swap this out for
# walking frames, emotion poses, etc.
DEFAULT_SPRITE = SPRITES_DIR / "idle_front.png"


class BuddyWindow(QWidget):
    """A frameless, transparent, always-on-top window that shows a sprite."""

    def __init__(self) -> None:
        super().__init__()

        # Frameless = no title bar / borders.
        # StaysOnTop = floats above other windows.
        # Tool = hides the window from the taskbar and alt-tab switcher.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        # Makes the window's own background see-through, so only the
        # non-transparent pixels of the PNG are visible.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # The QLabel is the actual canvas that holds the sprite image.
        self.sprite_label = QLabel(self)

        self.set_sprite(DEFAULT_SPRITE)
        self.position_bottom_right()

    def set_sprite(self, sprite_path: Path) -> None:
        """Load a PNG, scale it to BUDDY_HEIGHT_PX tall, and display it."""
        pixmap = QPixmap(str(sprite_path))
        if pixmap.isNull():
            # Loud failure beats a silently invisible buddy.
            raise FileNotFoundError(f"Could not load sprite: {sprite_path}")

        scaled = pixmap.scaledToHeight(
            BUDDY_HEIGHT_PX,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.sprite_label.setPixmap(scaled)
        self.sprite_label.resize(scaled.size())
        # Resize the window itself to exactly match the sprite — no extra
        # transparent padding around the edges.
        self.resize(scaled.size())

    def position_bottom_right(self) -> None:
        """Park the window in the bottom-right of the primary screen."""
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        x = screen_geometry.right() - self.width() - EDGE_MARGIN_PX
        y = screen_geometry.bottom() - self.height() - EDGE_MARGIN_PX
        self.move(x, y)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Escape closes the window so we're never stuck with a stubborn buddy.
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    buddy = BuddyWindow()
    buddy.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
