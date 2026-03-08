"""Tests for uncovered lines in input_handler.py."""
import asyncio
import os
import pytest
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from src.handlers.input_handler import InputHandler
from src.models.game_state import ChatConfig, ChatGameState, GameButton, GameSession
from src.models.input_queue import BufferedInput, PendingBuffer


# ── helpers ──────────────────────────────────────────────────────────────────

def _handler() -> InputHandler:
    return InputHandler()


def _session(chat_id=123456, message_id=789) -> GameSession:
    return GameSession(chat_id=chat_id, state=ChatGameState(chat_id=chat_id, message_id=message_id))


def _make_adapter(platform="telegram"):
    a = MagicMock()
    a.platform = platform
    a.answer_interaction = AsyncMock()
    a.edit_game_message = AsyncMock(return_value=None)
    a.edit_game_keyboard = AsyncMock()
    a.send_game_message = AsyncMock(return_value=200)
    a.send_text = AsyncMock()
    a.build_game_keyboard = MagicMock(return_value=MagicMock())
    return a


def _mock_controller_for_batch():
    c = MagicMock()
    c.save_state.return_value = b"state"
    c.begin_hooks.return_value = {}
    c.end_hooks.return_value = None
    c.get_modifier_specs.return_value = []
    c.get_frame.return_value = MagicMock()
    c.get_frame_as_png.return_value = BytesIO(b"png")
    c.send_input.return_value = None
    c.send_input_with_modifier.return_value = None
    c.load_state.return_value = None
    return c


def _base_settings_patch(mock_s):
    mock_s.input_hold_frames = 1
    mock_s.animation_duration = 0
    mock_s.sequence_delay_seconds = 0
    mock_s.tbc_duration_frames = 0
    mock_s.tbc_overlay_path = MagicMock()
    mock_s.timelapse_frame_skip = 1
    mock_s.max_queue_size = 50


# ── Task 1: Helper method unit tests ─────────────────────────────────────────

class TestRunBufferTimer:
    """Lines 92-94: _run_buffer_timer fires and sets drain event."""

    @pytest.mark.asyncio
    async def test_timer_sets_drain_event(self):
        handler = _handler()
        # Pre-create drain event
        event = asyncio.Event()
        handler._drain_events[1] = event

        with patch("src.handlers.input_handler.settings") as mock_s:
            mock_s.input_buffer_seconds = 0  # fire immediately
            await handler._run_buffer_timer(1)

        assert event.is_set()

    @pytest.mark.asyncio
    async def test_timer_does_nothing_when_no_drain_event(self):
        handler = _handler()
        # No drain event for chat_id=99
        with patch("src.handlers.input_handler.settings") as mock_s:
            mock_s.input_buffer_seconds = 0
            # Should not raise
            await handler._run_buffer_timer(99)


class TestCalculateProcessingTime:
    """Lines 100-104: _calculate_processing_time."""

    def test_single_button_returns_base_time(self):
        handler = _handler()
        with patch("src.handlers.input_handler.settings") as mock_s:
            mock_s.animation_duration = 2.0
            mock_s.sequence_delay_seconds = 0.5
            result = handler._calculate_processing_time([GameButton.A])
        assert result == 2.0

    def test_multi_button_adds_delay(self):
        handler = _handler()
        with patch("src.handlers.input_handler.settings") as mock_s:
            mock_s.animation_duration = 2.0
            mock_s.sequence_delay_seconds = 0.5
            result = handler._calculate_processing_time([GameButton.A, GameButton.B, GameButton.UP])
        # 2.0 + 0.5 * (3-1) = 3.0
        assert result == pytest.approx(3.0)


class TestGetMessageBaseText:
    """Lines 108-113: _get_message_base_text – exception path."""

    def test_returns_none_on_state_manager_exception(self):
        handler = _handler()
        with patch("src.handlers.input_handler.state_manager") as mock_sm:
            mock_sm.load_chat_config.side_effect = Exception("DB error")
            result = handler._get_message_base_text(123456)
        assert result is None


# ── Task 2: handle_button_press error paths ───────────────────────────────────

