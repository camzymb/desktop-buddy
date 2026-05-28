"""Sound playback for the buddy: a short attention 'pop' plus voice clips.

Wraps pygame's mixer so the rest of the app never touches audio details.
Sounds are preloaded once to avoid a disk-read hitch mid-message. If no
audio device is available (e.g. a headless session), the player disables
itself and every play call becomes a harmless no-op, so the buddy can still
talk visually without crashing.
"""

# === IMPORTS ===

import random
from pathlib import Path

import pygame


# === CONSTANTS ===

# Short attention sound played just before each voice clip.
POP_SOUND_FILENAME = "pop.mp3"

# Glob for the recorded voice clips; one is chosen at random per message.
VOICE_GLOB = "voice_*.mp3"


# === SOUND PLAYER ===

class SoundPlayer:
    """Loads and plays the buddy's sound effects through pygame's mixer."""

    def __init__(self, sounds_dir: Path) -> None:
        self._enabled: bool = self._init_mixer()
        self._pop_sound: pygame.mixer.Sound | None = None
        self._voice_sounds: list[pygame.mixer.Sound] = []

        if self._enabled:
            self._pop_sound = pygame.mixer.Sound(str(sounds_dir / POP_SOUND_FILENAME))
            self._voice_sounds = [
                pygame.mixer.Sound(str(path))
                for path in sorted(sounds_dir.glob(VOICE_GLOB))
            ]

    @staticmethod
    def _init_mixer() -> bool:
        """Start pygame's mixer, returning False if no audio device is available."""
        try:
            pygame.mixer.init()
            return True
        except pygame.error:
            return False

    def play_pop(self) -> float:
        """Play the attention 'pop' and return its length in seconds.

        The caller uses the returned length to schedule the voice clip so it
        starts right after the pop finishes instead of talking over it.
        Returns 0.0 when audio is unavailable, so the voice plays immediately.
        """
        if not self._enabled or self._pop_sound is None:
            return 0.0
        self._pop_sound.play()
        return self._pop_sound.get_length()

    def play_random_voice(self) -> None:
        """Play one randomly chosen voice clip, if any are loaded."""
        if not self._enabled or not self._voice_sounds:
            return
        random.choice(self._voice_sounds).play()
