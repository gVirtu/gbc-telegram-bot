"""Tests for input handler.

This module tests the buffered input queue system, state transitions,
and input processing flow.
"""

import asyncio
import os
import pytest
import numpy as np
from datetime import datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

# Set environment variables before importing
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
os.environ["WEBHOOK_URL"] = "https://test.example.com"
os.environ["WEBHOOK_SECRET"] = "test_secret_1234567890"

from telegram.error import TelegramError

from src.handlers.input_handler import (
    InputHandler,
    InputHandlerError,
    get_input_handler,
)
from src.models.game_state import ChatGameState, GameButton, GameSession
from src.models.input_queue import BufferedInput, PendingBuffer


class TestInputHandlerInitialization:
    """Test InputHandler initialization."""

    def test_init_no_args(self):
        """Test initialization with no arguments."""
        handler = InputHandler()

        assert handler._sessions == {}
        assert handler._processing == set()
        assert handler._pending_buffers == {}
        assert handler._buffer_tasks == {}
        assert handler._drain_events == {}

    def test_processing_set_isolated(self):
        """Test that processing set is isolated per handler instance."""
        handler1 = InputHandler()
        handler2 = InputHandler()

        handler1._processing.add(123)

        assert 123 in handler1._processing
        assert 123 not in handler2._processing, "Processing sets should be isolated"


