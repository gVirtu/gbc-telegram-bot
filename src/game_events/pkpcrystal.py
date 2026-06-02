"""Event specs for Polished Crystal (PKPCRYSTAL).

Each entry maps an event_key to an EventSpec. Specs with an ``addr``
get a pyboy hook registered automatically by the hooks module; specs
without one are score-only definitions.

Condition functions receive the GameController and should return True
for the event to be appended. They may access ``controller.pyboy`` to
read game memory.
"""

from src.models.game_state import EventSpec
from src.game_utils.pkpcrystal.reader import symbol_read_u8

SHINY_MASK = 0x80  # bit 7 of the personality byte

GAME_EVENTS: dict[str, EventSpec] = {
    "wild_battle_start": EventSpec(
        title="Wild Battle Started",
        score=5,
        addr="DoBattle.wild",
        condition=lambda c: symbol_read_u8(c.pyboy, "wBattleMode") == 1,
    ),
    "trainer_pokemon_defeated": EventSpec(
        title="Trainer Pokémon Defeated",
        score=15,
        addr="EnemyMonFaintedAnimation",
        condition=lambda c: symbol_read_u8(c.pyboy, "wBattleMode") == 2,
    ),
    "trainer_battle_win": EventSpec(
        title="Trainer Battle Won",
        score=50,
        addr="WinTrainerBattle",
    ),
    "gym_badge_get": EventSpec(
        title="Gym Badge Earned",
        score=1000,
        addr="Script_givebadge",
    ),
    "hall_of_fame": EventSpec(
        title="Entered Hall of Fame",
        score=2500,
        addr="HallOfFame",
    ),
    "party_level_up": EventSpec(
        title="Party Lv. Up",
        score=25,
        addr="LearnLevelMoves",
    ),
    "party_evolved": EventSpec(
        title="Party Pokémon Evolved",
        score=250,
        addr="LearnEvolutionMove",
    ),
    "wild_caught": EventSpec(
        title="Wild Pokémon Caught",
        score=50,
        addr="PokeBallEffect.caught",
    ),
    "wild_defeated": EventSpec(
        title="Wild Pokémon Defeated",
        score=5,
        addr="EnemyMonFaintedAnimation",
        condition=lambda c: symbol_read_u8(c.pyboy, "wBattleMode") == 1,
    ),
    "key_item_added": EventSpec(
        title="Key Item Acquired",
        score=500,
        addr="ReceiveKeyItem",
    ),
    "regular_item_added": EventSpec(
        title="Item Acquired",
        score=20,
        addr="ReceiveItem",
    ),
    "wild_shiny_sparkle": EventSpec(
        title="Shiny!!!",
        score=4096,
        addr="BattleStartMessage",
        condition=lambda c: symbol_read_u8(c.pyboy, "wBattleMode") == 1
        and (symbol_read_u8(c.pyboy, "wEnemyMonShiny") & SHINY_MASK) != 0,
    ),
}
