"""Tests for keyboard layouts.

This module tests Telegram inline keyboard creation and button handling.
"""

import pytest
from unittest.mock import MagicMock

from src.keyboard import (
    create_input_keyboard,
    create_game_message_text,
    create_disabled_keyboard,
    create_processing_keyboard,
    remove_keyboard,
    create_help_keyboard,
    create_save_slot_keyboard,
    create_confirmation_keyboard,
    get_button_from_callback,
    is_valid_button_callback,
    create_help_text,
    BUTTON_DESCRIPTIONS,
)
from src.models.game_state import GameButton


class TestCreateInputKeyboard:
    """Test input keyboard creation."""
    
    def test_returns_markup(self):
        """Test that function returns InlineKeyboardMarkup."""
        keyboard = create_input_keyboard()
        
        # Should return an object with inline_keyboard attribute
        assert hasattr(keyboard, 'inline_keyboard')
        # InlineKeyboardMarkup uses tuple internally
        assert isinstance(keyboard.inline_keyboard, (list, tuple))
    
    def test_has_correct_number_of_rows(self):
        """Test keyboard has expected number of rows."""
        keyboard = create_input_keyboard()
        
        # Should have 5 rows based on BUTTON_LAYOUT
        assert len(keyboard.inline_keyboard) == 5
    
    def test_contains_all_buttons(self):
        """Test all game buttons are present."""
        keyboard = create_input_keyboard()
        
        # Collect all buttons from keyboard
        all_buttons = set()
        for row in keyboard.inline_keyboard:
            for button in row:
                all_buttons.add(button.callback_data)
        
        # Should have all 8 buttons
        expected_buttons = {b.value for b in GameButton}
        assert all_buttons == expected_buttons
    
    def test_button_callback_data(self):
        """Test buttons have correct callback data."""
        keyboard = create_input_keyboard()
        
        # Check first button (should be UP)
        first_row = keyboard.inline_keyboard[0]
        assert len(first_row) == 1
        assert first_row[0].callback_data == "up"
        assert "⬆️" in first_row[0].text
    
    def test_button_order(self):
        """Test buttons are in correct order."""
        keyboard = create_input_keyboard()
        
        # Row 0: [UP]
        assert keyboard.inline_keyboard[0][0].callback_data == "up"
        
        # Row 1: [LEFT, RIGHT]
        row1 = keyboard.inline_keyboard[1]
        assert row1[0].callback_data == "left"
        assert row1[1].callback_data == "right"
        
        # Row 2: [DOWN]
        assert keyboard.inline_keyboard[2][0].callback_data == "down"
        
        # Row 3: [A, B]
        row3 = keyboard.inline_keyboard[3]
        assert row3[0].callback_data == "a"
        assert row3[1].callback_data == "b"
        
        # Row 4: [START, SELECT]
        row4 = keyboard.inline_keyboard[4]
        assert row4[0].callback_data == "start"
        assert row4[1].callback_data == "select"


class TestCreateGameMessageText:
    """Test game message text creation."""
    
    def test_basic_text(self):
        """Test basic message text."""
        text = create_game_message_text()
        
        assert "Pokémon Red" in text
        assert "Press a button to play" in text
        assert "First press wins" in text
    
    def test_text_with_status(self):
        """Test message text with status."""
        text = create_game_message_text("Processing: A...")
        
        assert "Processing: A..." in text
        assert "Pokémon Red" in text
    
    def test_markdown_formatting(self):
        """Test text uses Markdown formatting."""
        text = create_game_message_text("Status")
        
        assert "*Pokémon Red*" in text  # Bold
        assert "_Status_" in text  # Italic


class TestCreateDisabledKeyboard:
    """Test disabled keyboard creation."""
    
    def test_returns_markup(self):
        """Test function returns markup."""
        keyboard = create_disabled_keyboard()
        
        assert hasattr(keyboard, 'inline_keyboard')
    
    def test_buttons_disabled(self):
        """Test buttons show disabled state."""
        keyboard = create_disabled_keyboard()
        
        # All buttons should have "disabled" callback
        for row in keyboard.inline_keyboard:
            for button in row:
                assert button.callback_data == "disabled"
                assert "❌" in button.text


class TestCreateProcessingKeyboard:
    """Test processing keyboard creation."""
    
    def test_single_button(self):
        """Test processing keyboard has one button."""
        keyboard = create_processing_keyboard(GameButton.A)
        
        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 1
    
    def test_shows_button_name(self):
        """Test button shows processing text."""
        keyboard = create_processing_keyboard(GameButton.START)
        
        button = keyboard.inline_keyboard[0][0]
        assert "Processing: Start" in button.text
        assert button.callback_data == "processing"


class TestRemoveKeyboard:
    """Test keyboard removal."""
    
    def test_returns_none(self):
        """Test remove_keyboard returns None."""
        result = remove_keyboard()
        
        assert result is None


