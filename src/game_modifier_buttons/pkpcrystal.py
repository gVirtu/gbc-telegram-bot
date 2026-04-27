"""Modifier buttons for Polished Crystal (PKPCRYSTAL).

Provides game-specific modifier buttons:
- run: Holds B during directional inputs for running
"""

from src.game import game_controller_manager
from src.models.game_state import GameButton, ModifierButtonSpec
from src.game_utils.pkpcrystal.reader import symbol_read_u8
from src.game_utils.pkpcrystal.enum import BattleMode


def _run_condition(controller) -> bool:
    """Disable B button from running if in a battle."""
    pyboy = controller.pyboy
    mode = symbol_read_u8(pyboy, "wBattleMode")

    return BattleMode(mode) == BattleMode.NONE

MODIFIER_BUTTONS = [
    ModifierButtonSpec(
        key="run",
        modifier_button=GameButton.B,
        applies_to=[GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT],
        active_label_key="keyboard.buttons.running",
        inactive_label_key="keyboard.buttons.walking",
        condition=_run_condition,
    )
]
