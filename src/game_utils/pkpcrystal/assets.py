from pathlib import Path
from typing import Optional
import logging

from PIL import Image

from src.game_utils.pkpcrystal.reader import EXTSPECIES_MASK, MON_EXTSPECIES_F

logger = logging.getLogger(__name__)

SPECIESFORM_MASK = 0x3F

_pokemon_icon_asset_cache: dict[int, Optional["Image.Image"]] = {}
_cosmetic_table: list[tuple[int, int]] = []
_cosmetic_gap: int = 0


def _forms_match(table_form: int, mon_form: int) -> bool:
    if table_form & 0x80:
        return table_form == mon_form
    return (table_form & 0x7F) == (mon_form & 0x7F)


def init_form_lookup(pyboy) -> None:
    global _cosmetic_gap

    bank, addr = pyboy.symbol_lookup("CosmeticSpeciesAndFormTable")

    while True:
        species = pyboy.memory[(bank, addr)]
        if species == 0:
            break
        form_byte = pyboy.memory[(bank, addr + 1)]
        _cosmetic_table.append((species, form_byte))
        addr += 2

    _cosmetic_gap = 393 - len(_cosmetic_table)

    # logger.info(
    #     "Form lookup init: cosmetic_table=%d entries, gap=%d",
    #     len(_cosmetic_table),
    #     _cosmetic_gap,
    # )
    # for i in range(max(0, len(_cosmetic_table) - 6), len(_cosmetic_table)):
    #     sp, fb = _cosmetic_table[i]
    #     logger.info(
    #         "  table[%d]: species=0x%02X (%d) form=0x%02X (%d)",
    #         i, sp, sp, fb, fb,
    #     )


def get_mini_icon_index(species_id: int, form_byte: int) -> int:
    species_low = species_id & 0xFF
    b = form_byte & SPECIESFORM_MASK

    for i, (t_species, t_form) in enumerate(_cosmetic_table):
        if t_species == species_low and _forms_match(t_form, b):
            return _cosmetic_gap + i

    return species_id - 1


def load_pokemon_asset(species_id: int, form_byte: int = 0) -> Optional[Image.Image]:
    species_id = int(species_id)
    form_byte = int(form_byte)
    icon_index = get_mini_icon_index(species_id, form_byte)
    cache_key = icon_index

    if cache_key in _pokemon_icon_asset_cache:
        return _pokemon_icon_asset_cache[cache_key]

    asset_path = f"assets/dynamic/pkpcrystal/minis/{icon_index + 1}.png"
    if not Path(asset_path).exists():
        logger.warning(f"Pokémon icon asset not found: {asset_path}")
        _pokemon_icon_asset_cache[cache_key] = None
        return None

    img = Image.open(asset_path).crop((0, 0, 16, 16)).convert("RGBA")
    _pokemon_icon_asset_cache[cache_key] = img
    return img