class TestCreateHelpKeyboard:
    """Test help keyboard creation."""
    
    def test_has_buttons(self):
        """Test help keyboard has buttons."""
        keyboard = create_help_keyboard()
        
        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 2
    
    def test_button_callbacks(self):
        """Test help keyboard button callbacks."""
        keyboard = create_help_keyboard()
        
        row = keyboard.inline_keyboard[0]
        assert row[0].callback_data == "refresh"
        assert row[1].callback_data == "help"


class TestCreateSaveSlotKeyboard:
    """Test save slot keyboard creation."""
    
    def test_correct_number_of_slots(self):
        """Test keyboard has correct number of slot buttons."""
        keyboard = create_save_slot_keyboard(123456, save_slots=5)
        
        # Count slot buttons (excluding cancel)
        slot_buttons = 0
        for row in keyboard.inline_keyboard:
            for button in row:
                if button.callback_data.startswith("load_slot_"):
                    slot_buttons += 1
        
        assert slot_buttons == 5
    
    def test_slot_button_format(self):
        """Test slot button format."""
        keyboard = create_save_slot_keyboard(123456, save_slots=3)
        
        # Check first slot button
        first_button = keyboard.inline_keyboard[0][0]
        assert "Slot 0" in first_button.text
        assert first_button.callback_data == "load_slot_0"
    
    def test_has_cancel_button(self):
        """Test keyboard has cancel button."""
        keyboard = create_save_slot_keyboard(123456)
        
        # Last row should be cancel
        last_row = keyboard.inline_keyboard[-1]
        assert len(last_row) == 1
        assert last_row[0].callback_data == "cancel_load"
        assert "Cancel" in last_row[0].text


class TestCreateConfirmationKeyboard:
    """Test confirmation keyboard creation."""
    
    def test_yes_no_buttons(self):
        """Test keyboard has Yes/No buttons."""
        keyboard = create_confirmation_keyboard("reset")
        
        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 2
    
    def test_button_callbacks(self):
        """Test button callbacks include action."""
        keyboard = create_confirmation_keyboard("delete")
        
        row = keyboard.inline_keyboard[0]
        assert row[0].callback_data == "confirm_delete"
        assert row[1].callback_data == "cancel"


class TestGetButtonFromCallback:
    """Test callback data parsing."""
    
    def test_valid_button_callbacks(self):
        """Test parsing valid button callbacks."""
        assert get_button_from_callback("up") == GameButton.UP
        assert get_button_from_callback("down") == GameButton.DOWN
        assert get_button_from_callback("a") == GameButton.A
        assert get_button_from_callback("start") == GameButton.START
    
    def test_invalid_callback(self):
        """Test parsing invalid callback."""
        assert get_button_from_callback("invalid") is None
        assert get_button_from_callback("") is None
        assert get_button_from_callback("up_down") is None


class TestIsValidButtonCallback:
    """Test callback validation."""
    
    def test_valid_callbacks(self):
        """Test valid button callbacks."""
        assert is_valid_button_callback("left") is True
        assert is_valid_button_callback("right") is True
        assert is_valid_button_callback("b") is True
        assert is_valid_button_callback("select") is True
    
    def test_invalid_callbacks(self):
        """Test invalid callbacks."""
        assert is_valid_button_callback("load") is False
        assert is_valid_button_callback("refresh") is False
        assert is_valid_button_callback("") is False


class TestCreateHelpText:
    """Test help text creation."""
    
    def test_contains_title(self):
        """Test help text contains title."""
        text = create_help_text()
        
        assert "Game Controls" in text
    
    def test_contains_all_buttons(self):
        """Test help text describes all buttons."""
        text = create_help_text()
        
        for button in GameButton:
            assert button.emoji in text
            assert button.display_name in text
    
    def test_contains_commands(self):
        """Test help text lists commands."""
        text = create_help_text()
        
        assert "/start_game" in text or "/start" in text
        assert "/help" in text
    
    def test_button_descriptions_exist(self):
        """Test all buttons have descriptions."""
        for button in GameButton:
            assert button in BUTTON_DESCRIPTIONS
            assert len(BUTTON_DESCRIPTIONS[button]) > 0


class TestButtonDescriptions:
    """Test button description constants."""
    
    def test_all_buttons_have_descriptions(self):
        """Test every GameButton has a description."""
        for button in GameButton:
            assert button in BUTTON_DESCRIPTIONS
            assert isinstance(BUTTON_DESCRIPTIONS[button], str)
    
    def test_descriptions_meaningful(self):
        """Test descriptions are meaningful."""
        for button, description in BUTTON_DESCRIPTIONS.items():
            assert len(description) > 5  # Should be more than just a word
            assert button.display_name in description or len(description) > 10