class TestHandleButtonPressErrorPaths:
    """Lines 197-230, 264-272: error paths in handle_button_press."""

    @pytest.mark.asyncio
    async def test_invalid_button_answer_raises_is_swallowed(self):
        """Lines 197-198: answer_interaction raises on invalid button."""
        handler = _handler()
        adapter = _make_adapter()
        adapter.answer_interaction.side_effect = Exception("network")

        with patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456):
            # Should not raise despite adapter failure
            await handler.handle_button_press(
                callback_data="invalid",
                chat_id=123456, message_id=789,
                user_id=1, user_name="Alice",
                adapter=adapter, raw=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_no_session_valid_button_sends_no_active_game(self):
        """Lines 205-207: valid button pressed but no session."""
        handler = _handler()
        adapter = _make_adapter()

        with patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456), \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_sm.load_game_state.return_value = None
            mock_tm.get.return_value = "No active game"

            await handler.handle_button_press(
                callback_data="a",
                chat_id=123456, message_id=789,
                user_id=1, user_name="Alice",
                adapter=adapter, raw=MagicMock(),
            )

        adapter.answer_interaction.assert_awaited_once()
        assert "No active game" in adapter.answer_interaction.call_args[0][1]

    @pytest.mark.asyncio
    async def test_no_session_answer_raises_is_swallowed(self):
        """Lines 208-209: answer_interaction raises in no-session path."""
        handler = _handler()
        adapter = _make_adapter()
        adapter.answer_interaction.side_effect = Exception("network")

        with patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456), \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_sm.load_game_state.return_value = None
            mock_tm.get.return_value = "No active game"
            # Should not raise
            await handler.handle_button_press(
                callback_data="a",
                chat_id=123456, message_id=789,
                user_id=1, user_name="Alice",
                adapter=adapter, raw=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_outdated_message_answer_raises_is_swallowed(self):
        """Lines 217-218: answer_interaction raises for outdated message."""
        handler = _handler()
        handler._sessions[123456] = _session(message_id=999)
        adapter = _make_adapter()
        adapter.answer_interaction.side_effect = Exception("network")

        with patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456), \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_tm.get.return_value = "Outdated"
            await handler.handle_button_press(
                callback_data="a",
                chat_id=123456, message_id=789,  # 789 != 999 → outdated
                user_id=1, user_name="Alice",
                adapter=adapter, raw=MagicMock(),
            )
        # no raise = success

    @pytest.mark.asyncio
    async def test_buffer_add_failure_answers_with_error(self):
        """Lines 226-230: buffer.add returns False (buffer full)."""
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()

        # Simulate a full buffer by patching PendingBuffer.add
        full_buffer = MagicMock()
        full_buffer.add.return_value = (False, ("game.queue_full", {}))
        full_buffer.total_buttons.return_value = 10
        handler._pending_buffers[123456] = full_buffer

        with patch("src.handlers.input_handler.state_manager"), \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456), \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_tm.get.return_value = "Queue full"

            await handler.handle_button_press(
                callback_data="a",
                chat_id=123456, message_id=789,
                user_id=1, user_name="Alice",
                adapter=adapter, raw=MagicMock(),
            )

        adapter.answer_interaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_queue_start_exception_sends_error_message(self):
        """Lines 264-266: exception starting the queue loop sends error."""
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()
        # Make answer_interaction raise so we hit the except in the "not processing" branch
        adapter.answer_interaction.side_effect = Exception("forced error")

        with patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456), \
             patch("src.handlers.input_handler.settings") as mock_s, \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=123456)
            mock_sm.load_game_state.return_value = None
            mock_tm.get.return_value = "Processing"
            mock_s.max_queue_size = 50
            mock_s.max_sequence_length = 100

            await handler.handle_button_press(
                callback_data="a",
                chat_id=123456, message_id=789,
                user_id=1, user_name="Alice",
                adapter=adapter, raw=MagicMock(),
            )

        # Error message should have been sent
        adapter.send_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_processing_answer_raises_is_swallowed(self):
        """Lines 271-272: answer_interaction raises in already-processing branch."""
        handler = _handler()
        handler._sessions[123456] = _session()
        handler._processing.add(123456)
        adapter = _make_adapter()
        adapter.answer_interaction.side_effect = Exception("network")

        buffer = PendingBuffer(max_size=50)
        buffer.add(1, "Alice", GameButton.A)
        handler._pending_buffers[123456] = buffer

        with patch("src.handlers.input_handler.state_manager"), \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456), \
             patch("src.handlers.input_handler.translation_manager") as mock_tm, \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_tm.get.return_value = "Queue position"
            mock_s.max_queue_size = 50
            mock_s.max_sequence_length = 100
            # Should not raise
            await handler.handle_button_press(
                callback_data="b",
                chat_id=123456, message_id=789,
                user_id=1, user_name="Alice",
                adapter=adapter, raw=MagicMock(),
            )


