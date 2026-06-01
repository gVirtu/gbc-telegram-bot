"""Event specs for Polished Crystal (PKPCRYSTAL)."""

from src.models.game_state import EventSpec

GAME_EVENTS: dict[str, EventSpec] = {
    "wild_battle_start": EventSpec(
        title="Wild Battle Started",
        score=50,
    ),
}

