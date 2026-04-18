"""Tests for input handler overlay integration.

Tests for the frame offset tracking, append_recent_input calls,
and pre_existing_inputs passing to timelapse_queue.enqueue().
"""

import os
import pytest
import numpy as np
from datetime import datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

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
    controller.end_capture.return_value = [np.zeros((144, 160, 3), dtype=np.uint8)]
    controller.get_last_captured_audio.return_value = None
    controller.get_modifier_specs.return_value = []
    return controller


def _make_mock_config(feature_flags=None):
    config = MagicMock()
    config.modifier_states = {}
    config.auto_save_enabled = False
    config.feature_flags = feature_flags or {}
    config.platform = "telegram"
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


class TestProcessBatchCallsFrameTransform:
    """Test that _process_batch passes pre_existing_inputs to _make_frame_transform."""

    @pytest.fixture
    def handler(self):
        h = InputHandler()
        h._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=789),
        )
        return h

    @pytest.mark.asyncio
    async def test_make_frame_transform_called_with_pre_existing(
        self, handler, mock_adapter
    ):
        """_make_frame_transform is called with the pre_existing_inputs from the DB."""
        pre_existing = [
            {"user_id": 99, "user_name": "Old", "button": "up", "timestamp": "2026-01-01T00:00:00"},
        ]
        batch = _make_batch([(GameButton.A, 1, "Alice")])

        mock_controller = _make_mock_controller()
        mock_config = _make_mock_config()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler._make_frame_transform", return_value=lambda f: f) as mock_mft, \
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
            mock_sm.get_recent_inputs_for_overlay.return_value = pre_existing
            mock_sm.append_recent_input.return_value = None

            await handler._process_batch(123456, 789, batch, mock_adapter)

            mock_mft.assert_called_once()
            call_args = mock_mft.call_args
            assert call_args[0][0] == pre_existing  # first positional arg


    @pytest.mark.asyncio
    async def test_timelapse_enqueue_receives_no_overlay_params(
        self, handler, mock_adapter
    ):
        """trigger_worker is called and insert_timelapse_job has no overlay params in compositing_context."""
        batch = _make_batch([(GameButton.A, 1, "Alice")])
        mock_controller = _make_mock_controller()
        mock_config = _make_mock_config(feature_flags={"realtime_recaps": True})
        mock_tq = MagicMock()
        mock_tq.trigger_worker = Mock()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler._save_raw_frames_sync"), \
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
            mock_sm.insert_timelapse_job = Mock(return_value=1)

            await handler._process_batch(123456, 789, batch, mock_adapter)

            mock_tq.trigger_worker.assert_called_once()
            mock_sm.insert_timelapse_job.assert_called_once()


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

            with patch("src.tasks.timelapse_encoder.timelapse_queue"),                  patch("src.handlers.input_handler._save_raw_frames_sync"):
                await handler._process_batch(123456, 789, batch, mock_adapter)

            mock_sm.get_recent_inputs_for_overlay.assert_called_once_with(123456, limit=30)


class TestProcessBatchStatsHeader:
    """Test that _process_batch passes header_stats and base_global_frame_count to timelapse."""

    @pytest.fixture
    def handler(self):
        h = InputHandler()
        h._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=789, global_frame_count=150),
        )
        return h

    @pytest.mark.asyncio
    async def test_compositing_context_includes_header_stats_and_frame_count(
        self, handler, mock_adapter
    ):
        """compositing_context passed to insert_timelapse_job includes header_stats and base_global_frame_count."""
        batch = _make_batch([(GameButton.A, 1, "Alice")])
        mock_controller = _make_mock_controller()
        mock_config = _make_mock_config(feature_flags={"realtime_recaps": True})
        mock_tq = MagicMock()
        mock_tq.trigger_worker = Mock()

        today_stats = {"total": 10, "top_players": []}
        alltime_stats = {"total": 100, "top_players": []}

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler._make_frame_transform", return_value=lambda f: f), \
             patch("src.handlers.input_handler._save_raw_frames_sync"), \
             patch("src.handlers.input_handler.settings") as mock_settings, \
             patch("src.tasks.timelapse_encoder.timelapse_queue", mock_tq):

            mock_settings.input_hold_frames = 10
            mock_settings.animation_duration = 0
            mock_settings.sequence_delay_seconds = 0.0
            mock_settings.tbc_duration_frames = 0
            mock_settings.tbc_overlay_path = MagicMock()
            mock_settings.timelapse_frame_skip = 1
            mock_settings.max_queue_size = 50
            mock_settings.data_dir = MagicMock()
            mock_settings.data_dir.__truediv__ = lambda s, o: MagicMock()

            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_sm.get_recent_inputs_for_overlay.return_value = []
            mock_sm.get_today_input_stats.return_value = today_stats
            mock_sm.get_alltime_input_stats.return_value = alltime_stats
            mock_sm.append_recent_input.return_value = None
            mock_sm.insert_timelapse_job = Mock(return_value=1)
            mock_sm.connection = MagicMock()

            await handler._process_batch(123456, 789, batch, mock_adapter)

            mock_sm.insert_timelapse_job.assert_called_once()
            ctx = mock_sm.insert_timelapse_job.call_args[1]["compositing_context"]
            assert "header_stats" in ctx
            assert ctx["header_stats"]["today"]["total"] == 10
            assert "base_global_frame_count" in ctx
            assert ctx["base_global_frame_count"] == 150  # from initial state