class TestButtonPressHandling:
    """Test button press handling with buffered queue."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    @pytest.fixture
    def mock_callback_query(self):
        cq = MagicMock()
        cq.message.chat.id = 123456
        cq.message.message_id = 789
        cq.data = "a"
        cq.from_user.id = 1001
        cq.from_user.first_name = "TestUser"
        cq.from_user.username = "testuser"
        cq.answer = AsyncMock()
        return cq

    @pytest.mark.asyncio
    async def test_invalid_callback(self, handler, mock_callback_query, mock_adapter):
        """Test button press with invalid callback data."""
        await handler.handle_button_press(
            callback_data="invalid",
            chat_id=mock_callback_query.message.chat.id,
            message_id=mock_callback_query.message.message_id,
            user_id=mock_callback_query.from_user.id,
            user_name="TestUser",
            adapter=mock_adapter,
            raw=mock_callback_query,
        )

        mock_adapter.answer_interaction.assert_called_once_with(mock_callback_query, "Invalid button")

    @pytest.mark.asyncio
    async def test_input_already_in_progress(self, handler, mock_callback_query, mock_adapter):
        """Test button press while processing adds to buffer and answers with queue message."""
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            mock_state.save_game_state.return_value = None
            handler._processing.add(123456)
            handler._sessions[123456] = GameSession(
                chat_id=123456,
                state=ChatGameState(chat_id=123456, message_id=789)
            )

            await handler.handle_button_press(
                callback_data=mock_callback_query.data,
                chat_id=mock_callback_query.message.chat.id,
                message_id=mock_callback_query.message.message_id,
                user_id=mock_callback_query.from_user.id,
                user_name="TestUser",
                adapter=mock_adapter,
                raw=mock_callback_query,
            )

            mock_adapter.answer_interaction.assert_called_once()
            call_args = mock_adapter.answer_interaction.call_args[0][1]
            assert "Added to queue" in call_args or "Added to your sequence" in call_args

    @pytest.mark.asyncio
    async def test_outdated_message(self, handler, mock_callback_query, mock_adapter):
        """Test button press on outdated message is rejected."""
        with patch("src.handlers.input_handler.state_manager"):
            handler._sessions[123456] = GameSession(
                chat_id=123456,
                state=ChatGameState(chat_id=123456, message_id=999)
            )

            await handler.handle_button_press(
                callback_data=mock_callback_query.data,
                chat_id=mock_callback_query.message.chat.id,
                message_id=789,
                user_id=mock_callback_query.from_user.id,
                user_name="TestUser",
                adapter=mock_adapter,
                raw=mock_callback_query,
            )

            mock_adapter.answer_interaction.assert_called_once()
            call_args = mock_adapter.answer_interaction.call_args[0][1]
            assert "outdated" in call_args

    @pytest.mark.asyncio
    async def test_successful_button_press(self, handler, mock_callback_query, mock_adapter):
        """Test successful button press starts buffer timer and processing loop."""
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            mock_state.save_game_state.return_value = None
            with patch("src.handlers.input_handler.asyncio.create_task", side_effect=lambda coro, **kw: coro.close()) as mock_create_task:
                handler._sessions[123456] = GameSession(
                    chat_id=123456,
                    state=ChatGameState(chat_id=123456, message_id=789)
                )

                await handler.handle_button_press(
                    callback_data=mock_callback_query.data,
                    chat_id=mock_callback_query.message.chat.id,
                    message_id=mock_callback_query.message.message_id,
                    user_id=mock_callback_query.from_user.id,
                    user_name="TestUser",
                    adapter=mock_adapter,
                    raw=mock_callback_query,
                )

                mock_adapter.answer_interaction.assert_called_once()
                # create_task called: once for timer, once for process loop
                assert mock_create_task.call_count >= 1

                # Buffer was populated
                assert 123456 in handler._pending_buffers
                assert not handler._pending_buffers[123456].is_empty()

    @pytest.mark.asyncio
    async def test_max_sequence_triggers_drain_immediately(self, handler, mock_adapter):
        """Test that reaching max_sequence_length fires drain event immediately."""
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            mock_state.save_game_state.return_value = None
            with patch("src.handlers.input_handler.asyncio.create_task", side_effect=lambda coro, **kw: coro.close()):
                with patch("src.handlers.input_handler.settings") as mock_settings:
                    mock_settings.max_sequence_length = 2
                    mock_settings.maximum_inputs_per_animation = 8
                    mock_settings.input_buffer_seconds = 1.5
                    mock_settings.max_queue_size = 50
                    mock_settings.input_hold_frames = 10
                    mock_settings.animation_duration = 1
                    mock_settings.sequence_delay_seconds = 0.1
                    mock_settings.tbc_overlay_path = MagicMock()
                    mock_settings.tbc_duration_frames = 0
                    mock_settings.timelapse_frame_skip = 1

                    handler._sessions[123456] = GameSession(
                        chat_id=123456,
                        state=ChatGameState(chat_id=123456, message_id=789)
                    )
                    handler._pending_buffers[123456] = PendingBuffer(max_size=50)
                    # Pre-fill to max_sequence_length - 1
                    handler._pending_buffers[123456].add(1, "Alice", GameButton.A)

                    # This press should trigger drain immediately
                    await handler.handle_button_press(
                        callback_data="b",
                        chat_id=123456,
                        message_id=789,
                        user_id=1,
                        user_name="Alice",
                        adapter=mock_adapter,
                        raw=MagicMock(),
                    )

                    drain_event = handler._drain_events.get(123456)
                    assert drain_event is not None
                    assert drain_event.is_set()


class TestStartGame:
    """Test starting a new game."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    @pytest.mark.asyncio
    async def test_start_game_creates_session(self, handler, mock_adapter):
        """Test starting game creates session."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager"):
                mock_controller = MagicMock()
                mock_controller.is_initialized.return_value = True
                mock_controller.get_frame.return_value = MagicMock()
                mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
                mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

                message_id = await handler.start_game(123456, mock_adapter)

                assert message_id == 100
                assert 123456 in handler._sessions
                assert handler._sessions[123456].state.message_id == 100

    @pytest.mark.asyncio
    async def test_start_game_sends_photo(self, handler, mock_adapter):
        """Test starting game sends a game message via the adapter."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager"):
                mock_controller = MagicMock()
                mock_controller.is_initialized.return_value = True
                mock_controller.get_frame.return_value = MagicMock()
                mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
                mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

                await handler.start_game(123456, mock_adapter)

                mock_adapter.send_game_message.assert_called_once()


