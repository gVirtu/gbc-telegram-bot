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
        title="Wild Battle!",
        score=5,
        addr="DoBattle.wild",
        condition=lambda c: symbol_read_u8(c.pyboy, "wBattleMode") == 1,
    ),
    "trainer_pokemon_defeated": EventSpec(
        title="Trainer Pkmn Defeated!",
        score=15,
        addr="EnemyMonFaintedAnimation",
        condition=lambda c: symbol_read_u8(c.pyboy, "wBattleMode") == 2,
    ),
    "trainer_battle_win": EventSpec(
        title="Won Trainer Battle!",
        score=50,
        addr="WinTrainerBattle",
    ),
    "gym_badge_get": EventSpec(
        title="Gym Badge Earned!",
        score=1000,
        addr="Script_givebadge",
    ),
    "hall_of_fame": EventSpec(
        title="Entered Hall of Fame!!",
        score=2500,
        addr="HallOfFame",
    ),
    "party_level_up": EventSpec(
        title="Party Lv. Up!",
        score=50,
        addr="LearnLevelMoves",
        condition=lambda c: symbol_read_u8(c.pyboy, "wMonTriedToEvolve") == 0,
    ),
    "party_evolved": EventSpec(
        title="Party Pkmn Evolved!",
        score=250,
        addr="LearnEvolutionMove",
    ),
    "wild_caught": EventSpec(
        title="Wild Pkmn Caught!",
        score=50,
        addr="PokeBallEffect.caught",
    ),
    "wild_defeated": EventSpec(
        title="Wild Pkmn Defeated!",
        score=5,
        addr="EnemyMonFaintedAnimation",
        condition=lambda c: symbol_read_u8(c.pyboy, "wBattleMode") == 1,
    ),
    "key_item_added": EventSpec(
        title="Got Key Item!",
        score=500,
        addr="ReceiveKeyItem",
    ),
    "tmhm_item_added": EventSpec(
        title="Got TM/HM!",
        score=250,
        addr="ReceiveTMHM",
    ),
    "battle_item_added": EventSpec(
        title="Got Battle Item!",
        score=25,
        addr="ReceiveBattleItem",
    ),
    "regular_item_added": EventSpec(
        title="Got Item!",
        score=25,
        addr="ReceiveItem",
    ),
    "wild_shiny_sparkle": EventSpec(
        title="SHINY?!",
        score=4096,
        addr="BattleStartMessage",
        condition=lambda c: symbol_read_u8(c.pyboy, "wBattleMode") == 1
        and (symbol_read_u8(c.pyboy, "wEnemyMonShiny") & SHINY_MASK) != 0,
    ),
}
