"""Avatar provider for Polished Crystal (PKPCRYSTAL)."""

from pathlib import Path
from PIL import Image
from src.utils.state_manager import state_manager
from src.game_utils.pkpcrystal.assets import load_pokemon_asset

_AVATAR_PATH = Path("assets/dynamic/pkpcrystal/trainers/1.png")
_cached: Image.Image | None = None


def _load_default() -> Image.Image:
    """Load and cache the default avatar image."""
    global _cached
    if _cached is None:
        _cached = Image.open(_AVATAR_PATH).convert("RGBA")
    return _cached


def _load_avatar_image(platform: str, user_id: str) -> Image.Image | None:
    avatar_key = "pkpcrystal_avatar_path"
    
    avatar_path = state_manager.get_user_preference(platform, user_id, avatar_key)

    if avatar_path:
        return Image.open(avatar_path).convert("RGBA")
    return _load_default()


def get_avatar(img: Image.Image, scale: int, area: tuple[int, int, int, int], player: dict):
    """Draw the avatar and trainer card mons for pkpcrystal."""
    platform = player["platform"]
    user_id = player["user_id"]

    ax, ay, ax_max, ay_max = area
    avatar_sz = ax_max - ax

    avatar_img = _load_avatar_image(platform, user_id)
    if avatar_img:
        avatar_img = avatar_img.resize((avatar_sz, avatar_sz), Image.Resampling.LANCZOS)
        img.paste(avatar_img, (ax, ay), mask=avatar_img if avatar_img.mode == "RGBA" else None)
        
    mon_start_x = ax + avatar_sz + 2 * scale
    mon_start_y = ay + avatar_sz - 16 * scale
    mon_sz = 8 * scale

    for i in range(6):
        mon_key = f"pkpcrystal_trainer_card_mon_{i}_species"
        mon_species = state_manager.get_user_preference(platform, user_id, mon_key)
        
        if mon_species is not None:
            mon_img = load_pokemon_asset(mon_species)
            
            if mon_img is None:
                continue
            
            mon_x = mon_start_x + (i % 3) * mon_sz
            mon_y = mon_start_y + (i // 3) * mon_sz

            mon_img = mon_img.resize((mon_sz, mon_sz), Image.Resampling.LANCZOS)
            img.paste(mon_img, (mon_x, mon_y), mask=mon_img if mon_img.mode == "RGBA" else None)
