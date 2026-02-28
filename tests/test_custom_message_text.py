"""Integration tests for custom message base text feature.

Tests that custom message text flows from /m command through to displayed messages.
"""

import pytest

from src.keyboard import create_game_message_text
from src.models.game_state import ChatConfig


class TestCustomMessageTextIntegration:
    """Integration tests for custom message base text feature."""

    def test_create_game_message_text_with_override(self):
        """Test that create_game_message_text uses override when provided."""
        # Without override
        text_default = create_game_message_text()
        assert "Your turn!" in text_default

        # With override
        text_custom = create_game_message_text(base_text_override="Custom message!")
        assert "Custom message!" in text_custom
        assert "Your turn!" not in text_custom

    def test_create_game_message_text_with_queue_ignores_override(self):
        """Test that queue length overrides base text (override only used when queue is empty)."""
        text = create_game_message_text(queue_length=3, base_text_override="Custom!")
        assert "3 inputs in queue" in text
        assert "Custom!" not in text

    def test_chat_config_persistence(self):
        """Test that ChatConfig correctly handles message_base_text."""
        config = ChatConfig(
            chat_id=123456,
            message_base_text="Vamos jogar!"
        )
        
        # Test to_dict
        data = config.to_dict()
        assert data["message_base_text"] == "Vamos jogar!"
        
        # Test from_dict
        config2 = ChatConfig.from_dict(data)
        assert config2.message_base_text == "Vamos jogar!"

    def test_chat_config_none_value(self):
        """Test that ChatConfig handles None message_base_text."""
        config = ChatConfig(chat_id=123456)
        
        # Default should be None
        assert config.message_base_text is None
        
        # Test to_dict with None
        data = config.to_dict()
        assert data["message_base_text"] is None
        
        # Test from_dict with None
        config2 = ChatConfig.from_dict(data)
        assert config2.message_base_text is None
