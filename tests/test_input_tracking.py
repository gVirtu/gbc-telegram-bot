"""Tests for user input tracking feature.

This module tests:
- ChatGameState serialization with user tracking fields
- User input recording in InputHandler
- Message display with recent inputs
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from src.models.game_state import ChatGameState, GameButton, GameSession
from src.models.input_queue import BufferedInput
from src.keyboard import create_game_message_text
from src.handlers.input_handler import InputHandler


class TestChatGameStateSerialization:
    """Test ChatGameState serialization with new tracking fields."""

    def test_new_fields_default_values(self):
        """Test that tracking fields have proper default values."""
        state = ChatGameState(chat_id=123)

        assert state.user_input_counts == {}

    def test_to_dict_includes_new_fields(self):
        """Test that to_dict includes user tracking fields."""
        state = ChatGameState(chat_id=123)
        state.user_input_counts = {"456": 5, "789": 3}

        data = state.to_dict()

        assert "user_input_counts" in data
        assert data["user_input_counts"] == {"456": 5, "789": 3}

    def test_from_dict_with_new_fields(self):
        """Test that from_dict loads user tracking fields."""
        data = {
            "chat_id": 123,
            "message_id": 456,
            "input_in_progress": False,
            "last_input": "a",
            "last_input_time": None,
            "user_input_counts": {"789": 10},
            "created_at": "2026-02-06T12:00:00.000000",
            "updated_at": "2026-02-06T12:00:00.000000",
        }

        state = ChatGameState.from_dict(data)

        assert state.user_input_counts == {"789": 10}

    def test_from_dict_backward_compatibility(self):
        """Test that from_dict handles missing new fields (backward compatibility)."""
        data = {
            "chat_id": 123,
            "message_id": 456,
            "input_in_progress": False,
            "last_input": None,
            "last_input_time": None,
            "created_at": "2026-02-06T12:00:00.000000",
            "updated_at": "2026-02-06T12:00:00.000000",
        }

        state = ChatGameState.from_dict(data)

        assert state.user_input_counts == {}

    def test_serialization_roundtrip(self):
        """Test that data survives serialization roundtrip."""
        original = ChatGameState(chat_id=123)
        original.user_input_counts = {"111": 1, "222": 2}

        data = original.to_dict()
        restored = ChatGameState.from_dict(data)

        assert restored.user_input_counts == original.user_input_counts


class TestInputRecording:
    """Test user input recording in InputHandler."""

    def test_record_user_input_increments_count(self):
        """Test that recording input increments user count."""
        handler = InputHandler()

        state = ChatGameState(chat_id=123)

        handler._aggregate_to_recent_inputs(state, [BufferedInput(456, "Alice", GameButton.A)])

        assert state.user_input_counts["456"] == 1

        handler._aggregate_to_recent_inputs(state, [BufferedInput(456, "Alice", GameButton.B)])

        assert state.user_input_counts["456"] == 2

    def test_record_user_input_multiple_users(self):
        """Test recording inputs from multiple users."""
        handler = InputHandler()

        state = ChatGameState(chat_id=123)

        handler._aggregate_to_recent_inputs(state, [BufferedInput(456, "Alice", GameButton.A)])
        handler._aggregate_to_recent_inputs(state, [BufferedInput(789, "Bob", GameButton.B)])
        handler._aggregate_to_recent_inputs(state, [BufferedInput(456, "Alice", GameButton.UP)])

        assert state.user_input_counts["456"] == 2
        assert state.user_input_counts["789"] == 1


class TestMessageDisplay:
    """Test message display formatting with recent inputs."""

    def test_create_message_no_recent_inputs(self):
        """Test message creation with no recent inputs (default behavior)."""
        text = create_game_message_text()

        assert "Your turn" in text
        assert "Recent Activity" not in text

    def test_create_message_with_empty_list(self):
        """Test message creation with empty recent_inputs list."""
        text = create_game_message_text(recent_inputs=[])

        assert "Your turn" in text
        assert "Recent Activity" not in text

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

        assert "Recent Activity" in text
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

        assert "Recent Activity" in text
        # Most recent should be shown first (reversed)
        lines = text.split("\n")
        assert "Charlie: ⬆️ Up" in lines[-3]
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

        text = create_game_message_text(status="Game saved!", recent_inputs=recent)

        assert "Recent Activity" in text
        assert "Alice: START Start" in text
        assert "_Game saved!_" in text

    def test_button_emoji_and_display_name(self):
        """Test that all button types display correctly."""
        buttons_to_test = [
            ("up", "⬆️", "Up"),
            ("down", "⬇️", "Down"),
            ("left", "⬅️", "Left"),
            ("right", "➡️", "Right"),
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

        # Create mock adapter
        mock_adapter = MagicMock()
        mock_adapter.send_game_message = AsyncMock(return_value=100)
        mock_adapter.edit_game_message = AsyncMock(return_value=None)
        mock_adapter.edit_game_keyboard = AsyncMock()
        mock_adapter.answer_interaction = AsyncMock()

        # Create handler
        handler = InputHandler()

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
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)

            with patch('src.handlers.input_handler.settings') as mock_settings, \
                 patch('asyncio.sleep', new_callable=AsyncMock):

                # Set animation duration to 0 to avoid infinite loop
                mock_settings.animation_duration = 0
                mock_settings.max_queue_size = 10
                mock_settings.maximum_inputs_per_animation = 8
                mock_settings.max_sequence_length = 6
                mock_settings.input_buffer_seconds = 1.5
                mock_settings.min_update_interval_seconds = 5.0

                # Mock _process_queue_loop to run immediately (queue processing is async now)
                with patch.object(handler, '_process_queue_loop', new_callable=AsyncMock) as mock_process:
                    # Handle button press
                    await handler.handle_button_press(
                        callback_data=callback_query.data,
                        chat_id=callback_query.message.chat.id,
                        message_id=callback_query.message.message_id,
                        user_id=callback_query.from_user.id,
                        user_name="Alice",
                        adapter=mock_adapter,
                        raw=callback_query,
                    )

                    # Verify buffer has the input
                    assert handler._pending_buffers[123].total_buttons() == 1
                    assert handler._pending_buffers[123].items[0].user_id == 456

    @pytest.mark.asyncio
    async def test_multiple_users_sequence(self):
        """Test input tracking with multiple users pressing buttons in sequence."""
        handler = InputHandler()

        state = ChatGameState(chat_id=123, message_id=999)
        session = GameSession(chat_id=123, state=state)
        handler._sessions[123] = session

        # Simulate three different users pressing buttons
        users = [
            (456, "Alice", [GameButton.A]),
            (789, "Bob", [GameButton.B]),
            (101, "Charlie", [GameButton.UP]),
        ]

        for user_id, user_name, buttons in users:
            handler._aggregate_to_recent_inputs(session.state, [BufferedInput(user_id, user_name, b) for b in buttons])

        # Verify counts
        assert session.state.user_input_counts["456"] == 1
        assert session.state.user_input_counts["789"] == 1
        assert session.state.user_input_counts["101"] == 1


class TestEdgeCases:
    """Test edge cases and error conditions."""

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
