"""Tests for input handler overlay integration.

Tests for the frame offset tracking, append_recent_input calls,
and pre_existing_inputs passing to timelapse_queue.enqueue().
"""

import os
import pytest
from datetime import datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, call, patch

# Set environment variables before importing
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
os.environ["WEBHOOK_URL"] = "https://test.example.com"
os.environ["WEBHOOK_SECRET"] = "test_secret_1234567890"

from src.handlers.input_handler import InputHandler
from src.models.game_state import ChatGameState, GameButton, GameSession
from src.models.input_queue import BufferedInput


def _make_batch(buttons_and_users):
    """Create a batch of BufferedInputs from (button, user_id, user_name) tuples."""
    batch = []
    for button, user_id, user_name in buttons_and_users:
        bi = BufferedInput(user_id=user_id, user_name=user_name, button=button)
        batch.append(bi)
    return batch


def _make_mock_controller():
    controller = MagicMock()
    controller.send_input.return_value = None
    controller.get_frame_as_png.return_value = BytesIO(b"png")
    controller.begin_hooks.return_value = {}
    controller.end_capture.return_value = [MagicMock()]
    controller.get_last_captured_audio.return_value = None
    controller.get_modifier_specs.return_value = []
    return controller


def _make_mock_config(feature_flags=None):
    config = MagicMock()
    config.modifier_states = {}
    config.auto_save_enabled = False
    config.feature_flags = feature_flags or {}
    return config


class TestProcessBatchAppendsRecentInput:
    """Test that _process_batch calls append_recent_input once per button."""

    @pytest.fixture
    def handler(self):
        h = InputHandler()
        h._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=789),
        )
        return h

    @pytest.mark.asyncio
    async def test_process_batch_calls_append_recent_input_per_button(
        self, handler, mock_adapter
    ):
        """append_recent_input is called once per button in the batch."""
        batch = _make_batch([
            (GameButton.A, 1, "Alice"),
            (GameButton.B, 2, "Bob"),
        ])

        mock_controller = _make_mock_controller()
        mock_config = _make_mock_config()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_settings:

            mock_settings.input_hold_frames = 10
            mock_settings.animation_duration = 0
            mock_settings.sequence_delay_seconds = 0.0
            mock_settings.tbc_duration_frames = 0
            mock_settings.tbc_overlay_path = MagicMock()
            mock_settings.timelapse_frame_skip = 1
            mock_settings.max_queue_size = 50

            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_sm.get_recent_inputs_for_overlay.return_value = []
            mock_sm.append_recent_input.return_value = None

            await handler._process_batch(123456, 789, batch, mock_adapter)

            assert mock_sm.append_recent_input.call_count == 2
            # Verify called with correct button values
            calls = mock_sm.append_recent_input.call_args_list
            buttons_called = [c.kwargs["button"] for c in calls]
            assert "a" in buttons_called
            assert "b" in buttons_called


class TestProcessBatchTracksFrameOffsets:
    """Test that _process_batch computes correct frame offsets and passes them to enqueue."""

    @pytest.fixture
    def handler(self):
        h = InputHandler()
        h._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=789),
        )
        return h

    @pytest.mark.asyncio
    async def test_process_batch_tracks_frame_offsets(self, handler, mock_adapter):
        """enqueue receives new_inputs_with_offsets as a list of (dict, int) tuples."""
        batch = _make_batch([
            (GameButton.A, 1, "Alice"),
            (GameButton.B, 2, "Bob"),
        ])

        mock_controller = _make_mock_controller()
        mock_config = _make_mock_config(feature_flags={"realtime_recaps": True})
        mock_enqueue = AsyncMock()
        mock_tq = MagicMock()
        mock_tq.enqueue = mock_enqueue

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_settings, \
             patch("src.tasks.timelapse_encoder.timelapse_queue", mock_tq):

            mock_settings.input_hold_frames = 10
            mock_settings.animation_duration = 0
            mock_settings.sequence_delay_seconds = 0.0
            mock_settings.tbc_duration_frames = 0
            mock_settings.tbc_overlay_path = MagicMock()
            mock_settings.timelapse_frame_skip = 1
            mock_settings.max_queue_size = 50

            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_sm.get_recent_inputs_for_overlay.return_value = []
            mock_sm.append_recent_input.return_value = None

            await handler._process_batch(123456, 789, batch, mock_adapter)

            mock_enqueue.assert_called_once()
            call_kwargs = mock_enqueue.call_args.kwargs
            niwo = call_kwargs.get("new_inputs_with_offsets")
            assert niwo is not None
            assert len(niwo) == 2
            # Each entry should be a (dict, int) tuple
            for entry in niwo:
                input_dict, frame_offset = entry
                assert isinstance(input_dict, dict)
                assert isinstance(frame_offset, int)
                assert "user_id" in input_dict
                assert "user_name" in input_dict
                assert "button" in input_dict
                assert "timestamp" in input_dict


