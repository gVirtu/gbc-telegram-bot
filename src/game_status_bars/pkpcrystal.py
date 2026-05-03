"""Status bar data provider for Polished Crystal (PKPCRYSTAL)."""

from pathlib import Path
from typing import Any, Optional
import bisect
import logging

from PIL import Image, ImageDraw, ImageFont

from src.game_utils.pkpcrystal.lz import Decompressed
from src.utils.gbc_graphics import decode_1bpp, decode_2bpp, gbc_color_to_rgba
from src.utils.frame_utils import draw_text_to_fit
from src.game_utils.pkpcrystal.enum import BattleMode, GrowthRate, EXP_PER_LEVEL
from src.game_utils.pkpcrystal.reader import (
    symbol_read_u8, symbol_read_u16le, symbol_read_u24le,
    read_u8, read_u16, get_nth_string_addr, decode_text, get_pokemon_name
)
from src.game_utils.pkpcrystal.assets import load_pokemon_asset

logger = logging.getLogger(__name__)

_icon_cache: dict[tuple[str, int], Optional[Image.Image]] = {}
_badge_asset_cache: dict[tuple[str, int], Optional["Image.Image"]] = {}
_unifont_cache: dict[int, Optional[ImageFont.ImageFont]] = {}


def init(pyboy) -> None:
    """Extract ROM assets once at startup. Skips if already done."""
    out_dir = Path("assets/dynamic/pkpcrystal")
    
    # Prepare directories
    (out_dir / "minis").mkdir(parents=True, exist_ok=True)
    (out_dir / "badges" / "johto").mkdir(parents=True, exist_ok=True)
    (out_dir / "badges" / "kanto").mkdir(parents=True, exist_ok=True)
    (out_dir / "trainers").mkdir(parents=True, exist_ok=True)

    # Extract pokemon minis
    ptrs_bank, ptrs_base_addr = pyboy.symbol_lookup("MiniIconPointers")
    for i in range(0, 393):
        out_path = out_dir / "minis" / f"{i + 1}.png"
        if out_path.exists():
            continue

        base_addr = ptrs_base_addr + (i * 7)
        mini_bank = pyboy.memory[ptrs_bank, base_addr]
        mini_addr = read_u16(pyboy, ptrs_bank, base_addr + 1)
        mini_mask_addr = read_u16(pyboy, ptrs_bank, base_addr + 3)

        palette = _read_mini_palette(pyboy, i + 1)

        mask = _extract_mask_sprite(pyboy, mini_bank, mini_mask_addr)
        _extract_mini_sprite(pyboy, mini_bank, mini_addr, palette, mask, out_path=out_path)

    # Extract trainer card badges
    johto_badges_bank, johto_badges_bank_base_addr = pyboy.symbol_lookup("BadgeGFX")
    kanto_badges_bank, kanto_badges_bank_base_addr = pyboy.symbol_lookup("BadgeGFX2")
    
    johto_badge_palettes_bank, johto_badge_palettes_addr = pyboy.symbol_lookup("JohtoBadgePalettes")
    kanto_badge_palettes_bank, kanto_badge_palettes_addr = pyboy.symbol_lookup("KantoBadgePalettes")
    
    johto_badge_gfx = _extract_badge_gfx(pyboy, johto_badges_bank, johto_badges_bank_base_addr)
    kanto_badge_gfx = _extract_badge_gfx(pyboy, kanto_badges_bank, kanto_badges_bank_base_addr)
    
    for i in range(0, 8):
        johto_out_path = out_dir / "badges" / "johto" / f"{i + 1}.png"
        kanto_out_path = out_dir / "badges" / "kanto" / f"{i + 1}.png"

        if johto_out_path.exists() and kanto_out_path.exists():
            continue

        johto_palette = _read_palette(pyboy, johto_badge_palettes_bank, johto_badge_palettes_addr, i)
        kanto_palette = _read_palette(pyboy, kanto_badge_palettes_bank, kanto_badge_palettes_addr, i)
        
        _save_badge_sprite(johto_badge_gfx, johto_palette, i, out_path=johto_out_path)
        _save_badge_sprite(kanto_badge_gfx, kanto_palette, i, out_path=kanto_out_path)
        
    # Extract trainer pics
    ptrs_bank, ptrs_base_addr = pyboy.symbol_lookup("TrainerPicPointers")
    palettes_bank, palettes_base_addr = pyboy.symbol_lookup("TrainerPalettes")
    for i in range(0, 153):
        out_path = out_dir / "trainers" / f"{i + 1}.png"
        if out_path.exists():
            continue

        base_addr = ptrs_base_addr + (i * 3)
        trainer_bank = pyboy.memory[ptrs_bank, base_addr]
        trainer_addr = read_u16(pyboy, ptrs_bank, base_addr + 1)

        palette = _read_palette(pyboy, palettes_bank, palettes_base_addr, i, 2)

        pixels = _extract_trainer_pic(pyboy, trainer_bank, trainer_addr)
        _save_trainer_pic(pixels, palette, out_path=out_path)