# ── Task 3: Modifier button handler edge cases ────────────────────────────────

class TestHandleModifierButtonPressEdgeCases:
    """Lines 284, 298-300, 306-307: modifier handler edge cases."""

    @pytest.mark.asyncio
    async def test_called_directly_without_leader_resolves_leader(self):
        """Line 284: leader_id=None triggers get_leader_chat_id."""
        handler = _handler()
        adapter = _make_adapter()
        config = ChatConfig(chat_id=123456, modifier_states={})

        with patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456) as mock_leader, \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.save_chat_config = MagicMock()
            mock_controller = MagicMock()
            mock_controller.get_modifier_specs.return_value = []
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_tm.get.return_value = ""

            # Call without leader_id (None triggers the resolve)
            await handler._handle_modifier_button_press(
                raw=MagicMock(), chat_id=123456, message_id=789,
                key="run", adapter=adapter, leader_id=None
            )

        mock_leader.assert_called_once_with(123456)

    @pytest.mark.asyncio
    async def test_modifier_spec_found_uses_label_key(self):
        """Lines 298-300: matching spec → label translated and used."""
        from src.models.game_state import ModifierButtonSpec

        handler = _handler()
        adapter = _make_adapter()

        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="modifier.run.active",
            inactive_label_key="modifier.run.inactive",
        )
        config = ChatConfig(chat_id=123456, modifier_states={"run": False})

        with patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.save_chat_config = MagicMock()
            mock_controller = MagicMock()
            mock_controller.get_modifier_specs.return_value = [spec]
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_tm.get.return_value = "Run ON"

            await handler._handle_modifier_button_press(
                raw=MagicMock(), chat_id=123456, message_id=789,
                key="run", adapter=adapter, leader_id=123456
            )

        # After toggle, run is True → active_label_key used
        mock_tm.get.assert_any_call("modifier.run.active", 123456)
        adapter.answer_interaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_modifier_answer_raises_is_swallowed(self):
        """Lines 306-307: answer_interaction raises → error logged, no crash."""
        handler = _handler()
        adapter = _make_adapter()
        adapter.answer_interaction.side_effect = Exception("network")
        config = ChatConfig(chat_id=123456, modifier_states={})

        with patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.translation_manager") as mock_tm:
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.save_chat_config = MagicMock()
            mock_controller = MagicMock()
            mock_controller.get_modifier_specs.return_value = []
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_tm.get.return_value = ""

            # Should not raise
            await handler._handle_modifier_button_press(
                raw=MagicMock(), chat_id=123456, message_id=789,
                key="run", adapter=adapter, leader_id=123456
            )


# ── Task 4: _process_queue_loop tests ────────────────────────────────────────

