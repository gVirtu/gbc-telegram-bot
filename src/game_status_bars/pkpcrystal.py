"""Status bar data provider for Polished Crystal (PKPCRYSTAL)."""

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


def render_status_bar(img: Image.Image, data: dict, scale: int) -> None:
    """Draw map/party text on the status bar image in-place.

    Args:
        img: PIL Image already sized for the status bar.
        data: Status bar data dict with map_group, map_number, and party keys.
        scale: Rendering scale factor.
    """
    if "map_group" not in data or "map_number" not in data or "party" not in data:
        return

    from PIL import ImageFont

    draw = ImageDraw.Draw(img)
    party = data["party"]
    party_str = " ".join(str(s) for s in party)
    text = f"Map: {data['map_group']}/{data['map_number']}   Party: {party_str}"

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
    return {
        "map_group": _read_byte(pyboy, "wMapGroup"),
        "map_number": _read_byte(pyboy, "wMapNumber"),
        "party": [
            _read_byte(pyboy, "wPartyMon1Species"),
            _read_byte(pyboy, "wPartyMon2Species"),
            _read_byte(pyboy, "wPartyMon3Species"),
            _read_byte(pyboy, "wPartyMon4Species"),
            _read_byte(pyboy, "wPartyMon5Species"),
            _read_byte(pyboy, "wPartyMon6Species"),
        ],
    }

def _read_byte(pyboy, symbol: str) -> int:
    return pyboy.memory[pyboy.symbol_lookup(symbol)]