class TestProcessBatchPassesPreExistingInputs:
    """Test that _process_batch fetches and passes pre_existing_inputs to enqueue."""

    @pytest.fixture
    def handler(self):
        h = InputHandler()
        h._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=789),
        )
        return h

    @pytest.mark.asyncio
    async def test_process_batch_passes_pre_existing_inputs(self, handler, mock_adapter):
        """enqueue receives the pre_existing_inputs returned by get_recent_inputs_for_overlay."""
        pre_existing = [
            {"user_id": 99, "user_name": "OldUser", "button": "up", "timestamp": "2026-01-01T00:00:00"},
        ]

        batch = _make_batch([
            (GameButton.A, 1, "Alice"),
        ])

        mock_controller = _make_mock_controller()
        mock_config = _make_mock_config(feature_flags={"realtime_recaps": True})
        mock_enqueue = AsyncMock()

        mock_tq = MagicMock()
        mock_tq.enqueue = mock_enqueue

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_settings, \
             patch("src.tasks.timelapse_encoder.timelapse_queue", mock_tq):

            mock_settings.input_hold_frames = 10
            mock_settings.animation_duration = 0
            mock_settings.sequence_delay_seconds = 0.0
            mock_settings.tbc_duration_frames = 0
            mock_settings.tbc_overlay_path = MagicMock()
            mock_settings.timelapse_frame_skip = 1
            mock_settings.max_queue_size = 50

            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_sm.get_recent_inputs_for_overlay.return_value = pre_existing
            mock_sm.append_recent_input.return_value = None

            await handler._process_batch(123456, 789, batch, mock_adapter)

            mock_enqueue.assert_called_once()
            call_kwargs = mock_enqueue.call_args.kwargs
            assert call_kwargs.get("pre_existing_inputs") == pre_existing


class TestProcessBatchPreExistingCappedAt30:
    """Test that get_recent_inputs_for_overlay is called with limit=30."""

    @pytest.fixture
    def handler(self):
        h = InputHandler()
        h._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=789),
        )
        return h

    @pytest.mark.asyncio
    async def test_process_batch_pre_existing_capped_at_30(self, handler, mock_adapter):
        """get_recent_inputs_for_overlay is called with limit=30."""
        batch = _make_batch([
            (GameButton.A, 1, "Alice"),
        ])

        mock_controller = _make_mock_controller()
        mock_config = _make_mock_config()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_settings:

            mock_settings.input_hold_frames = 10
            mock_settings.animation_duration = 0
            mock_settings.sequence_delay_seconds = 0.0
            mock_settings.tbc_duration_frames = 0
            mock_settings.tbc_overlay_path = MagicMock()
            mock_settings.timelapse_frame_skip = 1
            mock_settings.max_queue_size = 50

            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_sm.get_recent_inputs_for_overlay.return_value = []
            mock_sm.append_recent_input.return_value = None

            with patch("src.tasks.timelapse_encoder.timelapse_queue"):
                await handler._process_batch(123456, 789, batch, mock_adapter)

            mock_sm.get_recent_inputs_for_overlay.assert_called_once_with(123456, limit=30)