class TestProcessQueueLoop:
    """Lines 317-318, 324, 328-347: _process_queue_loop paths."""

    @pytest.mark.asyncio
    async def test_no_session_exits_immediately(self):
        """Lines 317-318: no session → discard chat from processing and return."""
        handler = _handler()
        adapter = _make_adapter()
        handler._processing.add(123456)

        with patch("src.handlers.input_handler.state_manager") as mock_sm:
            mock_sm.load_game_state.return_value = None
            await handler._process_queue_loop(123456, 789, adapter)

        assert 123456 not in handler._processing

    @pytest.mark.asyncio
    async def test_empty_buffer_exits_immediately(self):
        """Line 324: buffer is empty on first check → breaks without waiting."""
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()
        # No buffer pre-created → get_or_create returns empty PendingBuffer

        with patch("src.handlers.input_handler.settings") as mock_s, \
             patch("src.handlers.input_handler.state_manager") as mock_sm:
            mock_s.max_queue_size = 50
            mock_s.minimum_inputs_per_animation = 1
            mock_s.min_update_interval_seconds = 0
            mock_sm.save_game_state = MagicMock()

            await handler._process_queue_loop(123456, 789, adapter)

        assert 123456 not in handler._processing

    @pytest.mark.asyncio
    async def test_full_cycle_processes_batch_then_cleans_up(self):
        """Lines 328-347: drain event fires, batch is processed, state saved."""
        handler = _handler()
        session = _session()
        handler._sessions[123456] = session
        adapter = _make_adapter()

        # Pre-populate buffer
        buf = PendingBuffer(max_size=50)
        buf.add(1, "Alice", GameButton.A)
        handler._pending_buffers[123456] = buf

        # Pre-set the drain event so wait() returns immediately
        drain_event = asyncio.Event()
        drain_event.set()
        handler._drain_events[123456] = drain_event

        mock_controller = _mock_controller_for_batch()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=123456, auto_save_enabled=False
            )
            mock_sm.save_game_state = MagicMock()
            mock_s.maximum_inputs_per_animation = 8
            mock_s.max_queue_size = 50
            mock_s.min_update_interval_seconds = 0
            mock_s.input_hold_frames = 1
            mock_s.animation_duration = 0
            mock_s.sequence_delay_seconds = 0
            mock_s.tbc_duration_frames = 0
            mock_s.tbc_overlay_path = MagicMock()
            mock_s.timelapse_frame_skip = 1

            await handler._process_queue_loop(123456, 789, adapter)

        # Session should be cleaned up, state saved
        assert 123456 not in handler._processing
        mock_sm.save_game_state.assert_called()

    @pytest.mark.asyncio
    async def test_batch_exception_sets_animation_duration_none(self):
        """Lines 340-341: _process_batch raises → result defaults to None duration."""
        handler = _handler()
        session = _session()
        handler._sessions[123456] = session
        adapter = _make_adapter()

        buf = PendingBuffer(max_size=50)
        buf.add(1, "Alice", GameButton.A)
        handler._pending_buffers[123456] = buf

        drain_event = asyncio.Event()
        drain_event.set()
        handler._drain_events[123456] = drain_event

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_gcm.get_or_create_controller = AsyncMock(side_effect=Exception("controller broken"))
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=123456, auto_save_enabled=False)
            mock_sm.save_game_state = MagicMock()
            mock_s.maximum_inputs_per_animation = 8
            mock_s.max_queue_size = 50
            mock_s.min_update_interval_seconds = 0

            await handler._process_queue_loop(123456, 789, adapter)

        assert 123456 not in handler._processing


# ── Task 5: _process_batch edge cases ────────────────────────────────────────

