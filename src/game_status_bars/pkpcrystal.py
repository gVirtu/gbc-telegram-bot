"""Status bar data provider for Polished Crystal (PKPCRYSTAL)."""

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from src.utils.lz import Decompressed
from src.utils.gbc_graphics import decode_2bpp, read_mini_palette


def init(pyboy) -> None:
    """Extract ROM assets once at startup. Skips if already done."""
    out = Path("assets/dynamic/pkpcrystal/minis/151.png")
    if out.exists():
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    _extract_mini_sprite(pyboy, "ChikoritaMini", pokemon_index=152, out_path=out)


def _extract_mini_sprite(pyboy, symbol: str, pokemon_index: int, out_path: Path) -> None:
    """Read a mini sprite from ROM and save it as a 16×32 RGBA PNG.

    Mini sprites are 16×32 pixels (8 tiles of 8×8), stored as LZ-compressed
    2bpp data. 512 bytes is safely larger than any compressed mini; Decompressed
    self-terminates at 0xFF.
    """
    # 1. Read raw LZ-compressed 2bpp from ROM byte-by-byte.
    # Slice reads (memory[bank, addr:addr+N]) don't reliably respect the bank
    # parameter in all PyBoy versions — individual reads do.
    bank, addr = pyboy.symbol_lookup(symbol)
    raw = bytes(pyboy.memory[bank, addr + i] for i in range(512))

    # 2. Decompress (Crystal LZ — Decompressed is the decompressor, not Compressed)
    decompressed = bytes(Decompressed(raw).output)

    # 3. Decode 2bpp → 16×32 pixel index grid
    pixels = decode_2bpp(decompressed, width=16, height=32)

    # 4. Read 4-color GBC palette from ROM
    palette = read_mini_palette(pyboy, pokemon_index)

    # 5. Render and save
    img = Image.new("RGBA", (16, 32))
    for y, row in enumerate(pixels):
        for x, idx in enumerate(row):
            img.putpixel((x, y), palette[idx])
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

    from PIL import ImageFont

    draw = ImageDraw.Draw(img)
    party = data["party"]
    party_str = " ".join(str(s) for s in party)
    text = f"@ {data['map_name']}   Party: {party_str}"

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


def get_status_bar_data(pyboy) -> dict[str, Any]:
    """Read game memory to build status bar data.

    Args:
        pyboy: PyBoy emulator instance (with symbols loaded)

    Returns:
        Dict with map_group, map_number, and party species IDs.
    """
    map_name = _get_map_name(pyboy)
    return {
        "map_name": map_name,
        "party": [
            _symbol_read_u8(pyboy, "wPartyMon1Species"),
            _symbol_read_u8(pyboy, "wPartyMon2Species"),
            _symbol_read_u8(pyboy, "wPartyMon3Species"),
            _symbol_read_u8(pyboy, "wPartyMon4Species"),
            _symbol_read_u8(pyboy, "wPartyMon5Species"),
            _symbol_read_u8(pyboy, "wPartyMon6Species"),
        ],
    }

def _get_map_name(pyboy):
    cur_landmark = _symbol_read_u8(pyboy, "wCurLandmark")
    
    if cur_landmark == 255:
        return 'N/A'

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

def _read_u16(pyboy, bank, addr):
    [lo, hi] = pyboy.memory[bank, addr:addr+2]
    return lo | (hi << 8)

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