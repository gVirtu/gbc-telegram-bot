"""Modifier buttons for Polished Crystal (PKPCRYSTAL).

Provides game-specific modifier buttons:
- run: Holds B during directional inputs for running
"""

from src.models.game_state import GameButton, ModifierButtonSpec

MODIFIER_BUTTONS = [
    ModifierButtonSpec(
        key="run",
        modifier_button=GameButton.B,
        applies_to=[GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT],
        active_label_key="keyboard.buttons.running",
        inactive_label_key="keyboard.buttons.walking",
    )
]