class TestProcessBatchEdgeCases:
    """Lines 394-452, 482-522: _process_batch edge cases."""

    @pytest.mark.asyncio
    async def test_modifier_applied_to_button_calls_send_input_with_modifier(self):
        """Lines 394-398: modifier spec applies → send_input_with_modifier called."""
        from src.models.game_state import ModifierButtonSpec
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()

        spec = ModifierButtonSpec(
            key="run", modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="a", inactive_label_key="b"
        )
        controller = _mock_controller_for_batch()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            controller.get_modifier_specs.return_value = [spec]
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=123456, modifier_states={"run": True}, auto_save_enabled=False
            )
            _base_settings_patch(mock_s)

            batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.UP)]
            await handler._process_batch(123456, 789, batch, adapter)

        controller.send_input_with_modifier.assert_called_once_with(
            GameButton.UP, GameButton.B, frames=mock_s.input_hold_frames
        )
        controller.send_input.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_button_batch_captures_inter_button_delay_frames(self):
        """Lines 406-410: inter-button delay frames captured."""
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()
        controller = _mock_controller_for_batch()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=123456, modifier_states={}, auto_save_enabled=False
            )
            _base_settings_patch(mock_s)
            mock_s.sequence_delay_seconds = 0.1  # non-zero → delay loop runs
            mock_s.animation_duration = 0

            batch = [
                BufferedInput(user_id=1, user_name="Alice", button=GameButton.A),
                BufferedInput(user_id=1, user_name="Alice", button=GameButton.B),
            ]
            await handler._process_batch(123456, 789, batch, adapter)

        # tick() should have been called for inter-button delay
        assert controller.tick.called

    @pytest.mark.asyncio
    async def test_auto_press_a_fires_when_hook_threshold_met(self):
        """Lines 427-434: auto-press A loop fires when autoPressA._total increases."""
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()
        controller = _mock_controller_for_batch()

        # Start with _total=0 so threshold=60. Patch _tick_and_capture_animation_frames
        # to simulate the game advancing so _total reaches 60 (meeting the threshold).
        initial_context = {"autoPressA": {"_total": 0}}
        controller.begin_hooks.return_value = initial_context

        call_count = [0]
        def mutate_context(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: simulate autoPressA threshold being reached
                initial_context["autoPressA"]["_total"] = 60
            # Subsequent calls: _total stays at 60, threshold becomes 120, while exits

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=123456, modifier_states={}, auto_save_enabled=False
            )
            _base_settings_patch(mock_s)

            with patch.object(handler, "_tick_and_capture_animation_frames", side_effect=mutate_context):
                batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.A)]
                result = await handler._process_batch(123456, 789, batch, adapter)

        # send_input called at least twice: once for batch button, once for auto-press A
        assert controller.send_input.call_count >= 2

    @pytest.mark.asyncio
    async def test_dangerous_action_blocks_and_restores_state(self):
        """Lines 448-452: dangerousActions hook fires → state restored, error sent."""
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()
        controller = _mock_controller_for_batch()
        controller.begin_hooks.return_value = {"dangerousActions": {"_total": 1}}

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.translation_manager") as mock_tm, \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=123456, modifier_states={}, auto_save_enabled=False
            )
            mock_tm.get.return_value = "Blocked!"
            _base_settings_patch(mock_s)

            batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.A)]
            result = await handler._process_batch(123456, 789, batch, adapter)

        controller.load_state.assert_called_once_with(controller.save_state.return_value)
        assert result == {"animation_duration": None}
        adapter.send_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_broadcast_failure_is_logged_not_raised(self):
        """Lines 482-483: broadcast_game_update raises → logged as warning, processing continues."""
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()
        controller = _mock_controller_for_batch()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock) as mock_bcast, \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=123456, modifier_states={}, auto_save_enabled=False
            )
            mock_bcast.side_effect = Exception("broadcast failed")
            _base_settings_patch(mock_s)

            batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.A)]
            result = await handler._process_batch(123456, 789, batch, adapter)

        # Despite broadcast failure, we still get a result
        assert "animation_duration" in result

    @pytest.mark.asyncio
    async def test_timelapse_queue_enqueued_when_not_none(self):
        """Lines 490-495: timelapse_queue is not None → frames enqueued."""
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()
        controller = _mock_controller_for_batch()

        mock_timelapse_queue = MagicMock()
        mock_timelapse_queue.enqueue = AsyncMock()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.tasks.timelapse_encoder.timelapse_queue", mock_timelapse_queue), \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=123456, modifier_states={}, auto_save_enabled=False
            )
            _base_settings_patch(mock_s)

            batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.A)]
            await handler._process_batch(123456, 789, batch, adapter)

        mock_timelapse_queue.enqueue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_timelapse_enqueue_failure_is_swallowed(self):
        """Lines 496-497: timelapse enqueue raises → swallowed as warning."""
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()
        controller = _mock_controller_for_batch()

        mock_timelapse_queue = MagicMock()
        mock_timelapse_queue.enqueue = AsyncMock(side_effect=Exception("encoding failed"))

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.tasks.timelapse_encoder.timelapse_queue", mock_timelapse_queue), \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=123456, modifier_states={}, auto_save_enabled=False
            )
            _base_settings_patch(mock_s)

            batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.A)]
            # Should not raise
            await handler._process_batch(123456, 789, batch, adapter)

    @pytest.mark.asyncio
    async def test_animation_failure_falls_back_to_photo(self):
        """Lines 499-503: outer exception during animation → fallback to static photo.

        The outer except is triggered when the dynamic import of timelapse_queue
        fails (the module is in sys.modules but lacks the attribute).
        """
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()
        controller = _mock_controller_for_batch()

        # A module mock with restricted spec so accessing timelapse_queue raises AttributeError,
        # which Python converts to ImportError — triggering the outer except at line 499.
        fake_timelapse_module = MagicMock(spec=["__name__", "__spec__", "__loader__", "__package__"])
        fake_timelapse_module.__name__ = "src.tasks.timelapse_encoder"

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_s, \
             patch.dict("sys.modules", {"src.tasks.timelapse_encoder": fake_timelapse_module}):
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=123456, modifier_states={}, auto_save_enabled=False
            )
            _base_settings_patch(mock_s)

            batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.A)]
            await handler._process_batch(123456, 789, batch, adapter)

        # Fallback: edit_game_message called with photo
        adapter.edit_game_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_save_failure_is_logged_not_raised(self):
        """Lines 521-522: auto-save raises → swallowed as warning."""
        handler = _handler()
        handler._sessions[123456] = _session()
        adapter = _make_adapter()
        controller = _mock_controller_for_batch()
        # Make the second save_state (auto-save) raise
        controller.save_state.side_effect = [b"state", Exception("disk full")]

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.settings") as mock_s:
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=123456, modifier_states={}, auto_save_enabled=True
            )
            mock_sm.find_next_auto_save_slot.return_value = 1
            _base_settings_patch(mock_s)

            batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.A)]
            # Should not raise
            result = await handler._process_batch(123456, 789, batch, adapter)

        assert "animation_duration" in result


