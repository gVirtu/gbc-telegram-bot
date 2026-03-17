"""Tests for Discord sequence modal mapping and parsing."""
import os
import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from src.models.game_state import GameButton


class TestSequenceMappings:

    def test_all_four_mapping_keys_present(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        assert "ULDR AB ST" in SEQUENCE_MAPPINGS
        assert "WASD ZX CV" in SEQUENCE_MAPPINGS
        assert "IJKL NM UO" in SEQUENCE_MAPPINGS
        assert "8426 13 79" in SEQUENCE_MAPPINGS

    def test_each_mapping_has_exactly_eight_entries(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        for key, mapping in SEQUENCE_MAPPINGS.items():
            assert len(mapping) == 8, f"{key} should map 8 characters"

    def test_each_mapping_covers_all_eight_buttons(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        required = {GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT,
                    GameButton.A, GameButton.B, GameButton.START, GameButton.SELECT}
        for key, mapping in SEQUENCE_MAPPINGS.items():
            assert set(mapping.values()) == required, f"{key} missing buttons"

    def test_uldr_mapping_chars(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        m = SEQUENCE_MAPPINGS["ULDR AB ST"]
        assert m["U"] == GameButton.UP
        assert m["L"] == GameButton.LEFT
        assert m["D"] == GameButton.DOWN
        assert m["R"] == GameButton.RIGHT
        assert m["A"] == GameButton.A
        assert m["B"] == GameButton.B
        assert m["S"] == GameButton.START
        assert m["T"] == GameButton.SELECT

    def test_wasd_mapping_chars(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        m = SEQUENCE_MAPPINGS["WASD ZX CV"]
        assert m["W"] == GameButton.UP
        assert m["A"] == GameButton.LEFT
        assert m["S"] == GameButton.DOWN
        assert m["D"] == GameButton.RIGHT
        assert m["Z"] == GameButton.A
        assert m["X"] == GameButton.B
        assert m["C"] == GameButton.START
        assert m["V"] == GameButton.SELECT

    def test_ijkl_mapping_chars(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        m = SEQUENCE_MAPPINGS["IJKL NM UO"]
        assert m["I"] == GameButton.UP
        assert m["J"] == GameButton.LEFT
        assert m["K"] == GameButton.DOWN
        assert m["L"] == GameButton.RIGHT
        assert m["N"] == GameButton.A
        assert m["M"] == GameButton.B
        assert m["U"] == GameButton.START
        assert m["O"] == GameButton.SELECT

    def test_numpad_mapping_chars(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        m = SEQUENCE_MAPPINGS["8426 13 79"]
        assert m["8"] == GameButton.UP
        assert m["4"] == GameButton.LEFT
        assert m["2"] == GameButton.DOWN
        assert m["6"] == GameButton.RIGHT
        assert m["1"] == GameButton.A
        assert m["3"] == GameButton.B
        assert m["7"] == GameButton.START
        assert m["9"] == GameButton.SELECT


class TestParseSequence:

    def test_valid_uppercase_sequence(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("ULDR", "ULDR AB ST")
        assert buttons == [GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT]
        assert invalid == []

    def test_valid_lowercase_sequence_case_insensitive(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("uldr", "ULDR AB ST")
        assert buttons == [GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT]
        assert invalid == []

    def test_mixed_case(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("uLdR", "ULDR AB ST")
        assert buttons == [GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT]
        assert invalid == []

    def test_invalid_char_reported(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("UXY", "ULDR AB ST")
        assert buttons == [GameButton.UP]
        assert "X" in invalid
        assert "Y" in invalid

    def test_invalid_chars_deduplicated(self):
        from src.adapters.discord import parse_sequence
        _, invalid = parse_sequence("UXX", "ULDR AB ST")
        assert invalid.count("X") == 1

    def test_wasd_mapping(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("wasd", "WASD ZX CV")
        assert buttons == [GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT]
        assert invalid == []

    def test_numpad_mapping(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("8426", "8426 13 79")
        assert buttons == [GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT]
        assert invalid == []

    def test_unknown_mapping_key_falls_back_to_uldr(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("U", "UNKNOWN_KEY")
        assert buttons == [GameButton.UP]

    def test_empty_sequence(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("", "ULDR AB ST")
        assert buttons == []
        assert invalid == []

    def test_custom_id_is_not_valid_button_callback(self):
        """open_sequence_modal must not match is_valid_button_callback."""
        from src.keyboard import is_valid_button_callback
        assert not is_valid_button_callback("open_sequence_modal"), (
            "open_sequence_modal must never match a GameButton value or modifier_ prefix"
        )


class TestDiscordGameViewSequenceButton:

    def test_sequence_button_present_in_view_without_modifiers(self):
        """View built without modifiers must contain an open_sequence_modal button."""
        from src.adapters.discord import DiscordGameView
        view = DiscordGameView.build(chat_config=None, modifier_specs=None)
        custom_ids = [item.custom_id for item in view.children]
        assert "open_sequence_modal" in custom_ids

    def test_sequence_button_present_in_view_with_modifiers(self):
        """View built with modifiers must still contain the sequence button."""
        from src.adapters.discord import DiscordGameView
        from src.models.game_state import ModifierButtonSpec, ChatConfig, GameButton
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT],
            inactive_label_key="keyboard.modifier.run.inactive",
            active_label_key="keyboard.modifier.run.active",
        )
        config = ChatConfig(chat_id=1)
        view = DiscordGameView.build(chat_config=config, modifier_specs=[spec])
        custom_ids = [item.custom_id for item in view.children]
        assert "open_sequence_modal" in custom_ids

    def test_sequence_button_on_correct_row_without_modifiers(self):
        """Without modifiers, sequence button must be on row 3 (after 3 game rows 0-2)."""
        from src.adapters.discord import DiscordGameView
        view = DiscordGameView.build(chat_config=None, modifier_specs=None)
        seq_btn = next(item for item in view.children if item.custom_id == "open_sequence_modal")
        assert seq_btn.row == 3

    def test_sequence_button_on_correct_row_with_modifiers(self):
        """With modifiers on row 3, sequence button must be on row 4."""
        from src.adapters.discord import DiscordGameView
        from src.models.game_state import ModifierButtonSpec, ChatConfig, GameButton
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT],
            inactive_label_key="keyboard.modifier.run.inactive",
            active_label_key="keyboard.modifier.run.active",
        )
        config = ChatConfig(chat_id=1)
        view = DiscordGameView.build(chat_config=config, modifier_specs=[spec])
        seq_btn = next(item for item in view.children if item.custom_id == "open_sequence_modal")
        assert seq_btn.row == 4

    def test_sequence_button_style_is_primary(self):
        """Sequence button must use primary (blue) style."""
        import discord
        from src.adapters.discord import DiscordGameView
        view = DiscordGameView.build(chat_config=None, modifier_specs=None)
        seq_btn = next(item for item in view.children if item.custom_id == "open_sequence_modal")
        assert seq_btn.style == discord.ButtonStyle.primary