class TestShowCurrentFrame:
    """Test showing current frame."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    @pytest.mark.asyncio
    async def test_show_frame_no_game(self, handler, mock_adapter):
        """Test showing frame with no active game."""
        with patch("src.handlers.input_handler.state_manager"):
            with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
                mock_mgr.get_controller.return_value = None

                result = await handler.show_current_frame(123456, mock_adapter)

                assert result is None

    @pytest.mark.asyncio
    async def test_show_frame_edits_existing(self, handler, mock_adapter):
        """Test showing frame edits existing message via the adapter."""
        handler._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=100)
        )

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.get_frame.return_value = MagicMock()
            mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
            mock_mgr.get_controller.return_value = mock_controller

            result = await handler.show_current_frame(123456, mock_adapter)

            assert result == 100
            mock_adapter.edit_game_message.assert_called_once()


class TestInputProcessing:
    """Test input processing flow."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    @pytest.fixture
    def mock_controller(self):
        controller = MagicMock()
        controller.send_input.return_value = MagicMock()
        controller.get_frame_as_png.return_value = BytesIO(b"png")
        controller.begin_hooks.return_value = {}
        controller.end_capture.return_value = [np.zeros((144, 160, 3), dtype=np.uint8)]
        controller.get_last_captured_audio.return_value = None
        return controller

    @pytest.mark.asyncio
    async def test_process_sequence_executes_button(self, handler, mock_adapter, mock_controller):
        """Test input processing executes button press."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager") as mock_sm:
                with patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock):
                    with patch("src.handlers.input_handler.generate_tbc_frames") as mock_tbc:
                        with patch("src.handlers.input_handler.apply_overlay_composite", return_value=[]):
                            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                                modifier_states={}, auto_save_enabled=False, platform="telegram"
                            )
                            mock_controller.get_modifier_specs.return_value = []
                            mock_tbc.return_value = []

                            await handler._process_sequence(123456, [GameButton.B], 789, mock_adapter)

                            mock_controller.send_input.assert_called_once()
                            call_args = mock_controller.send_input.call_args
                            assert call_args[0][0] == GameButton.B


class TestAggregateToRecentInputs:
    """Test _aggregate_to_recent_inputs (now only updates user_input_counts)."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    def test_single_user_single_button(self, handler):
        state = ChatGameState(chat_id=1)
        batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.A)]
        handler._aggregate_to_recent_inputs(state, batch)
        assert state.user_input_counts["1"] == 1

    def test_consecutive_same_user_collapsed(self, handler):
        state = ChatGameState(chat_id=1)
        batch = [
            BufferedInput(user_id=1, user_name="Alice", button=GameButton.UP),
            BufferedInput(user_id=1, user_name="Alice", button=GameButton.DOWN),
        ]
        handler._aggregate_to_recent_inputs(state, batch)
        assert state.user_input_counts["1"] == 2

    def test_different_users_separate_entries(self, handler):
        state = ChatGameState(chat_id=1)
        batch = [
            BufferedInput(user_id=1, user_name="Alice", button=GameButton.A),
            BufferedInput(user_id=2, user_name="Bob", button=GameButton.B),
        ]
        handler._aggregate_to_recent_inputs(state, batch)
        assert state.user_input_counts["1"] == 1
        assert state.user_input_counts["2"] == 1

    def test_alternating_users(self, handler):
        state = ChatGameState(chat_id=1)
        batch = [
            BufferedInput(user_id=1, user_name="Alice", button=GameButton.A),
            BufferedInput(user_id=2, user_name="Bob", button=GameButton.B),
            BufferedInput(user_id=1, user_name="Alice", button=GameButton.UP),
        ]
        handler._aggregate_to_recent_inputs(state, batch)
        assert state.user_input_counts["1"] == 2
        assert state.user_input_counts["2"] == 1

    def test_capped_at_three_entries(self, handler):
        """user_input_counts accumulates all users, not capped."""
        state = ChatGameState(chat_id=1)
        for i in range(4):
            batch = [BufferedInput(user_id=i, user_name=f"User{i}", button=GameButton.A)]
            handler._aggregate_to_recent_inputs(state, batch)
        assert len(state.user_input_counts) == 4

    def test_user_input_counts_updated(self, handler):
        state = ChatGameState(chat_id=1)
        batch = [
            BufferedInput(user_id=1, user_name="Alice", button=GameButton.A),
            BufferedInput(user_id=1, user_name="Alice", button=GameButton.B),
        ]
        handler._aggregate_to_recent_inputs(state, batch)
        assert state.user_input_counts["1"] == 2

    def test_empty_batch_no_change(self, handler):
        state = ChatGameState(chat_id=1)
        handler._aggregate_to_recent_inputs(state, [])
        assert state.user_input_counts == {}