# ── Task 6: Animation frames + show_current_frame tests ──────────────────────

class TestTickAndCaptureAnimationFramesEarlyBreak:
    """Lines 142-145: early break when inputWaitCalls exceeds threshold."""

    def test_early_break_on_input_wait_loop(self):
        """inputWaitCalls._total exceeds threshold → loop breaks early.

        threshold = initial _total(0) + game_fps(60) = 60.
        After first tick, simulate _total jumping to 61 > 60 → break fires.
        """
        handler = _handler()
        controller = MagicMock()

        frames = []
        hook_context = {"inputWaitCalls": {"_total": 0}}

        # Simulate game advancing: first tick pushes _total past the threshold
        def mutate_on_tick(n):
            hook_context["inputWaitCalls"]["_total"] = 61  # > threshold of 60

        controller.tick.side_effect = mutate_on_tick

        handler._tick_and_capture_animation_frames(
            controller=controller,
            animation_frames=100,
            hook_context=hook_context,
            game_fps=60,
            capture_interval_frames=4,
            frames=frames,
        )

        # Should have stopped after 1 tick (break on frame 0)
        assert controller.tick.call_count == 1

    def test_no_early_break_when_below_threshold(self):
        """No early break when inputWaitCalls stays below threshold."""
        handler = _handler()
        controller = MagicMock()

        frames = []
        hook_context = {"inputWaitCalls": {"_total": 0}}

        handler._tick_and_capture_animation_frames(
            controller=controller,
            animation_frames=5,
            hook_context=hook_context,
            game_fps=60,
            capture_interval_frames=1,
            frames=frames,
        )

        # All 5 frames should have been processed
        assert controller.tick.call_count == 5


class TestShowCurrentFrameFallbackPaths:
    """Lines 661-676: show_current_frame when edit fails or no session."""

    @pytest.mark.asyncio
    async def test_edit_fails_falls_back_to_send(self):
        """Lines 661-664: edit_game_message raises → new message sent."""
        handler = _handler()
        handler._sessions[123456] = _session(message_id=100)
        adapter = _make_adapter()
        adapter.edit_game_message.side_effect = Exception("rate limit")
        adapter.send_game_message.return_value = 200

        mock_controller = MagicMock()
        mock_controller.is_initialized.return_value = True
        mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
        mock_controller.get_modifier_specs.return_value = []

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm:
            mock_gcm.get_controller.return_value = mock_controller
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=123456)
            mock_sm.load_chat_config.return_value = None

            result = await handler.show_current_frame(123456, adapter)

        assert result == 200
        adapter.send_game_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_session_creates_new_session_on_send(self):
        """Lines 673-674: no session → session created after send."""
        handler = _handler()
        adapter = _make_adapter()
        adapter.send_game_message.return_value = 300

        mock_controller = MagicMock()
        mock_controller.is_initialized.return_value = True
        mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
        mock_controller.get_modifier_specs.return_value = []

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm:
            mock_gcm.get_controller.return_value = mock_controller
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=123456)
            mock_sm.load_game_state.return_value = None
            mock_sm.load_chat_config.return_value = None
            mock_sm.save_game_state = MagicMock()

            result = await handler.show_current_frame(123456, adapter)

        assert result == 300
        assert 123456 in handler._sessions
        assert handler._sessions[123456].state.message_id == 300


