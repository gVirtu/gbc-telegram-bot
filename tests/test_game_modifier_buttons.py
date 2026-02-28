"""Tests for game modifier button modules."""

import pytest
from src.models.game_state import GameButton, ModifierButtonSpec


class TestPkpcrystalModifierButtons:
    """Test Polished Crystal modifier button specs."""

    def test_module_exports_modifier_buttons(self):
        """Test that pkpcrystal module exports MODIFIER_BUTTONS list."""
        from src.game_modifier_buttons import pkpcrystal
        assert hasattr(pkpcrystal, "MODIFIER_BUTTONS")
        assert isinstance(pkpcrystal.MODIFIER_BUTTONS, list)

    def test_run_modifier_spec_present(self):
        """Test that the run modifier spec is present."""
        from src.game_modifier_buttons import pkpcrystal
        keys = [spec.key for spec in pkpcrystal.MODIFIER_BUTTONS]
        assert "run" in keys

    def test_run_modifier_spec_structure(self):
        """Test the run modifier spec has correct structure."""
        from src.game_modifier_buttons import pkpcrystal
        spec = next(s for s in pkpcrystal.MODIFIER_BUTTONS if s.key == "run")
        assert isinstance(spec, ModifierButtonSpec)
        assert spec.modifier_button == GameButton.B
        assert GameButton.UP in spec.applies_to
        assert GameButton.DOWN in spec.applies_to
        assert GameButton.LEFT in spec.applies_to
        assert GameButton.RIGHT in spec.applies_to
        assert spec.active_label_key == "keyboard.buttons.running"
        assert spec.inactive_label_key == "keyboard.buttons.walking"

    def test_non_directional_not_in_applies_to(self):
        """Test that non-directional buttons are not in applies_to."""
        from src.game_modifier_buttons import pkpcrystal
        spec = next(s for s in pkpcrystal.MODIFIER_BUTTONS if s.key == "run")
        assert GameButton.A not in spec.applies_to
        assert GameButton.B not in spec.applies_to
        assert GameButton.START not in spec.applies_to
