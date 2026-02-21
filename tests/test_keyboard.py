"""Tests for keyboard layouts.

This module tests Telegram inline keyboard creation and button handling.
"""

import pytest
from unittest.mock import MagicMock

from src.keyboard import (
    create_input_keyboard,
    create_game_message_text,
    create_save_slot_keyboard,
    get_button_from_callback,
    is_valid_button_callback,
    create_help_text
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
        assert len(keyboard.inline_keyboard) == 4
    
    def test_contains_all_buttons(self):
        """Test all game buttons are present (except SEQUENCE and ENVIAR which are deprecated)."""
        keyboard = create_input_keyboard()

        # Collect all buttons from keyboard
        all_buttons = set()
        for row in keyboard.inline_keyboard:
            for button in row:
                all_buttons.add(button.callback_data)

        # Should have all buttons except SEQUENCE and ENVIAR (which are deprecated)
        expected_buttons = {b.value for b in GameButton if b not in (GameButton.SEQUENCE, GameButton.ENVIAR)}
        assert all_buttons == expected_buttons
    
    def test_button_order(self):
        """Test buttons are in correct order."""
        keyboard = create_input_keyboard()

        # Row 0: [SELECT, UP, START]
        assert keyboard.inline_keyboard[0][0].callback_data == "select"
        assert keyboard.inline_keyboard[0][1].callback_data == "up"
        assert keyboard.inline_keyboard[0][2].callback_data == "start"

        # Row 1: [LEFT, DOWN, RIGHT]
        row1 = keyboard.inline_keyboard[1]
        assert row1[0].callback_data == "left"
        assert row1[1].callback_data == "down"
        assert row1[2].callback_data == "right"

        # Row 2: [WAIT, A, B]
        assert keyboard.inline_keyboard[2][0].callback_data == "wait"
        assert keyboard.inline_keyboard[2][1].callback_data == "a"
        assert keyboard.inline_keyboard[2][2].callback_data == "b"

        # Row 3: [RUN]
        row3 = keyboard.inline_keyboard[3]
        assert row3[0].callback_data == "run"
        assert len(row3) == 1


class TestCreateGameMessageText:
    """Test game message text creation."""
    
    def test_basic_text(self):
        """Test basic message text."""
        text = create_game_message_text()
        
        assert "Sua vez" in text
    
    def test_text_with_status(self):
        """Test message text with status."""
        text = create_game_message_text("Processando: A...")
        
        assert "Processando: A..." in text
        assert "Sua vez" in text
    
    def test_markdown_formatting(self):
        """Test text uses Markdown formatting."""
        text = create_game_message_text("Status")
        
        assert "Sua vez" in text
        assert "_Status_" in text  # Italic


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
        text = create_help_text(123456)
        
        assert "Como jogar" in text
    
    def test_contains_all_buttons(self):
        """Test help text describes all active buttons (excluding deprecated SEQUENCE and ENVIAR)."""
        text = create_help_text(123456)

        # Only check active buttons (excluding deprecated SEQUENCE and ENVIAR)
        active_buttons = [b for b in GameButton if b not in (GameButton.SEQUENCE, GameButton.ENVIAR)]
        for button in active_buttons:
            assert button.emoji in text

    def test_contains_commands(self):
        """Test help text lists commands."""
        text = create_help_text(123456)
        
        assert "/start_game" in text or "/start" in text
        assert "/help" in text
        
        # Make sure all descriptions have been translated
        assert "button_descriptions" not in text
    