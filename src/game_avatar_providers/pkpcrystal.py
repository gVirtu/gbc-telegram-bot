"""Avatar provider for Polished Crystal (PKPCRYSTAL)."""

from pathlib import Path
from PIL import Image

_AVATAR_PATH = Path("assets/pkpcrystal/default_avatar.png")
_cached: Image.Image | None = None


def _load() -> Image.Image:
    """Load and cache the default avatar image."""
    global _cached
    if _cached is None:
        _cached = Image.open(_AVATAR_PATH).convert("RGBA")
    return _cached


def get_avatar(player: dict) -> Image.Image | None:
    """Return the default avatar for pkpcrystal, ignoring player data."""
    return _load()