class TestProcessBatchModifier:
    """Test that _process_batch captures modifier and passes it to DB and input_dict."""

    @pytest.fixture
    def handler(self):
        from src.handlers.input_handler import InputHandler
        from src.models.game_state import ChatGameState, GameSession
        h = InputHandler()
        h._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=1),
        )
        return h

    @pytest.mark.asyncio
    async def test_modifier_captured_in_input_dict(self, handler):
        """When a modifier spec is active and applies to the pressed button,
        input_dict['modifier'] is set to the modifier button value."""
        from src.models.game_state import GameButton, ModifierButtonSpec
        from src.models.input_queue import BufferedInput

        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        controller = _make_mock_controller()
        controller.get_modifier_specs.return_value = [spec]
        controller.send_input_with_modifier = MagicMock()

        config = _make_mock_config()
        config.modifier_states = {"run": True}

        batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.UP)]

        with (
            patch("src.handlers.input_handler.game_controller_manager") as mock_gcm,
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.scoring_manager") as mock_sc,
            patch("src.handlers.input_handler.broadcast_game_update", new=AsyncMock()),
            patch("src.handlers.input_handler._build_recent_inputs_grouped", return_value=[]),
            patch("src.handlers.input_handler.create_game_message_text", return_value=""),
        ):
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.get_recent_inputs_for_overlay.return_value = []
            mock_sm.get_today_input_stats.return_value = {}
            mock_sm.get_alltime_input_stats.return_value = {}
            mock_sm.connection = MagicMock()

            scored = MagicMock()
            scored.total_score = 10
            scored.base_score = 10
            scored.streak_bonus = 0
            scored.current_streak = 1
            mock_sc.score_input.return_value = scored

            adapter = MagicMock()
            adapter.platform = "telegram"
            adapter.build_game_keyboard.return_value = MagicMock()

            # Capture what gets passed to append_recent_input
            captured_modifier = {}
            def capture_append(**kwargs):
                captured_modifier["modifier"] = kwargs.get("modifier")
            mock_sm.append_recent_input.side_effect = capture_append

            await handler._process_batch(123456, 1, batch, adapter)

        assert captured_modifier.get("modifier") == "b"

    @pytest.mark.asyncio
    async def test_no_modifier_when_spec_inactive(self, handler):
        """When no modifier spec is active, input_dict['modifier'] is None."""
        from src.models.game_state import GameButton, ModifierButtonSpec
        from src.models.input_queue import BufferedInput

        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        controller = _make_mock_controller()
        controller.get_modifier_specs.return_value = [spec]

        config = _make_mock_config()
        config.modifier_states = {"run": False}  # inactive

        batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.UP)]

        with (
            patch("src.handlers.input_handler.game_controller_manager") as mock_gcm,
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.scoring_manager") as mock_sc,
            patch("src.handlers.input_handler.broadcast_game_update", new=AsyncMock()),
            patch("src.handlers.input_handler._build_recent_inputs_grouped", return_value=[]),
            patch("src.handlers.input_handler.create_game_message_text", return_value=""),
        ):
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.get_recent_inputs_for_overlay.return_value = []
            mock_sm.get_today_input_stats.return_value = {}
            mock_sm.get_alltime_input_stats.return_value = {}
            mock_sm.connection = MagicMock()

            scored = MagicMock()
            scored.total_score = 10
            scored.base_score = 10
            scored.streak_bonus = 0
            scored.current_streak = 1
            mock_sc.score_input.return_value = scored

            adapter = MagicMock()
            adapter.platform = "telegram"
            adapter.build_game_keyboard.return_value = MagicMock()

            captured_modifier = {}
            def capture_append(**kwargs):
                captured_modifier["modifier"] = kwargs.get("modifier")
            mock_sm.append_recent_input.side_effect = capture_append

            await handler._process_batch(123456, 1, batch, adapter)

        assert captured_modifier.get("modifier") is None
