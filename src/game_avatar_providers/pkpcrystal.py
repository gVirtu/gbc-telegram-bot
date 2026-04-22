"""Avatar provider for Polished Crystal (PKPCRYSTAL)."""

from pathlib import Path
from PIL import Image
from src.utils.state_manager import state_manager

_AVATAR_PATH = Path("assets/dynamic/pkpcrystal/trainers/1.png")
_cached: Image.Image | None = None


def _load() -> Image.Image:
    """Load and cache the default avatar image."""
    global _cached
    if _cached is None:
        _cached = Image.open(_AVATAR_PATH).convert("RGBA")
    return _cached


def get_avatar(player: dict) -> Image.Image | None:
    """Return the default avatar for pkpcrystal, ignoring player data."""
    platform = player["platform"]
    user_id = player["user_id"]
    
    avatar_key = "pkpcrystal_avatar_path"
    
    avatar_path = state_manager.get_user_preference(platform, user_id, avatar_key)
    if avatar_path:
        return Image.open(avatar_path).convert("RGBA")

    return _load()
