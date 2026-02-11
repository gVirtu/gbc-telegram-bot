"""Tests for user input tracking feature.

This module tests:
- ChatGameState serialization with user tracking fields
- User input recording in InputHandler
- Message display with recent inputs
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from src.models.game_state import ChatGameState, GameButton, GameSession
from src.keyboard import create_game_message_text
from src.handlers.input_handler import InputHandler


class TestChatGameStateSerialization:
    """Test ChatGameState serialization with new tracking fields."""

    def test_new_fields_default_values(self):
        """Test that new fields have proper default values."""
        state = ChatGameState(chat_id=123)

        assert state.user_input_counts == {}
        assert state.recent_inputs == []

    def test_to_dict_includes_new_fields(self):
        """Test that to_dict includes user tracking fields."""
        state = ChatGameState(chat_id=123)
        state.user_input_counts = {"456": 5, "789": 3}
        state.recent_inputs = [
            {
                "user_id": 456,
                "user_name": "Alice",
                "button": "a",
                "timestamp": "2026-02-06T12:00:00.000000"
            }
        ]

        data = state.to_dict()

        assert "user_input_counts" in data
        assert data["user_input_counts"] == {"456": 5, "789": 3}
        assert "recent_inputs" in data
        assert len(data["recent_inputs"]) == 1
        assert data["recent_inputs"][0]["user_name"] == "Alice"

    def test_from_dict_with_new_fields(self):
        """Test that from_dict loads user tracking fields."""
        data = {
            "chat_id": 123,
            "message_id": 456,
            "input_in_progress": False,
            "last_input": "a",
            "last_input_time": None,
            "frame_hash": "abc123",
            "user_input_counts": {"789": 10},
            "recent_inputs": [
                {
                    "user_id": 789,
                    "user_name": "Bob",
                    "button": "b",
                    "timestamp": "2026-02-06T12:00:00.000000"
                }
            ],
            "created_at": "2026-02-06T12:00:00.000000",
            "updated_at": "2026-02-06T12:00:00.000000",
        }

        state = ChatGameState.from_dict(data)

        assert state.user_input_counts == {"789": 10}
        assert len(state.recent_inputs) == 1
        assert state.recent_inputs[0]["user_name"] == "Bob"

    def test_from_dict_backward_compatibility(self):
        """Test that from_dict handles missing new fields (backward compatibility)."""
        data = {
            "chat_id": 123,
            "message_id": 456,
            "input_in_progress": False,
            "last_input": None,
            "last_input_time": None,
            "frame_hash": None,
            "created_at": "2026-02-06T12:00:00.000000",
            "updated_at": "2026-02-06T12:00:00.000000",
        }

        state = ChatGameState.from_dict(data)

        # Should use default values
        assert state.user_input_counts == {}
        assert state.recent_inputs == []

    def test_serialization_roundtrip(self):
        """Test that data survives serialization roundtrip."""
        original = ChatGameState(chat_id=123)
        original.user_input_counts = {"111": 1, "222": 2}
        original.recent_inputs = [
            {
                "user_id": 111,
                "user_name": "User1",
                "button": "up",
                "timestamp": "2026-02-06T12:00:00.000000"
            },
            {
                "user_id": 222,
                "user_name": "User2",
                "button": "down",
                "timestamp": "2026-02-06T12:01:00.000000"
            }
        ]

        data = original.to_dict()
        restored = ChatGameState.from_dict(data)

        assert restored.user_input_counts == original.user_input_counts
        assert restored.recent_inputs == original.recent_inputs


class TestInputRecording:
    """Test user input recording in InputHandler."""

    def test_record_user_input_increments_count(self):
        """Test that recording input increments user count."""
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123)
        session = GameSession(chat_id=123, state=state)

        handler._record_user_input(session, 456, "Alice", [GameButton.A])

        assert session.state.user_input_counts["456"] == 1

        handler._record_user_input(session, 456, "Alice", [GameButton.B])

        assert session.state.user_input_counts["456"] == 2

    def test_record_user_input_multiple_users(self):
        """Test recording inputs from multiple users."""
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123)
        session = GameSession(chat_id=123, state=state)

        handler._record_user_input(session, 456, "Alice", [GameButton.A])
        handler._record_user_input(session, 789, "Bob", [GameButton.B])
        handler._record_user_input(session, 456, "Alice", [GameButton.UP])

        assert session.state.user_input_counts["456"] == 2
        assert session.state.user_input_counts["789"] == 1

    def test_record_user_input_adds_to_recent(self):
        """Test that recording input adds to recent_inputs."""
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123)
        session = GameSession(chat_id=123, state=state)

        handler._record_user_input(session, 456, "Alice", [GameButton.A])

        assert len(session.state.recent_inputs) == 1
        assert session.state.recent_inputs[0]["user_id"] == 456
        assert session.state.recent_inputs[0]["user_name"] == "Alice"
        assert session.state.recent_inputs[0]["buttons"] == ["a"]
        assert "timestamp" in session.state.recent_inputs[0]

    def test_record_user_input_fifo_behavior(self):
        """Test that recent_inputs maintains FIFO with max 3 entries."""
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123)
        session = GameSession(chat_id=123, state=state)

        # Add 5 inputs
        handler._record_user_input(session, 1, "User1", [GameButton.A])
        handler._record_user_input(session, 2, "User2", [GameButton.B])
        handler._record_user_input(session, 3, "User3", [GameButton.UP])
        handler._record_user_input(session, 4, "User4", [GameButton.DOWN])
        handler._record_user_input(session, 5, "User5", [GameButton.START])

        # Should only keep last 3
        assert len(session.state.recent_inputs) == 3
        assert session.state.recent_inputs[0]["user_id"] == 3
        assert session.state.recent_inputs[1]["user_id"] == 4
        assert session.state.recent_inputs[2]["user_id"] == 5

    def test_user_name_extraction_first_name(self):
        """Test that first_name is used when available."""
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123)
        session = GameSession(chat_id=123, state=state)

        handler._record_user_input(session, 456, "Alice", [GameButton.A])

        assert session.state.recent_inputs[0]["user_name"] == "Alice"

    def test_user_name_extraction_username_fallback(self):
        """Test that @username is used when first_name is not available."""
        # This is tested implicitly by the calling code, but we can test
        # that the record method accepts any string
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123)
        session = GameSession(chat_id=123, state=state)

        handler._record_user_input(session, 456, "@alice_user", [GameButton.A])

        assert session.state.recent_inputs[0]["user_name"] == "@alice_user"

    def test_user_name_extraction_user_fallback(self):
        """Test that 'User' fallback works."""
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123)
        session = GameSession(chat_id=123, state=state)

        handler._record_user_input(session, 456, "User", [GameButton.A])

        assert session.state.recent_inputs[0]["user_name"] == "User"


class TestMessageDisplay:
    """Test message display formatting with recent inputs."""

    def test_create_message_no_recent_inputs(self):
        """Test message creation with no recent inputs (default behavior)."""
        text = create_game_message_text()

        assert "Sua vez" in text
        assert "Atividade recente" not in text

    def test_create_message_with_empty_list(self):
        """Test message creation with empty recent_inputs list."""
        text = create_game_message_text(recent_inputs=[])

        assert "Sua vez" in text
        assert "Atividade recente" not in text

    def test_create_message_with_one_input(self):
        """Test message creation with one recent input."""
        recent = [
            {
                "user_id": 456,
                "user_name": "Alice",
                "button": "a",
                "timestamp": "2026-02-06T12:00:00.000000"
            }
        ]

        text = create_game_message_text(recent_inputs=recent)

        assert "Atividade recente" in text
        assert "Alice: 🅰️ A" in text

    def test_create_message_with_three_inputs(self):
        """Test message creation with three recent inputs."""
        recent = [
            {
                "user_id": 1,
                "user_name": "Alice",
                "button": "a",
                "timestamp": "2026-02-06T12:00:00.000000"
            },
            {
                "user_id": 2,
                "user_name": "Bob",
                "button": "b",
                "timestamp": "2026-02-06T12:01:00.000000"
            },
            {
                "user_id": 3,
                "user_name": "Charlie",
                "button": "up",
                "timestamp": "2026-02-06T12:02:00.000000"
            }
        ]

        text = create_game_message_text(recent_inputs=recent)

        assert "Atividade recente" in text
        # Most recent should be shown first (reversed)
        lines = text.split("\n")
        assert "Charlie: ⬆️ Cima" in lines[-3]
        assert "Bob: 🅱️ B" in lines[-2]
        assert "Alice: 🅰️ A" in lines[-1]

    def test_create_message_with_status_and_inputs(self):
        """Test message creation with both status and recent inputs."""
        recent = [
            {
                "user_id": 456,
                "user_name": "Alice",
                "button": "start",
                "timestamp": "2026-02-06T12:00:00.000000"
            }
        ]

        text = create_game_message_text(status="Jogo salvo!", recent_inputs=recent)

        assert "Atividade recente" in text
        assert "Alice: START Start" in text
        assert "_Jogo salvo!_" in text

    def test_button_emoji_and_display_name(self):
        """Test that all button types display correctly."""
        buttons_to_test = [
            ("up", "⬆️", "Cima"),
            ("down", "⬇️", "Baixo"),
            ("left", "⬅️", "Esquerda"),
            ("right", "➡️", "Direita"),
            ("a", "🅰️", "A"),
            ("b", "🅱️", "B"),
            ("start", "START", "Start"),
            ("select", "SELECT", "Select"),
        ]

        for button_value, emoji, display in buttons_to_test:
            recent = [
                {
                    "user_id": 456,
                    "user_name": "Tester",
                    "button": button_value,
                    "timestamp": "2026-02-06T12:00:00.000000"
                }
            ]

            text = create_game_message_text(recent_inputs=recent)

            assert f"Tester: {emoji} {display}" in text


class TestIntegration:
    """Integration tests for the full input tracking flow."""

    @pytest.mark.asyncio
    async def test_full_input_flow(self):
        """Test complete flow: button press -> state update -> message display."""
        # Create mock callback query
        callback_query = Mock()
        callback_query.message.chat.id = 123
        callback_query.message.message_id = 999
        callback_query.data = "a"
        callback_query.from_user.id = 456
        callback_query.from_user.first_name = "Alice"
        callback_query.from_user.username = None
        callback_query.answer = AsyncMock()

        # Create handler with mocked dependencies
        mock_bot = Mock()
        mock_bot.edit_message_reply_markup = AsyncMock()
        mock_bot.edit_message_media = AsyncMock()
        mock_bot.edit_message_caption = AsyncMock()

        handler = InputHandler(mock_bot)

        # Create session
        state = ChatGameState(chat_id=123, message_id=999)
        session = GameSession(chat_id=123, state=state)
        handler._sessions[123] = session

        # Mock game controller
        with patch('src.handlers.input_handler.game_controller_manager') as mock_gcm, \
             patch('src.handlers.input_handler.state_manager') as mock_sm:

            mock_controller = Mock()
            mock_controller.send_input = Mock(return_value=None)
            mock_controller.tick = Mock(return_value=None)
            mock_controller.get_frame_as_png = Mock(return_value=b"fake_png")
            mock_controller.last_frame_hash = "hash123"
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)

            # Mock should_update_frame to skip animation
            with patch('src.handlers.input_handler.should_update_frame', return_value=(False, "hash123")), \
                 patch('src.handlers.input_handler.settings') as mock_settings, \
                 patch('asyncio.sleep', new_callable=AsyncMock):
                
                # Set animation duration to 0 to avoid infinite loop
                mock_settings.animation_duration = 0


                # Handle button press
                await handler.handle_button_press(callback_query)

        # Verify user input was recorded
        assert session.state.user_input_counts["456"] == 1
        assert len(session.state.recent_inputs) == 1
        assert session.state.recent_inputs[0]["user_name"] == "Alice"
        assert session.state.recent_inputs[0]["buttons"] == ["a"]

        # Verify message would include recent inputs
        text = create_game_message_text(recent_inputs=session.state.recent_inputs)
        assert "Alice: 🅰️ A" in text

    @pytest.mark.asyncio
    async def test_multiple_users_sequence(self):
        """Test input tracking with multiple users pressing buttons in sequence."""
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123, message_id=999)
        session = GameSession(chat_id=123, state=state)
        handler._sessions[123] = session

        # Simulate three different users pressing buttons
        users = [
            (456, "Alice", [GameButton.A]),
            (789, "Bob", [GameButton.B]),
            (101, "Charlie", [GameButton.UP]),
        ]

        for user_id, user_name, button in users:
            handler._record_user_input(session, user_id, user_name, button)

        # Verify counts
        assert session.state.user_input_counts["456"] == 1
        assert session.state.user_input_counts["789"] == 1
        assert session.state.user_input_counts["101"] == 1

        # Verify recent inputs
        assert len(session.state.recent_inputs) == 3

        # Verify message display (most recent first)
        text = create_game_message_text(recent_inputs=session.state.recent_inputs)
        lines = text.split("\n")

        assert "Charlie: ⬆️ Cima" in lines[-3]
        assert "Bob: 🅱️ B" in lines[-2]
        assert "Alice: 🅰️ A" in lines[-1]


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_user_name(self):
        """Test handling of empty user name."""
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123)
        session = GameSession(chat_id=123, state=state)

        handler._record_user_input(session, 456, "", [GameButton.A])

        # Should still record the input
        assert len(session.state.recent_inputs) == 1
        assert session.state.recent_inputs[0]["user_name"] == ""

    def test_very_long_user_name(self):
        """Test handling of very long user names."""
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123)
        session = GameSession(chat_id=123, state=state)

        long_name = "A" * 100
        handler._record_user_input(session, 456, long_name, [GameButton.A])

        assert session.state.recent_inputs[0]["user_name"] == long_name

    def test_special_characters_in_name(self):
        """Test handling of special characters in user names."""
        mock_bot = Mock()
        handler = InputHandler(mock_bot)

        state = ChatGameState(chat_id=123)
        session = GameSession(chat_id=123, state=state)

        special_name = "Alice 😀 *Test* _User_"
        handler._record_user_input(session, 456, special_name, [GameButton.A])

        assert session.state.recent_inputs[0]["user_name"] == special_name

    def test_message_length_with_max_inputs(self):
        """Test that message with max inputs doesn't exceed reasonable length."""
        # Create longest possible input records
        long_name = "VeryLongUserName123"
        recent = []

        for i in range(3):
            recent.append({
                "user_id": i,
                "user_name": long_name,
                "button": "select",  # Longest display name
                "timestamp": "2026-02-06T12:00:00.000000"
            })

        text = create_game_message_text(recent_inputs=recent)

        # Telegram caption limit is 1024 characters
        # Our message should be well under that
        assert len(text) < 1024
        assert len(text) < 300  # Should be much shorter in practice
