"""Status bar data provider for Polished Crystal (PKPCRYSTAL)."""

from typing import Any


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