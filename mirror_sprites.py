"""Dev utility: generate LEFT-facing walk frames by mirroring the RIGHT-facing ones.

The buddy's walk animation keeps separate sprite sets for each direction. Rather
than hand-draw both, we draw only the RIGHT-facing frames and flip them
horizontally to produce the LEFT set. Mirroring (instead of drawing the left
frames separately) guarantees the two directions stay perfectly consistent and,
crucially, that the character's head always faces her direction of travel — a
mirrored right-facing frame can never accidentally turn its head backward.

Run this manually whenever you add or update the right-facing frames:

    .venv/bin/python mirror_sprites.py

It finds every `walk_right_*.png` in sprites/ and writes a matching
`walk_left_*.png` beside it (overwriting any existing left frame).
"""

# === IMPORTS ===

import sys
from pathlib import Path

from PyQt6.QtGui import QImage


# === CONSTANTS ===

PROJECT_DIR = Path(__file__).resolve().parent
SPRITES_DIR = PROJECT_DIR / "sprites"

# Filename glob for the hand-drawn source frames, plus the token swap that
# turns a right-facing filename into its left-facing counterpart.
RIGHT_FRAME_GLOB = "walk_right_*.png"
RIGHT_TOKEN = "walk_right"
LEFT_TOKEN = "walk_left"


# === MIRRORING ===

def mirror_frame(source_path: Path, destination_path: Path) -> None:
    """Flip one sprite horizontally and save it, preserving transparency.

    Raises FileNotFoundError if the source image can't be loaded (e.g. the
    file is missing or isn't a valid image), so a bad asset fails loudly here
    rather than silently producing a blank left frame.
    """
    image = QImage(str(source_path))
    if image.isNull():
        raise FileNotFoundError(f"Could not load sprite: {source_path}")

    mirrored_image = image.mirrored(True, False)  # horizontal flip only
    if not mirrored_image.save(str(destination_path)):
        raise OSError(f"Could not write mirrored sprite: {destination_path}")


def mirror_all_right_frames() -> int:
    """Mirror every right-facing walk frame into its left-facing counterpart.

    Returns the number of frames mirrored. The frame count is whatever exists
    on disk, so this works unchanged whether there are 4, 6, or any number of
    right-facing frames.
    """
    right_frames = sorted(SPRITES_DIR.glob(RIGHT_FRAME_GLOB))
    if not right_frames:
        print(f"No '{RIGHT_FRAME_GLOB}' files found in {SPRITES_DIR}.")
        return 0

    for source_path in right_frames:
        left_filename = source_path.name.replace(RIGHT_TOKEN, LEFT_TOKEN)
        destination_path = source_path.with_name(left_filename)
        mirror_frame(source_path, destination_path)
        print(f"  {source_path.name}  ->  {destination_path.name}")

    return len(right_frames)


# === ENTRY POINT ===

def main() -> int:
    """Mirror the right-facing frames and report how many were produced."""
    frames_mirrored = mirror_all_right_frames()
    print(f"Done: mirrored {frames_mirrored} frame(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
