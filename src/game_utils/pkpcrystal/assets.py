from pathlib import Path
from typing import Optional
import logging

from PIL import Image

logger = logging.getLogger(__name__)

_pokemon_icon_asset_cache: dict[int, Optional["Image.Image"]] = {}


def load_pokemon_asset(species_id: int) -> Optional[Image.Image]:
    """Load and cache pokemon PNG (RGBA). Returns None if missing."""
    if species_id in _pokemon_icon_asset_cache:
        return _pokemon_icon_asset_cache[species_id]

    asset_path = f"assets/dynamic/pkpcrystal/minis/{species_id}.png"
    if not Path(asset_path).exists():
        logger.warning(f"Pokémon icon asset not found: {asset_path}")
        _pokemon_icon_asset_cache[species_id] = None
        return None

    img = Image.open(asset_path).crop((0, 0, 16, 16)).convert("RGBA")
    _pokemon_icon_asset_cache[species_id] = img
    return img


