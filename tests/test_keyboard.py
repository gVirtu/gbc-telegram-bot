"""Tests for keyboard layouts."""

import pytest
from unittest.mock import MagicMock, patch

from src.keyboard import (
    create_input_keyboard,
    create_game_message_text,
    create_save_slot_keyboard,
    get_button_from_callback,
    is_valid_button_callback,
    create_help_text,
)
from src.models.game_state import ChatConfig, GameButton, ModifierButtonSpec


class TestCreateInputKeyboard:
    """Test input keyboard creation."""

    def test_returns_markup(self):
        """Test that function returns InlineKeyboardMarkup."""
        keyboard = create_input_keyboard()
        assert hasattr(keyboard, 'inline_keyboard')
        assert isinstance(keyboard.inline_keyboard, (list, tuple))

    def test_no_modifier_specs_has_three_rows(self):
        """Test keyboard has 3 rows when no modifier specs provided."""
        keyboard = create_input_keyboard()
        assert len(keyboard.inline_keyboard) == 3

    def test_with_modifier_specs_appends_row(self):
        """Test that modifier specs add a fourth row."""
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        config = ChatConfig(chat_id=123, modifier_states={})
        keyboard = create_input_keyboard(chat_config=config, modifier_specs=[spec])
        assert len(keyboard.inline_keyboard) == 4

    def test_modifier_button_callback_data(self):
        """Test modifier button uses modifier_ prefix in callback_data."""
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        config = ChatConfig(chat_id=123, modifier_states={})
        keyboard = create_input_keyboard(chat_config=config, modifier_specs=[spec])
        modifier_row = keyboard.inline_keyboard[3]
        assert len(modifier_row) == 1
        assert modifier_row[0].callback_data == "modifier_run"

    def test_modifier_button_inactive_label(self):
        """Test modifier button shows inactive label when state is False."""
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        config = ChatConfig(chat_id=0, modifier_states={"run": False})
        with patch("src.keyboard.translation_manager") as mock_tm:
            mock_tm.get.return_value = "🚶"
            keyboard = create_input_keyboard(chat_config=config, modifier_specs=[spec])
            mock_tm.get.assert_any_call("keyboard.buttons.walking", 0)

    def test_modifier_button_active_label(self):
        """Test modifier button shows active label when state is True."""
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        config = ChatConfig(chat_id=0, modifier_states={"run": True})
        with patch("src.keyboard.translation_manager") as mock_tm:
            mock_tm.get.return_value = "🏃"
            keyboard = create_input_keyboard(chat_config=config, modifier_specs=[spec])
            mock_tm.get.assert_any_call("keyboard.buttons.running", 0)

    def test_base_button_order(self):
        """Test base buttons are in correct order."""
        keyboard = create_input_keyboard()
        assert keyboard.inline_keyboard[0][0].callback_data == "select"
        assert keyboard.inline_keyboard[0][1].callback_data == "up"
        assert keyboard.inline_keyboard[0][2].callback_data == "start"
        assert keyboard.inline_keyboard[1][0].callback_data == "left"
        assert keyboard.inline_keyboard[1][1].callback_data == "down"
        assert keyboard.inline_keyboard[1][2].callback_data == "right"
        assert keyboard.inline_keyboard[2][0].callback_data == "wait"
        assert keyboard.inline_keyboard[2][1].callback_data == "a"
        assert keyboard.inline_keyboard[2][2].callback_data == "b"

    def test_no_run_button_in_base_layout(self):
        """Test RUN button is no longer in base layout."""
        keyboard = create_input_keyboard()
        all_callbacks = [
            btn.callback_data
            for row in keyboard.inline_keyboard
            for btn in row
        ]
        assert "run" not in all_callbacks

    def test_chat_id_from_config(self):
        """Test that chat_id is taken from chat_config."""
        config = ChatConfig(chat_id=42)
        keyboard = create_input_keyboard(chat_config=config)
        assert keyboard is not None

    def test_none_config_uses_defaults(self):
        """Test that None config uses chat_id=0 and empty modifier_states."""
        keyboard = create_input_keyboard(chat_config=None)
        assert keyboard is not None
        assert len(keyboard.inline_keyboard) == 3

    def test_empty_modifier_specs_has_three_rows(self):
        """Test that an empty modifier_specs list produces no modifier row."""
        keyboard = create_input_keyboard(modifier_specs=[])
        assert len(keyboard.inline_keyboard) == 3

    def test_multiple_modifier_specs_produce_multi_button_row(self):
        """Test that multiple modifier specs each get a button in the modifier row."""
        spec1 = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        spec2 = ModifierButtonSpec(
            key="turbo",
            modifier_button=GameButton.A,
            applies_to=[GameButton.DOWN],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        config = ChatConfig(chat_id=0, modifier_states={})
        keyboard = create_input_keyboard(chat_config=config, modifier_specs=[spec1, spec2])
        assert len(keyboard.inline_keyboard) == 4
        modifier_row = keyboard.inline_keyboard[3]
        assert len(modifier_row) == 2
        callbacks = [btn.callback_data for btn in modifier_row]
        assert "modifier_run" in callbacks
        assert "modifier_turbo" in callbacks


class TestCreateGameMessageText:
    """Test game message text creation."""

    def test_basic_text(self):
        text = create_game_message_text()
        assert "Your turn" in text

    def test_text_with_status(self):
        text = create_game_message_text("Processing: A...")
        assert "Processing: A..." in text
        assert "Your turn" in text

    def test_markdown_formatting(self):
        text = create_game_message_text("Status")
        assert "Your turn" in text
        assert "_Status_" in text


class TestCreateSaveSlotKeyboard:
    """Test save slot keyboard creation."""

    def test_correct_number_of_slots(self):
        keyboard = create_save_slot_keyboard(123456, save_slots=5)
        slot_buttons = sum(
            1
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data.startswith("load_slot_")
        )
        assert slot_buttons == 5

    def test_slot_button_format(self):
        keyboard = create_save_slot_keyboard(123456, save_slots=3)
        first_button = keyboard.inline_keyboard[0][0]
        assert "Slot 0" in first_button.text
        assert first_button.callback_data == "load_slot_0"

    def test_has_cancel_button(self):
        keyboard = create_save_slot_keyboard(123456)
        last_row = keyboard.inline_keyboard[-1]
        assert len(last_row) == 1
        assert last_row[0].callback_data == "cancel_load"
        assert "Cancel" in last_row[0].text


class TestGetButtonFromCallback:
    """Test callback data parsing."""

    def test_valid_button_callbacks(self):
        assert get_button_from_callback("up") == GameButton.UP
        assert get_button_from_callback("down") == GameButton.DOWN
        assert get_button_from_callback("left") == GameButton.LEFT
        assert get_button_from_callback("right") == GameButton.RIGHT
        assert get_button_from_callback("a") == GameButton.A
        assert get_button_from_callback("b") == GameButton.B
        assert get_button_from_callback("start") == GameButton.START
        assert get_button_from_callback("select") == GameButton.SELECT
        assert get_button_from_callback("wait") == GameButton.WAIT

    def test_invalid_callback(self):
        assert get_button_from_callback("invalid") is None
        assert get_button_from_callback("") is None
        assert get_button_from_callback("modifier_run") is None


class TestIsValidButtonCallback:
    """Test callback validation."""

    def test_valid_callbacks(self):
        assert is_valid_button_callback("left") is True
        assert is_valid_button_callback("down") is True
        assert is_valid_button_callback("right") is True
        assert is_valid_button_callback("up") is True
        assert is_valid_button_callback("a") is True
        assert is_valid_button_callback("b") is True
        assert is_valid_button_callback("start") is True
        assert is_valid_button_callback("select") is True
        assert is_valid_button_callback("wait") is True
        assert is_valid_button_callback("modifier_run") is True

    def test_invalid_callbacks(self):
        assert is_valid_button_callback("load") is False
        assert is_valid_button_callback("") is False


class TestCreateHelpText:
    """Test help text creation."""

    def test_contains_title(self):
        text = create_help_text(123456)
        assert "How to play" in text

    def test_contains_commands(self):
        text = create_help_text(123456)
        assert "/start_game" in text or "/start" in text
        assert "/help" in text
        assert "button_descriptions" not in text
