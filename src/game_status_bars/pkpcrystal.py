"""Status bar data provider for Polished Crystal (PKPCRYSTAL)."""

from pathlib import Path
from typing import Any, Optional
from enum import Enum
import math
import bisect

from PIL import Image, ImageDraw, ImageFont

from src.utils.lz import Decompressed
from src.utils.gbc_graphics import decode_1bpp, decode_2bpp, read_mini_palette

_pokemon_icon_asset_cache: dict[int, Optional["Image.Image"]] = {}
_held_item_icon_cache: dict[int, Optional[Image.Image]] = {}


class GrowthRate(Enum):
    MEDIUM_FAST = 0
    MEDIUM_SLOW = 1
    FAST = 2
    SLOW = 3

EXP_PER_LEVEL = {
    GrowthRate.MEDIUM_FAST: [math.floor(n**3) for n in range(1, 101)],
    GrowthRate.MEDIUM_SLOW: [(math.floor(((6/5) * (n**3)) - (15 * (n**2)) + (100 * n) - 140)) for n in range(1, 101)],
    GrowthRate.FAST: [math.floor((4 * (n**3)) / 5) for n in range(1, 101)],
    GrowthRate.SLOW: [math.floor((5 * (n**3)) / 4) for n in range(1, 101)],
}


def init(pyboy) -> None:
    """Extract ROM assets once at startup. Skips if already done."""
    out_dir = Path("assets/dynamic/pkpcrystal/minis")
    out_dir.mkdir(parents=True, exist_ok=True)

    ptrs_bank, ptrs_base_addr = pyboy.symbol_lookup("MiniIconPointers")
    for i in range(0, 393):
        base_addr = ptrs_base_addr + (i * 7)
        mini_bank = pyboy.memory[ptrs_bank, base_addr]
        mini_addr = _read_u16(pyboy, ptrs_bank, base_addr + 1)
        mini_mask_addr = _read_u16(pyboy, ptrs_bank, base_addr + 3)

        palette = read_mini_palette(pyboy, i + 1)

        out_path = out_dir / f"{i + 1}.png"
        # if out_path.exists():
        #     continue

        mask = _extract_mask_sprite(pyboy, mini_bank, mini_mask_addr)
        _extract_mini_sprite(pyboy, mini_bank, mini_addr, palette, mask, out_path=out_path)


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

    # img = Image.new("RGBA", (16, 32))
    # for y, row in enumerate(pixels):
    #     for x, idx in enumerate(row):
    #         img.putpixel((x, y), palette[idx])
    # img.save(str(out_path))


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

    text = f"{data['map_name']}"

    font_size = max(8, 8 * scale)
    font_path = Path(__file__).parent.parent.parent / "assets" / "fonts" / "unifont-17.0.04.otf"
    try:
        font = ImageFont.truetype(str(font_path), size=font_size)
    except Exception:
        font = ImageFont.load_default()

    pad = scale * 4
    height = img.height
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_h = bbox[3] - bbox[1]
    except Exception:
        text_h = font_size
    y = max(0, (height - text_h) // 2)
    draw.text((pad, y), text, fill=(255, 255, 255), font=font, fontmode="1")
    
    render_party(img, party, scale)

    
def render_party(img: Image.Image, party: list[dict], scale: int):
    draw = ImageDraw.Draw(img)

    start_x = 82 * scale
    y = 1 * scale
    
    font_size = max(5, 5 * scale)
    font_path = Path(__file__).parent.parent.parent / "assets" / "fonts" / "unifont-17.0.04.otf"
    try:
        font = ImageFont.truetype(str(font_path), size=font_size)
    except Exception:
        font = ImageFont.load_default()
        
    held_item_icon = _load_held_item_icon(4 * scale)

    for i, pokemon in enumerate(party):
        species = pokemon["species"]
        if species == 0:
            continue

        x = start_x + i * (22 * scale)
        asset = _load_pokemon_asset(species)

        if asset:
            resized_asset = asset.resize((10 * scale, 10 * scale), resample=Image.Resampling.LANCZOS)
            img.paste(resized_asset, (x + 5 * scale, y), resized_asset)
            
        level = pokemon['level']
        level_label = f"L{level}" if 9 < level < 100 else f"L0{level}" if level < 10 else "MAX"
        draw.text((x, y + 10 * scale), level_label, fill=(255, 255, 255), font=font, fontmode="1")
        
        status = _get_status_text(pokemon['status'])
        draw.text((x + 13 * scale, y + 6 * scale), status, fill=(255, 255, 255), font=font, fontmode="1")
        
        hp_percent = pokemon["hp"] / max(pokemon["max_hp"], 1)
        hp_color = (0, 184, 0) if hp_percent > 0.5 else (248, 168, 0) if hp_percent > 0.2 else (248, 0, 0)

        _draw_bar(draw, x + 9 * scale, y + 12 * scale, 10 * scale, 1 * scale, hp_percent, hp_color)
        _draw_bar(draw, x + 9 * scale, y + 14 * scale, 10 * scale, 1 * scale, pokemon["exp_percent"], (32, 136, 248))
        
        if pokemon["item"] > 0:
            img.paste(held_item_icon, (x, y + 6 * scale), held_item_icon)
            
            
def _draw_bar(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int, percent: float, color: tuple[int, int, int]):
    draw.rectangle([x - 1, y - 1, x + width + 1, y + height + 1], fill=(0, 0, 0))

    if percent > 0:
        draw.rectangle([x, y, x + width * percent, y + height], fill=color)
        
        
def _load_held_item_icon(height_px: int) -> Optional[Image.Image]:
    if height_px not in _held_item_icon_cache:
        path = f"assets/pkpcrystal/held_item.png"
        if not Path(path).exists():
            _held_item_icon_cache[height_px] = None
        else:
            icon = Image.open(path).convert("RGBA")
            aspect = icon.width / icon.height
            new_w = max(1, int(height_px * aspect))
            _held_item_icon_cache[height_px] = icon.resize((new_w, height_px), Image.Resampling.LANCZOS)
    return _held_item_icon_cache[height_px]


def _load_pokemon_asset(species_id: int) -> Optional["Image.Image"]:
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


def get_status_bar_data(pyboy) -> dict[str, Any]:
    """Read game memory to build status bar data.

    Args:
        pyboy: PyBoy emulator instance (with symbols loaded)

    Returns:
        Dict with map_group, map_number, and party species IDs.
    """
    map_name = _get_map_name(pyboy)
    party = []
    
    for i in range(1, 7):
        species = _symbol_read_u8(pyboy, f"wPartyMon{i}Species")
        
        if species == 0:
            continue
        
        growth_rate = _get_growth_rate(pyboy, species)
        total_exp = _symbol_read_u24le(pyboy, f"wPartyMon{i}Exp")
        current_level = _get_level_from_exp(growth_rate, total_exp)
        current_level_exp = EXP_PER_LEVEL[growth_rate][current_level - 1] if current_level > 1 else 0
        next_level_at = EXP_PER_LEVEL[growth_rate][current_level] if current_level < 100 else total_exp
        total_level_exp = next_level_at - current_level_exp
        exp_percent = (total_exp - current_level_exp) / max(total_level_exp, 1)

        party.append({
            "species": _symbol_read_u8(pyboy, f"wPartyMon{i}Species"),
            "ext_species": _symbol_read_u8(pyboy, f"wPartyMon{i}ExtSpecies"),
            "hp": _symbol_read_u16le(pyboy, f"wPartyMon{i}HP"),
            "max_hp": _symbol_read_u16le(pyboy, f"wPartyMon{i}MaxHP"),
            "item": _symbol_read_u8(pyboy, f"wPartyMon{i}Item"),
            "status": _symbol_read_u8(pyboy, f"wPartyMon{i}Status"),
            "level": current_level,
            "exp_percent": exp_percent,
        })

    return {
        "map_name": map_name,
        "party": party
    }
    
def _get_growth_rate(pyboy, species: int) -> GrowthRate:
    base_data_bank, base_data_addr = pyboy.symbol_lookup("BaseData")
    base_data_width = 0x22
    growth_rate_offset = 0x10
    growth_rate = pyboy.memory[base_data_bank, base_data_addr + (species - 1) * base_data_width + growth_rate_offset]

    return GrowthRate(growth_rate)

def _get_level_from_exp(growth_rate: GrowthRate, total_exp: int) -> int:
    return bisect.bisect_right(EXP_PER_LEVEL[growth_rate], total_exp)

def _get_map_name(pyboy):
    cur_landmark = _symbol_read_u8(pyboy, "wCurLandmark")
    
    if cur_landmark == 255:
        return '???'

    bank, landmarks_base_addr = pyboy.symbol_lookup("Landmarks")
    
    # logger.debug(f"Cur Landmark: {cur_landmark}")
    # logger.debug(f"Landmarks Bank: {bank}")
    # logger.debug(f"Landmarks Base Address: {hex(landmarks_base_addr)}")

    # Landmark structure: x (u8), y (u8), name ptr (u16)
    landmark_name_ptr_addr = landmarks_base_addr + (cur_landmark * 4)
    landmark_name_ptr = _read_u16(pyboy, bank, landmark_name_ptr_addr + 2)

    # logger.debug(f"Landmark Name Pointer Address: {hex(landmark_name_ptr_addr)}")
    # logger.debug(f"Landmark Name Pointer: {hex(landmark_name_ptr)}")

    landmark_name = _decode_text(pyboy, bank, landmark_name_ptr)
    # logger.debug(f"Landmark Name: {landmark_name}")

    return landmark_name

def _symbol_read_u8(pyboy, symbol: str) -> int:
    return pyboy.memory[pyboy.symbol_lookup(symbol)]

def _symbol_read_u16le(pyboy, symbol: str) -> int:
    bank, addr = pyboy.symbol_lookup(symbol)
    return _read_u16le(pyboy, bank, addr)

def _symbol_read_u24le(pyboy, symbol: str) -> int:
    bank, addr = pyboy.symbol_lookup(symbol)
    return _read_u24le(pyboy, bank, addr)

def _read_u16(pyboy, bank, addr):
    [lo, hi] = pyboy.memory[bank, addr:addr+2]
    return lo | (hi << 8)

def _read_u16le(pyboy, bank, addr):
    [hi, lo] = pyboy.memory[bank, addr:addr+2]
    return lo | (hi << 8)

def _read_u24le(pyboy, bank, addr):
    [hi, mi, lo] = pyboy.memory[bank, addr:addr+3]
    return lo | (mi << 8) | (hi << 16)

def _decode_text(pyboy, bank, addr):
    text = []
    while True:
        c = pyboy.memory[(bank, addr)]

        if c == 0x53:  # @ string terminator
            break

        text.append(CHARMAP.get(c, " "))
        addr += 1
    return "".join(text)

CHARMAP = {
    0x80: "A",
    0x81: "B",
    0x82: "C",
    0x83: "D",
    0x84: "E",
    0x85: "F",
    0x86: "G",
    0x87: "H",
    0x88: "I",
    0x89: "J",
    0x8a: "K",
    0x8b: "L",
    0x8c: "M",
    0x8d: "N",
    0x8e: "O",
    0x8f: "P",
    0x90: "Q",
    0x91: "R",
    0x92: "S",
    0x93: "T",
    0x94: "U",
    0x95: "V",
    0x96: "W",
    0x97: "X",
    0x98: "Y",
    0x99: "Z",
    0x9a: "(",
    0x9b: ")",
    0x9c: ".",
    0x9d: ",",
    0x9e: "?",
    0x9f: "!",
    0xa0: "a",
    0xa1: "b",
    0xa2: "c",
    0xa3: "d",
    0xa4: "e",
    0xa5: "f",
    0xa6: "g",
    0xa7: "h",
    0xa8: "i",
    0xa9: "j",
    0xaa: "k",
    0xab: "l",
    0xac: "m",
    0xad: "n",
    0xae: "o",
    0xaf: "p",
    0xb0: "q",
    0xb1: "r",
    0xb2: "s",
    0xb3: "t",
    0xb4: "u",
    0xb5: "v",
    0xb6: "w",
    0xb7: "x",
    0xb8: "y",
    0xb9: "z",
    0xba: "“",
    0xbb: "”",
    0xbc: "-",
    0xbd: ":",
    0xbe: "♂",
    0xbf: "♀",
    0xc0: "'",
    0xc1: "'d",
    0xc2: "'l",
    0xc3: "'m",
    0xc4: "'r",
    0xc5: "'s",
    0xc6: "'t",
    0xc7: "'v",
    0xc8: "é",
    0xc9: "É",
    0xca: "á",
    0xcb: "𝐇",
    0xcc: "í",
    0xcd: "ó",
    0xce: "¿",
    0xcf: "¡",
    0xd0: "Po",
    0xd1: "ké",
    0xd2: "Pk",
    0xd3: "Mn",
    0xd4: "ID",
    0xd5: "№",
    0xd6: "Lv.",
    0xd7: "𝐏",
    0xd8: "&",
    0xd9: "♪",
    0xda: "♥",
    0xdb: "×",
    0xdc: "/",
    0xdd: "%",
    0xde: "+",
    0xdf: "<SHARP>",
    0xe0: "0",
    0xe1: "1",
    0xe2: "2",
    0xe3: "3",
    0xe4: "4",
    0xe5: "5",
    0xe6: "6",
    0xe7: "7",
    0xe8: "8",
    0xe9: "9",
    0xea: "¥",
    0xeb: "…",
    0xec: "★",
    0xed: "▼",
    0xee: "▲",
    0xef: "◀",
    0xf0: "▶",
    0xf1: "▷",
}