def _read_mini_palette(pyboy, pokemon_index: int) -> list[tuple[int, int, int, int]]:
    """Read a Pokemon's 4-color GBC palette from ROM.

    Follows Polished Crystal's logic for a plain,
    non-shiny species entry. For plain-form species, the palette table
    index collapses to the base species slot in PokemonPalettes.

    Args:
        pyboy: PyBoy instance with symbols loaded.
        pokemon_index: National Dex number (1-based, e.g. 152 for Chikorita).

    Returns:
        4 RGBA tuples. Index 0 is always transparent (alpha=0).

    """
    pp_bank, pp_addr = pyboy.symbol_lookup("PokemonPalettes")
    pal_base = pp_addr + (pokemon_index) * 8

    colors: list[tuple[int, int, int, int]] = [(255, 255, 255, 255)]  # index 0 = white, index 1 = black
    for i in range(0, 2):
        lo = pyboy.memory[pp_bank, pal_base + (i * 2)]
        hi = pyboy.memory[pp_bank, pal_base + (i * 2) + 1]
        colors.append(gbc_color_to_rgba(lo | (hi << 8)))
    colors.append((0, 0, 0, 255))

    return colors


def _read_palette(pyboy, bank: int, addr: int, index: int, size: int = 4) -> list[tuple[int, int, int, int]]:
    pal_base = addr + index * size * 2

    colors: list[tuple[int, int, int, int]] = [(255, 255, 255, 255)]  # index 0 = white, index 1 = black
    for i in range(0, size):
        lo = pyboy.memory[bank, pal_base + (i * 2)]
        hi = pyboy.memory[bank, pal_base + (i * 2) + 1]
        colors.append(gbc_color_to_rgba(lo | (hi << 8)))
    colors.append((0, 0, 0, 255))

    return colors
    