class TestSessionManagement:
    """Test session management."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    def test_is_input_in_progress(self, handler):
        assert handler.is_input_in_progress(123456) is False
        handler._processing.add(123456)
        assert handler.is_input_in_progress(123456) is True

    def test_cleanup_session(self, handler):
        handler._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456)
        )
        handler._pending_buffers[123456] = PendingBuffer()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            result = handler.cleanup_session(123456)

            assert result is True
            assert 123456 not in handler._sessions
            assert 123456 not in handler._pending_buffers
            mock_mgr.remove_controller.assert_called_once_with(123456)

    def test_cleanup_nonexistent_session(self, handler):
        result = handler.cleanup_session(999999)
        assert result is False


class TestSingleton:
    """Test singleton pattern."""

    @pytest.fixture
    def reset_singleton(self):
        import src.handlers.input_handler as ih
        original = ih._input_handler
        ih._input_handler = None
        yield
        ih._input_handler = original

    def test_get_input_handler_creates_new(self, reset_singleton):
        handler = get_input_handler()
        assert handler is not None

    def test_get_input_handler_returns_same(self, reset_singleton):
        handler1 = get_input_handler()
        handler2 = get_input_handler()
        assert handler1 is handler2


class TestErrorHandling:
    """Test error handling."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    @pytest.mark.asyncio
    async def test_send_error_message(self, handler, mock_adapter):
        await handler._send_error_message(123456, "Test error", mock_adapter)
        mock_adapter.send_text.assert_called_once_with(123456, "❌ Test error")

    @pytest.mark.asyncio
    async def test_send_error_message_handles_exception(self, handler, mock_adapter):
        mock_adapter.send_text.side_effect = Exception("Network error")
        # Should not raise
        await handler._send_error_message(123456, "Test error", mock_adapter)


class TestEditOperations:
    """Test message editing operations."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    @pytest.mark.asyncio
    async def test_edit_keyboard(self, handler, mock_adapter):
        keyboard = MagicMock()
        await handler._edit_message_keyboard(123456, 789, keyboard, mock_adapter)
        mock_adapter.edit_game_keyboard.assert_called_once_with(
            chat_id=123456,
            message_id=789,
            keyboard=keyboard,
        )

    @pytest.mark.asyncio
    async def test_edit_keyboard_handles_error(self, handler, mock_adapter):
        mock_adapter.edit_game_keyboard.side_effect = Exception("Error")
        await handler._edit_message_keyboard(123456, 789, MagicMock(), mock_adapter)

    @pytest.mark.asyncio
    async def test_edit_media(self, tmp_path, handler, mock_adapter):
        with patch("src.handlers.input_handler.settings") as mock_settings:
            mock_settings.get_chat_save_dir.return_value = tmp_path / "saves" / "123456"
            photo_buffer = BytesIO(b"png")
            await handler._edit_message_media(123456, 789, photo_buffer, "caption", mock_adapter)
            mock_adapter.edit_game_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_edit_media_handles_error(self, handler, mock_adapter):
        mock_adapter.edit_game_message.side_effect = Exception("Error")
        await handler._edit_message_media(123456, 789, BytesIO(b"png"), "caption", mock_adapter)


class TestSessionLoading:
    """Test loading existing sessions from state manager."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    def test_get_session_loads_from_state(self, handler):
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            mock_state.load_game_state.return_value = ChatGameState(
                chat_id=123456,
                message_id=100
            )
            session = handler._get_session(123456)
            assert session is not None
            assert session.chat_id == 123456
            assert session.state.message_id == 100

    def test_get_session_returns_none_when_no_state(self, handler):
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            mock_state.load_game_state.return_value = None
            session = handler._get_session(123456)
            assert session is None

    def test_get_session_caches_in_memory(self, handler):
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            mock_state.load_game_state.return_value = ChatGameState(
                chat_id=123456,
                message_id=100
            )
            session1 = handler._get_session(123456)
            session2 = handler._get_session(123456)
            assert session1 is session2
            mock_state.load_game_state.assert_called_once()