# ── Task 7: resume_game tests ─────────────────────────────────────────────────

class TestResumeGame:
    """Lines 680-716: resume_game – all paths."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_controller(self):
        """Lines 685-686: no leader controller → return None."""
        handler = _handler()
        adapter = _make_adapter()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456):
            mock_gcm.get_controller.return_value = None
            mock_sm.load_game_state.return_value = None
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=123456)

            result = await handler.resume_game(123456, adapter)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_controller_not_initialized(self):
        """Lines 685-686: controller exists but not initialized → return None."""
        handler = _handler()
        adapter = _make_adapter()
        mock_controller = MagicMock()
        mock_controller.is_initialized.return_value = False

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456):
            mock_gcm.get_controller.return_value = mock_controller
            mock_sm.load_game_state.return_value = None
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=123456)

            result = await handler.resume_game(123456, adapter)

        assert result is None

    @pytest.mark.asyncio
    async def test_existing_session_removes_old_keyboard_and_sends_new_message(self):
        """Lines 694-710: session exists → remove old keyboard, send new message, update session."""
        handler = _handler()
        handler._sessions[123456] = _session(message_id=100)
        adapter = _make_adapter()
        adapter.send_game_message.return_value = 200

        mock_controller = MagicMock()
        mock_controller.is_initialized.return_value = True
        mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
        mock_controller.get_modifier_specs.return_value = []

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456):
            mock_gcm.get_controller.return_value = mock_controller
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=123456)
            mock_sm.save_game_state = MagicMock()
            mock_sm.load_chat_config.return_value = None

            result = await handler.resume_game(123456, adapter)

        assert result == 200
        adapter.edit_game_keyboard.assert_awaited_once_with(123456, 100, None)
        assert handler._sessions[123456].state.message_id == 200
        mock_sm.save_game_state.assert_called()

    @pytest.mark.asyncio
    async def test_no_session_creates_new_session(self):
        """Lines 712-714: no existing session → _create_session called."""
        handler = _handler()
        adapter = _make_adapter()
        adapter.send_game_message.return_value = 300

        mock_controller = MagicMock()
        mock_controller.is_initialized.return_value = True
        mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
        mock_controller.get_modifier_specs.return_value = []

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456):
            mock_gcm.get_controller.return_value = mock_controller
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=123456)
            mock_sm.load_game_state.return_value = None  # no existing session
            mock_sm.save_game_state = MagicMock()
            mock_sm.load_chat_config.return_value = None

            result = await handler.resume_game(123456, adapter)

        assert result == 300
        assert 123456 in handler._sessions

    @pytest.mark.asyncio
    async def test_old_keyboard_removal_failure_is_swallowed(self):
        """Lines 696-698: edit_game_keyboard raises for old message → swallowed, new message still sent."""
        handler = _handler()
        handler._sessions[123456] = _session(message_id=100)
        adapter = _make_adapter()
        adapter.edit_game_keyboard.side_effect = Exception("message not found")
        adapter.send_game_message.return_value = 200

        mock_controller = MagicMock()
        mock_controller.is_initialized.return_value = True
        mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
        mock_controller.get_modifier_specs.return_value = []

        with patch("src.handlers.input_handler.game_controller_manager") as mock_gcm, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=123456):
            mock_gcm.get_controller.return_value = mock_controller
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=123456)
            mock_sm.save_game_state = MagicMock()
            mock_sm.load_chat_config.return_value = None

            result = await handler.resume_game(123456, adapter)

        # Despite keyboard removal failure, new message is still sent
        assert result == 200
        adapter.send_game_message.assert_awaited_once()