def _extract_mini_sprite(pyboy, bank: int, addr: int, palette: list[tuple[int, int, int, int]], mask: list[list[int]], out_path: Path) -> None:
    """Read a mini sprite from ROM and save it as a 16×32 RGBA PNG.

    Mini sprites are 16×32 pixels (8 tiles of 8×8), stored as LZ-compressed
    2bpp data. 512 bytes is safely larger than any compressed mini; Decompressed
    self-terminates at 0xFF.
    """
    # 1. Read raw LZ-compressed 2bpp directly from the ROM file.
    # PyBoy's memory API (both slice and individual reads) maps through the
    # emulated address space and may not reliably return data from a specific
    # ROM bank when that bank isn't currently mapped. Reading the file
    # directly is unambiguous: file_offset = bank * 0x4000 + (addr % 0x4000).

    file_offset = bank * 0x4000 + (addr % 0x4000)
    with open(pyboy.gamerom, "rb") as f:
        f.seek(file_offset)
        raw = bytearray(f.read(512))

    raw = bytes(raw)

    # 2. Decompress using the Polished Crystal LZ format.
    decompressed = bytes(Decompressed(raw).output)

    # 3. Pad to tile-aligned size — the encoder omits trailing zero bytes when
    #    the last tile row(s) are fully transparent.
    needed = (16 // 8) * (32 // 8) * 16  # tiles_x * tiles_y * bytes_per_tile
    if len(decompressed) < needed:
        decompressed = decompressed + bytes(needed - len(decompressed))

    # 4. Decode 2bpp → 16×32 pixel index grid
    pixels = decode_2bpp(decompressed, width=16, height=32)

    # 6. Render and save
    img = Image.new("RGBA", (16, 32))
    for y, row in enumerate(pixels):
        for x, idx in enumerate(row):
            color = palette[idx]
            if mask[y][x] == 0:
                color = (color[0], color[1], color[2], 0)
            img.putpixel((x, y), color)
    img.save(str(out_path))


def _extract_mask_sprite(pyboy, bank: int, addr: int) -> None:
    """Read a mini mask sprite from ROM and save it as a 16x32 RGBA PNG."""
    file_offset = bank * 0x4000 + (addr % 0x4000)
    with open(pyboy.gamerom, "rb") as f:
        f.seek(file_offset)
        raw = bytes(f.read(512))

    decompressed = bytes(Decompressed(raw).output)

    needed = (16 // 8) * (32 // 8) * 8  # tiles_x * tiles_y * bytes_per_tile
    if len(decompressed) < needed:
        decompressed = decompressed + bytes(needed - len(decompressed))

    return decode_1bpp(decompressed, width=16, height=32)


def _extract_badge_gfx(pyboy, bank: int, addr: int) -> None:
    """Reads a badge spritesheet from ROM and return its piexls.

    Badges are 16×176 pixels (22 tiles of 8×8), stored as LZ-compressed
    2bpp data. BadgeGFX has 531 bytes and BadgeGFX2 has 447 bytes, so reading 531 is safe; 
    Decompressed self-terminates at 0xFF.
    """

    file_offset = bank * 0x4000 + (addr % 0x4000)
    with open(pyboy.gamerom, "rb") as f:
        f.seek(file_offset)
        raw = bytearray(f.read(531))

    raw = bytes(raw)

    decompressed = bytes(Decompressed(raw).output)

    needed = (16 // 8) * (176 // 8) * 16  # tiles_x * tiles_y * bytes_per_tile
    if len(decompressed) < needed:
        decompressed = decompressed + bytes(needed - len(decompressed))

    return decode_2bpp(decompressed, width=16, height=176)


def _save_badge_sprite(pixels: list[list[int]], palette: list[tuple[int, int, int, int]], badge_index: int, out_path: Path) -> None:
    pixels_cropped = pixels[badge_index * 16 : (badge_index + 1) * 16]
    palette.append((0, 0, 0, 0))
    
    _floodfill_transparency(pixels_cropped)
    
    img = Image.new("RGBA", (16, 16))
    for y, row in enumerate(pixels_cropped):
        for x, idx in enumerate(row):
            color = palette[idx]
            img.putpixel((x, y), color)
    img.save(str(out_path))
    
    
def _floodfill_transparency(pixels: list[list[int]]) -> None:
    """
    Flood-fills white pixels (idx 0) from the corners of the grid to be transparent (idx -1).
    """
    height = len(pixels)
    width = len(pixels[0])
    
    visited = set()
    queue = [
        (0, 0), 
        (0, width >> 1), 
        (0, width - 1), 
        (height >> 1, 0), 
        (height - 1, 0), 
        (height - 1, width >> 1), 
        (height - 1, width - 1),
        (height >> 1, width - 1),
    ]
    
    while queue:
        y, x = queue.pop(0)
        if (y, x) in visited:
            continue
        visited.add((y, x))
        
        if pixels[y][x] == 0:
            pixels[y][x] = -1
            if y > 0:
                queue.append((y - 1, x))
            if y < height - 1:
                queue.append((y + 1, x))
            if x > 0:
                queue.append((y, x - 1))
            if x < width - 1:
                queue.append((y, x + 1))    
    

def _extract_trainer_pic(pyboy, bank: int, addr: int) -> None:
    """Reads a badge spritesheet from ROM and return its piexls.

    Badges are 56×56 pixels (49 tiles of 8×8), stored as LZ-compressed
    2bpp data. Decompressed self-terminates at 0xFF.
    """

    file_offset = bank * 0x4000 + (addr % 0x4000)
    with open(pyboy.gamerom, "rb") as f:
        f.seek(file_offset)
        raw = bytearray(f.read(1024))

    raw = bytes(raw)

    decompressed = bytes(Decompressed(raw).output)

    needed = (56 // 8) * (56 // 8) * 16  # tiles_x * tiles_y * bytes_per_tile
    if len(decompressed) < needed:
        decompressed = decompressed + bytes(needed - len(decompressed))

    return decode_2bpp(decompressed, width=56, height=56, pic=True)


def _save_trainer_pic(pixels: list[list[int]], palette: list[tuple[int, int, int, int]], out_path: Path) -> None:
    palette.append((0, 0, 0, 0))
    
    img = Image.new("RGBA", (56, 56))
    for y, row in enumerate(pixels):
        for x, idx in enumerate(row):
            color = palette[idx]
            img.putpixel((x, y), color)
    img.save(str(out_path))


def render_status_bar(img: Image.Image, data: dict, scale: int) -> None:
    """Draw map/party text on the status bar image in-place.

    Args:
        img: PIL Image already sized for the status bar.
        data: Status bar data dict with map_name and party keys.
        scale: Rendering scale factor.
    """
    if "map_name" not in data or "party" not in data:
        return

    draw = ImageDraw.Draw(img)
    party = data["party"]
    pack = data["pack"]
    johto_badges = data["johto_badges"]
    kanto_badges = data["kanto_badges"]

    if (data["battle"]):
        text = f"VS {data['battle']['opponent']}"
    else:
        text = f"{data['map_name']}"

    font_size = max(8, 8 * scale)
    font = _load_unifont(font_size)

    pad = scale * 4
    height = img.height

    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_h = bbox[3] - bbox[1]
    except Exception:
        text_h = font_size

    y = max(0, (height - text_h) // 2)
    
    draw_text_to_fit(img, draw, pad, y, text, (255, 255, 255), 80 * scale, font)
    
    render_party(img, party, scale)
    render_pack_counts(img, pack, scale)
    render_badges(img, johto_badges, kanto_badges, scale)

    
def render_party(img: Image.Image, party: list[dict], scale: int):
    draw = ImageDraw.Draw(img)

    start_x = 82 * scale
    y = 1 * scale
    
    font_size = max(7, 7 * scale)
    font = _load_unifont(font_size)
        
    held_item_icon = _load_icon("held_item", 4 * scale)

    for i, pokemon in enumerate(party):
        is_egg = pokemon["is_egg"]
        species = 255 if is_egg else pokemon["species"]

        if species == 0:
            continue

        x = start_x + i * (22 * scale)
        asset = load_pokemon_asset(species)

        if asset:
            resized_asset = asset.resize((10 * scale, 10 * scale), resample=Image.Resampling.LANCZOS)
            img.paste(resized_asset, (x + 5 * scale, y), resized_asset)
            
        if is_egg:
            continue
            
        status = _get_status_text(pokemon['status'])
        draw.text((x + 13 * scale, y + 5 * scale), status, fill=(255, 255, 255), font=font, fontmode="1")
        
        hp_percent = pokemon["hp"] / max(pokemon["max_hp"], 1)
        hp_color = (0, 184, 0) if hp_percent > 0.5 else (248, 168, 0) if hp_percent > 0.2 else (248, 0, 0)

        _draw_bar(draw, x + 10 * scale, y + 12 * scale, 9 * scale, 1 * scale, hp_percent, hp_color)
        _draw_bar(draw, x + 10 * scale, y + 14 * scale, 9 * scale, 1 * scale, pokemon["exp_percent"], (32, 136, 248))
        
        level = pokemon['level']
        level_label = f"L{level}" if 9 < level < 100 else f"L0{level}" if level < 10 else "MAX"
        draw.text((x - 1 * scale, y + 8.5 * scale), level_label, fill=(255, 255, 255), font=font, fontmode="1")
        
        if pokemon["item"] > 0:
            img.paste(held_item_icon, (x + 3 * scale, y + 6 * scale), held_item_icon)
            
            
def _draw_bar(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int, percent: float, color: tuple[int, int, int]):
    draw.rectangle([x - 1, y - 1, x + width + 1, y + height + 1], fill=(0, 0, 0))

    if percent > 0:
        draw.rectangle([x, y, x + width * percent, y + height], fill=color)
        
        
def _load_icon(name: str, height_px: int) -> Optional[Image.Image]:
    if (name, height_px) not in _icon_cache:
        path = f"assets/pkpcrystal/{name}.png"
        if not Path(path).exists():
            _icon_cache[(name, height_px)] = None
        else:
            icon = Image.open(path).convert("RGBA")
            aspect = icon.width / icon.height
            new_w = max(1, int(height_px * aspect))
            _icon_cache[(name, height_px)] = icon.resize((new_w, height_px), Image.Resampling.LANCZOS)
    return _icon_cache[(name, height_px)]


def _load_unifont(height_px: int) -> Optional[ImageFont.ImageFont]:
    if height_px not in _unifont_cache:
        path = "assets/fonts/unifont-17.0.04.otf"
        if not Path(path).exists():
            _unifont_cache[height_px] = None
        else:
            try:
                _unifont_cache[height_px] = ImageFont.truetype(str(path), size=height_px)
            except Exception:
                _unifont_cache[height_px] = ImageFont.load_default()
    return _unifont_cache[height_px]


def _load_badge_asset(region: str, badge_id: int) -> Optional["Image.Image"]:
    """Load and cache a badge PNG (RGBA). Returns None if missing."""
    if (region, badge_id) in _badge_asset_cache:
        return _badge_asset_cache[(region, badge_id)]

    asset_path = f"assets/dynamic/pkpcrystal/badges/{region}/{badge_id}.png"
    if not Path(asset_path).exists():
        logger.warning(f"Badge asset not found: {asset_path}")
        _badge_asset_cache[(region, badge_id)] = None
        return None
    img = Image.open(asset_path).crop((0, 0, 16, 16)).convert("RGBA")
    _badge_asset_cache[(region, badge_id)] = img
    return img


def _get_status_text(value: int) -> str:
    if value == 0:
        return ''
    elif value & 0x07:
        return 'SLP'
    elif value & 0x08:
        return 'PSN'
    elif value & 0x10:
        return 'BRN'
    elif value & 0x20:
        return 'FRZ'
    elif value & 0x40:
        return 'PAR'
    elif value & 0x80:
        return 'TOX'
    
    
def render_pack_counts(img: Image.Image, pack: dict, scale: int):
    start_x = 215 * scale
    
    font_size = max(7, 7 * scale)
    font = _load_unifont(font_size)

    icons = {
        "items": _load_icon("pack_items", 5 * scale),
        "meds": _load_icon("pack_meds", 5 * scale),
        "balls": _load_icon("pack_balls", 5 * scale),
        "berries": _load_icon("pack_berries", 5 * scale)
    }
    
    categories = ["items", "meds", "balls", "berries"]
    draw = ImageDraw.Draw(img)
    
    for i, category in enumerate(categories):
        x = start_x + i * (9 * scale)
        y = 1 * scale
        
        icon = icons[category]

        if icon:
            img.paste(icon, (x + (2 * scale), y), icon)
            
        count = pack[f'{category}_count']
        label = str(count)
        
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            text_w = bbox[2] - bbox[0]
        except Exception:
            text_w = font_size

        draw.text((int(x + (4.5 * scale) - (text_w / 2)), y + 7 * scale), label, fill=(255, 255, 255), font=font, fontmode="1")
    

def render_badges(img: Image.Image, johto_badges: int, kanto_badges: int, scale: int):
    start_x = 252 * scale
    
    badges = johto_badges if kanto_badges == 0 else kanto_badges
    region = "johto" if kanto_badges == 0 else "kanto"
    
    for i in range(0, 8):
        x = start_x + (i % 4) * (8 * scale)
        y = (i // 4) * (8 * scale)
        asset = _load_badge_asset(region, i + 1)

        if asset:
            has_badge = (badges >> i) & 1
            resized_asset = asset.resize((8 * scale, 8 * scale), resample=Image.Resampling.LANCZOS)
            blank = Image.new("RGBA", (8 * scale, 8 * scale), (0, 0, 0, 0))
            img.paste(resized_asset if has_badge else blank, (x, y), resized_asset)


def get_status_bar_data(pyboy) -> dict[str, Any]:
    """Read game memory to build status bar data.

    Args:
        pyboy: PyBoy emulator instance (with symbols loaded)

    Returns:
        Dict with map_group, map_number, and party species IDs.
    """
    map_name = _get_map_name(pyboy)
    battle_data = _get_battle_data(pyboy)
    party = []
    party_count = symbol_read_u8(pyboy, "wPartyCount")
    
    for i in range(1, party_count + 1):
        species = symbol_read_u8(pyboy, f"wPartyMon{i}Species")
        
        if species == 0:
            continue
        
        growth_rate = _get_growth_rate(pyboy, species)
        total_exp = symbol_read_u24le(pyboy, f"wPartyMon{i}Exp")
        current_level = _get_level_from_exp(growth_rate, total_exp)
        current_level_exp = EXP_PER_LEVEL[growth_rate][current_level - 1] if current_level > 1 else 0
        next_level_at = EXP_PER_LEVEL[growth_rate][current_level] if current_level < 100 else total_exp
        total_level_exp = next_level_at - current_level_exp
        exp_percent = (total_exp - current_level_exp) / max(total_level_exp, 1)
        
        gender_is_egg_ext_species_form = symbol_read_u8(pyboy, f"wPartyMon{i}ExtSpecies")
        gender = gender_is_egg_ext_species_form & 0b10000000
        is_egg = gender_is_egg_ext_species_form & 0b01000000
        ext_species = gender_is_egg_ext_species_form & 0b00100000
        form = gender_is_egg_ext_species_form & 0b00011111
        # logger.info(f"#{i}: Gender = {gender} | Is egg? {is_egg} | Ext species {ext_species} | Form {form}")

        party.append({
            "species": symbol_read_u8(pyboy, f"wPartyMon{i}Species"),
            "ext_species": ext_species,
            "is_egg": is_egg,
            "gender": gender,
            "form": form,
            "hp": symbol_read_u16le(pyboy, f"wPartyMon{i}HP"),
            "max_hp": symbol_read_u16le(pyboy, f"wPartyMon{i}MaxHP"),
            "item": symbol_read_u8(pyboy, f"wPartyMon{i}Item"),
            "status": symbol_read_u8(pyboy, f"wPartyMon{i}Status"),
            "level": current_level,
            "exp_percent": exp_percent,
        })

    return {
        "map_name": map_name,
        "party": party,
        "johto_badges": symbol_read_u8(pyboy, "wJohtoBadges"),
        "kanto_badges": symbol_read_u8(pyboy, "wKantoBadges"),
        "pack": {
            "items_count": symbol_read_u8(pyboy, "wNumItems"),
            "meds_count": symbol_read_u8(pyboy, "wNumMedicine"),
            "balls_count": symbol_read_u8(pyboy, "wNumBalls"),
            "berries_count": symbol_read_u8(pyboy, "wNumBerries"),
        },
        "battle": battle_data
    }
    
def _get_growth_rate(pyboy, species: int) -> GrowthRate:
    base_data_bank, base_data_addr = pyboy.symbol_lookup("BaseData")
    base_data_width = 0x22
    growth_rate_offset = 0x10
    growth_rate = pyboy.memory[base_data_bank, base_data_addr + (species - 1) * base_data_width + growth_rate_offset]

    return GrowthRate(growth_rate)

def _get_level_from_exp(growth_rate: GrowthRate, total_exp: int) -> int:
    return max(1, bisect.bisect_right(EXP_PER_LEVEL[growth_rate], total_exp))

def _get_map_name(pyboy):
    cur_landmark = symbol_read_u8(pyboy, "wCurLandmark")
    
    if cur_landmark == 255:
        return '???'

    bank, landmarks_base_addr = pyboy.symbol_lookup("Landmarks")
    
    # logger.debug(f"Cur Landmark: {cur_landmark}")
    # logger.debug(f"Landmarks Bank: {bank}")
    # logger.debug(f"Landmarks Base Address: {hex(landmarks_base_addr)}")

    # Landmark structure: x (u8), y (u8), name ptr (u16)
    landmark_name_ptr_addr = landmarks_base_addr + (cur_landmark * 4)
    landmark_name_ptr = read_u16(pyboy, bank, landmark_name_ptr_addr + 2)

    # logger.debug(f"Landmark Name Pointer Address: {hex(landmark_name_ptr_addr)}")
    # logger.debug(f"Landmark Name Pointer: {hex(landmark_name_ptr)}")

    landmark_name = decode_text(pyboy, bank, landmark_name_ptr)
    # logger.debug(f"Landmark Name: {landmark_name}")

    return landmark_name


def _get_battle_data(pyboy):
    mode = symbol_read_u8(pyboy, "wBattleMode")
    # logger.debug(f"Battle Mode: {mode}")
    
    if BattleMode(mode) == BattleMode.WILD:
        temp_enemy_mon_species = symbol_read_u8(pyboy, "wTempEnemyMonSpecies")
        # logger.debug(f"Temp Enemy Mon Species: {temp_enemy_mon_species}")

        pokemon_name = get_pokemon_name(pyboy, temp_enemy_mon_species)
        # logger.debug(f"Pokemon Name: {pokemon_name}")

        return {
            "mode": "wild",
            "opponent": pokemon_name
        }
    
    if BattleMode(mode) == BattleMode.TRAINER:
        other_trainer_class = symbol_read_u8(pyboy, "wOtherTrainerClass")
        other_trainer_id = symbol_read_u8(pyboy, "wOtherTrainerID")
        
        # logger.debug(f"Other Trainer Class: {other_trainer_class}")
        # logger.debug(f"Other Trainer ID: {other_trainer_id}")
        
        groups_bank, groups_base_addr = pyboy.symbol_lookup("TrainerGroups")
        trainer_group_ptr_addr = groups_base_addr + ((other_trainer_class - 1) * 3)

        # logger.debug(f"Trainer Group Pointer Addr: {hex(groups_bank)}:{hex(trainer_group_ptr_addr)}")

        trainer_group_bank = read_u8(pyboy, groups_bank, trainer_group_ptr_addr)
        trainer_group_ptr = read_u16(pyboy, groups_bank, trainer_group_ptr_addr + 1)

        # logger.debug(f"Trainer Group: {hex(trainer_group_bank)}:{hex(trainer_group_ptr)}")
        
        trainer_id_ptr = trainer_group_ptr
        i = other_trainer_id
        
        while i > 1:
            # Skip this trainer's length (given by the first byte) + 1 (the length byte itself)
            trainer_data_length = read_u8(pyboy, trainer_group_bank, trainer_id_ptr)
            trainer_id_ptr += trainer_data_length + 1

            i -= 1
        
        # logger.debug(f"Trainer ID Pointer: {hex(trainer_group_bank)}:{hex(trainer_id_ptr)}")

        trainer_name = decode_text(pyboy, trainer_group_bank, trainer_id_ptr + 1)
        # logger.debug(f"Trainer Name: {trainer_name}")
        
        trainer_class_names_bank, trainer_class_names_base_addr = pyboy.symbol_lookup("TrainerClassNames")
        trainer_class_name_addr = get_nth_string_addr(pyboy, trainer_class_names_bank, trainer_class_names_base_addr, other_trainer_class - 1)
        trainer_class_name = decode_text(pyboy, trainer_class_names_bank, trainer_class_name_addr)

        # logger.debug(f"Trainer Class Name Addr: {hex(trainer_class_name_addr)}")
        # logger.debug(f"Trainer Class Name: {trainer_class_name}")

        return {
            "mode": "trainer",
            "opponent": f"{trainer_class_name} {trainer_name}"
        }

    return None