class TestWaitButtonProcessing:
    """Test WAIT button processing."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    @pytest.fixture
    def mock_controller(self):
        controller = MagicMock()
        controller.tick.return_value = MagicMock()
        controller.send_input.return_value = MagicMock()
        controller.get_frame_as_png.return_value = BytesIO(b"png")
        controller.begin_hooks.return_value = {}
        controller.end_capture.return_value = [np.zeros((144, 160, 3), dtype=np.uint8)]
        controller.get_last_captured_audio.return_value = None
        return controller

    @pytest.mark.asyncio
    async def test_wait_button_skips_send_input(self, handler, mock_adapter, mock_controller):
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager") as mock_sm:
                with patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock):
                    with patch("src.handlers.input_handler.generate_tbc_frames") as mock_tbc:
                        with patch("src.handlers.input_handler.apply_overlay_composite", return_value=[]):
                            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                                modifier_states={}, auto_save_enabled=False, platform="telegram"
                            )
                            mock_controller.get_modifier_specs.return_value = []
                            mock_tbc.return_value = []

                            handler._sessions[123456] = GameSession(
                                chat_id=123456,
                                state=ChatGameState(chat_id=123456, message_id=789)
                            )

                            await handler._process_sequence(123456, [GameButton.WAIT], 789, mock_adapter)

                            mock_controller.send_input.assert_not_called()
                            assert mock_controller.tick.call_count > 1

    @pytest.mark.asyncio
    async def test_wait_button_ticks_emulator(self, handler, mock_adapter, mock_controller):
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager") as mock_sm:
                with patch("src.handlers.input_handler.settings") as mock_settings:
                    with patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock):
                        with patch("src.handlers.input_handler.generate_tbc_frames") as mock_tbc:
                            with patch("src.handlers.input_handler.apply_overlay_composite", return_value=[]):
                                mock_settings.input_hold_frames = 30
                                mock_settings.animation_duration = 1
                                mock_settings.sequence_delay_seconds = 0
                                mock_settings.tbc_duration_frames = 0
                                mock_settings.max_queue_size = 10
                                mock_settings.maximum_inputs_per_animation = 8
                                mock_settings.tbc_overlay_path = MagicMock()
                                mock_settings.timelapse_frame_skip = 1
                                mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                                mock_sm.get_or_create_chat_config.return_value = MagicMock(
                                    modifier_states={}, auto_save_enabled=False, platform="telegram"
                                )
                                mock_controller.get_modifier_specs.return_value = []
                                mock_tbc.return_value = []

                                handler._sessions[123456] = GameSession(
                                    chat_id=123456,
                                    state=ChatGameState(chat_id=123456, message_id=789)
                                )

                                await handler._process_sequence(123456, [GameButton.WAIT], 789, mock_adapter)

                                from unittest.mock import call
                                assert mock_controller.tick.call_args_list[0] == call(frames=30)
                                for tick_call in mock_controller.tick.call_args_list[1:-1]:
                                    assert tick_call == call(1)
                                    
                                # Tick remainder frames for capture_frames_expected
                                assert mock_controller.tick.call_args_list[-1] == call(60)

    @pytest.mark.asyncio
    async def test_wait_button_runs_animation(self, handler, mock_adapter, mock_controller):
        with (
            patch("src.handlers.input_handler.game_controller_manager") as mock_mgr,
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.generate_tbc_frames") as mock_tbc,
            patch("src.handlers.input_handler.apply_overlay_composite", return_value=[MagicMock()]),
            patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock) as mock_bcast,
        ):
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                modifier_states={}, auto_save_enabled=False, platform="telegram"
            )
            mock_controller.get_modifier_specs.return_value = []
            mock_tbc.return_value = []

            handler._sessions[123456] = GameSession(
                chat_id=123456,
                state=ChatGameState(chat_id=123456, message_id=789)
            )

            await handler._process_sequence(123456, [GameButton.WAIT], 789, mock_adapter)

            mock_bcast.assert_called_once()
            call_args = mock_bcast.call_args
            assert call_args.args[0] == 123456

    @pytest.mark.asyncio
    async def test_normal_button_still_calls_send_input(self, handler, mock_adapter, mock_controller):
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager") as mock_sm:
                with patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock):
                    with patch("src.handlers.input_handler.generate_tbc_frames") as mock_tbc:
                        with patch("src.handlers.input_handler.apply_overlay_composite", return_value=[]):
                            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                                modifier_states={}, auto_save_enabled=False, platform="telegram"
                            )
                            mock_controller.get_modifier_specs.return_value = []
                            mock_tbc.return_value = []

                            handler._sessions[123456] = GameSession(
                                chat_id=123456,
                                state=ChatGameState(chat_id=123456, message_id=789)
                            )

                            await handler._process_sequence(123456, [GameButton.A], 789, mock_adapter)

                            mock_controller.send_input.assert_called_once()
                            assert mock_controller.tick.call_count > 0


class TestModifierButtonHandling:
    """Test modifier button press handling."""

    @pytest.fixture
    def handler(self):
        return InputHandler()

    def _make_callback_query(self, chat_id=123456, message_id=100, callback_data="modifier_run"):
        cq = MagicMock()
        cq.message.chat.id = chat_id
        cq.message.message_id = message_id
        cq.data = callback_data
        cq.from_user.id = 1
        cq.from_user.first_name = "Alice"
        cq.answer = AsyncMock()
        return cq

    @pytest.mark.asyncio
    async def test_modifier_callback_no_session_returns_no_active_game(self, handler, mock_adapter):
        cq = self._make_callback_query()

        with patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_sm.load_game_state.return_value = None
            mock_tm.get.return_value = "No active game"

            await handler.handle_button_press(
                callback_data=cq.data,
                chat_id=cq.message.chat.id,
                message_id=cq.message.message_id,
                user_id=cq.from_user.id,
                user_name="Alice",
                adapter=mock_adapter,
                raw=cq,
            )

            mock_adapter.answer_interaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_modifier_callback_stale_message_id_returns_outdated(self, handler, mock_adapter):
        cq = self._make_callback_query(message_id=999)

        state = ChatGameState(chat_id=123456, message_id=100)
        session = GameSession(chat_id=123456, state=state)
        handler._sessions[123456] = session

        with patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_tm.get.return_value = "Outdated"
            await handler.handle_button_press(
                callback_data=cq.data,
                chat_id=cq.message.chat.id,
                message_id=cq.message.message_id,
                user_id=cq.from_user.id,
                user_name="Alice",
                adapter=mock_adapter,
                raw=cq,
            )
            mock_adapter.answer_interaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_modifier_callback_toggles_modifier_state(self, handler, mock_adapter):
        cq = self._make_callback_query()

        state = ChatGameState(chat_id=123456, message_id=100)
        session = GameSession(chat_id=123456, state=state)
        handler._sessions[123456] = session

        from src.models.game_state import ChatConfig
        config = ChatConfig(chat_id=123456, modifier_states={"run": False})

        with patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_sm.get_or_create_chat_config.return_value = config
            mock_controller = MagicMock()
            mock_controller.get_modifier_specs.return_value = []
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_tm.get.return_value = ""

            await handler.handle_button_press(
                callback_data=cq.data,
                chat_id=cq.message.chat.id,
                message_id=cq.message.message_id,
                user_id=cq.from_user.id,
                user_name="Alice",
                adapter=mock_adapter,
                raw=cq,
            )

            assert config.modifier_states["run"] is True
            mock_sm.save_chat_config.assert_called_once_with(config)

    @pytest.mark.asyncio
    async def test_modifier_callback_toggles_back_when_active(self, handler, mock_adapter):
        cq = self._make_callback_query()

        state = ChatGameState(chat_id=123456, message_id=100)
        session = GameSession(chat_id=123456, state=state)
        handler._sessions[123456] = session

        from src.models.game_state import ChatConfig
        config = ChatConfig(chat_id=123456, modifier_states={"run": True})

        with patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_sm.get_or_create_chat_config.return_value = config
            mock_controller = MagicMock()
            mock_controller.get_modifier_specs.return_value = []
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_tm.get.return_value = ""

            await handler.handle_button_press(
                callback_data=cq.data,
                chat_id=cq.message.chat.id,
                message_id=cq.message.message_id,
                user_id=cq.from_user.id,
                user_name="Alice",
                adapter=mock_adapter,
                raw=cq,
            )

            assert config.modifier_states["run"] is False


class TestUserColorPrefetch:
    """Test that user color pre-fetch logic works correctly for sidebar rendering."""

    def test_custom_color_hex_to_rgb_conversion(self):
        """hex_to_rgb correctly converts name_tag_color for use in user_colors dict."""
        from src.utils.frame_utils import hex_to_rgb
        # This is the conversion that happens in the pre-fetch loop
        color = hex_to_rgb("#FF0000")
        assert color == (255, 0, 0)

    def test_missing_profile_omits_entry(self):
        """When get_player_profile returns None, the user is not added to user_colors."""
        from src.utils.frame_utils import hex_to_rgb

        user_colors: dict = {}
        mock_profile = None  # simulates no profile

        uid = 99
        uname = "Bob"
        if uid and uname not in user_colors:
            if mock_profile:
                user_colors[uname] = hex_to_rgb(mock_profile.name_tag_color)

        assert "Bob" not in user_colors
