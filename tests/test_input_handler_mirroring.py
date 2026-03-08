"""Tests for InputHandler mirroring behaviour."""

import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.handlers.input_handler import InputHandler
from src.models.game_state import ChatConfig, ChatGameState, GameButton, GameSession


def _make_handler() -> InputHandler:
    return InputHandler()


def _make_session(chat_id: int, message_id: int) -> GameSession:
    state = ChatGameState(chat_id=chat_id, message_id=message_id)
    return GameSession(chat_id=chat_id, state=state)


def _make_adapter(platform="telegram"):
    adapter = MagicMock()
    adapter.platform = platform
    adapter.answer_interaction = AsyncMock()
    adapter.build_game_keyboard = MagicMock(return_value=MagicMock())
    adapter.edit_game_message = AsyncMock(return_value=None)
    adapter.edit_game_keyboard = AsyncMock()
    adapter.send_game_message = AsyncMock(return_value=200)
    adapter.send_text = AsyncMock()
    return adapter


# ---------------------------------------------------------------------------
# handle_button_press — leader resolution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHandleButtonPressLeaderResolution:
    """When a mirror chat presses a button, buffer is keyed to leader."""

    async def test_mirror_chat_buffers_to_leader(self):
        """Input from mirror should use leader's buffer, not mirror's buffer."""
        handler = _make_handler()
        mirror_id = 20
        leader_id = 10

        mirror_session = _make_session(mirror_id, 777)
        handler._sessions[mirror_id] = mirror_session
        adapter = _make_adapter()

        with (
            patch("src.handlers.input_handler.get_leader_chat_id", return_value=leader_id),
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.game_controller_manager"),
            patch("src.handlers.input_handler.asyncio.create_task"),
        ):
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=leader_id)
            leader_session = _make_session(leader_id, 888)
            mock_sm.load_game_state.return_value = None
            handler._sessions[leader_id] = leader_session

            await handler.handle_button_press(
                callback_data="a",
                chat_id=mirror_id,
                message_id=777,
                user_id=1,
                user_name="User",
                adapter=adapter,
                raw=None,
            )

        # Buffer should be on leader, not mirror
        assert leader_id in handler._pending_buffers
        assert mirror_id not in handler._pending_buffers

    async def test_mirror_validates_against_originating_session(self):
        """Stale message_id from mirror's own session should be rejected."""
        handler = _make_handler()
        mirror_id = 20
        leader_id = 10

        mirror_session = _make_session(mirror_id, 777)
        handler._sessions[mirror_id] = mirror_session
        adapter = _make_adapter()

        with (
            patch("src.handlers.input_handler.get_leader_chat_id", return_value=leader_id),
            patch("src.handlers.input_handler.state_manager"),
        ):
            await handler.handle_button_press(
                callback_data="a",
                chat_id=mirror_id,
                message_id=999,  # stale — mirror's session has 777
                user_id=1,
                user_name="User",
                adapter=adapter,
                raw=None,
            )

        # Should have answered with outdated message, no buffer created
        adapter.answer_interaction.assert_called_once()
        assert mirror_id not in handler._pending_buffers
        assert leader_id not in handler._pending_buffers

    async def test_independent_chat_buffers_to_self(self):
        """Non-mirror chat should buffer to itself."""
        handler = _make_handler()
        chat_id = 10

        session = _make_session(chat_id, 100)
        handler._sessions[chat_id] = session
        adapter = _make_adapter()

        with (
            patch("src.handlers.input_handler.get_leader_chat_id", return_value=chat_id),
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.game_controller_manager"),
            patch("src.handlers.input_handler.asyncio.create_task"),
        ):
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=chat_id)
            mock_sm.load_game_state.return_value = None

            await handler.handle_button_press(
                callback_data="a",
                chat_id=chat_id,
                message_id=100,
                user_id=1,
                user_name="User",
                adapter=adapter,
                raw=None,
            )

        assert chat_id in handler._pending_buffers


# ---------------------------------------------------------------------------
# _handle_modifier_button_press — leader config
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestModifierButtonPressLeader:
    async def test_modifier_uses_leader_config(self):
        """Modifier toggle should write to leader config, not mirror config."""
        handler = _make_handler()
        leader_id = 10
        leader_config = ChatConfig(chat_id=leader_id, modifier_states={})
        adapter = _make_adapter()

        mock_controller = MagicMock()
        mock_controller.get_modifier_specs.return_value = []

        with (
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.game_controller_manager") as mock_gcm,
        ):
            mock_sm.get_or_create_chat_config.return_value = leader_config
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)

            await handler._handle_modifier_button_press(
                raw=None,
                chat_id=20,  # mirror
                message_id=777,
                key="run",
                adapter=adapter,
                leader_id=leader_id,
            )

        # config fetched for leader, not mirror
        mock_sm.get_or_create_chat_config.assert_called_once_with(leader_id)
        # saved back
        mock_sm.save_chat_config.assert_called_once_with(leader_config)
        assert leader_config.modifier_states.get("run") is True

    async def test_modifier_edit_keyboard_on_originating_chat(self):
        """Keyboard edit should happen on the originating chat (not leader)."""
        handler = _make_handler()
        mirror_id = 20
        leader_id = 10
        leader_config = ChatConfig(chat_id=leader_id, modifier_states={})
        adapter = _make_adapter()

        mock_controller = MagicMock()
        mock_controller.get_modifier_specs.return_value = []

        with (
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.game_controller_manager") as mock_gcm,
        ):
            mock_sm.get_or_create_chat_config.return_value = leader_config
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)

            await handler._handle_modifier_button_press(
                raw=None,
                chat_id=mirror_id,
                message_id=777,
                key="run",
                adapter=adapter,
                leader_id=leader_id,
            )

        # Keyboard edited on the originating chat (mirror)
        adapter.edit_game_keyboard.assert_called_once_with(mirror_id, 777, adapter.build_game_keyboard.return_value)


# ---------------------------------------------------------------------------
# _process_batch — broadcast to mirrors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestProcessBatchMirrorBroadcast:
    async def test_broadcast_called_when_mirrors_exist(self):
        """After editing leader's message, broadcast_game_update is called for mirrors."""
        handler = _make_handler()
        leader_id = 10
        session = _make_session(leader_id, 100)
        handler._sessions[leader_id] = session

        mock_controller = MagicMock()
        mock_controller.save_state.return_value = b"state"
        mock_controller.get_frame.return_value = MagicMock()
        mock_controller.get_modifier_specs.return_value = []
        mock_controller.begin_hooks.return_value = {}
        mock_controller.end_hooks.return_value = None

        adapter = _make_adapter()
        batch = [MagicMock(button=GameButton.A, user_id=1, user_name="U")]

        fake_media_buffer = BytesIO(b"video")

        with (
            patch("src.handlers.input_handler.game_controller_manager") as mock_gcm,
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]),
            patch("src.handlers.input_handler.create_game_message_text", return_value="caption"),
        ):
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=leader_id)
            mock_sm.get_mirror_chat_ids.return_value = [20, 30]
            mock_sm.find_next_auto_save_slot.return_value = 0
            mock_bcast = AsyncMock()

            with patch("src.handlers.input_handler.broadcast_game_update", mock_bcast):
                await handler._process_batch(leader_id, 100, batch, adapter)

        mock_bcast.assert_called_once()
        call_args = mock_bcast.call_args
        assert call_args.args[0] == leader_id

    async def test_no_broadcast_called_when_no_mirrors(self):
        """If no mirrors, broadcast_game_update is still called."""
        handler = _make_handler()
        leader_id = 10
        session = _make_session(leader_id, 100)
        handler._sessions[leader_id] = session

        mock_controller = MagicMock()
        mock_controller.save_state.return_value = b"state"
        mock_controller.get_frame.return_value = MagicMock()
        mock_controller.get_modifier_specs.return_value = []
        mock_controller.begin_hooks.return_value = {}
        mock_controller.end_hooks.return_value = None

        adapter = _make_adapter()
        batch = [MagicMock(button=GameButton.A, user_id=1, user_name="U")]
        fake_media_buffer = BytesIO(b"video")

        with (
            patch("src.handlers.input_handler.game_controller_manager") as mock_gcm,
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]),
            patch("src.handlers.input_handler.create_game_message_text", return_value="caption"),
        ):
            mock_gcm.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(chat_id=leader_id)
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.find_next_auto_save_slot.return_value = 0

            mock_bcast = AsyncMock()
            with patch("src.handlers.input_handler.broadcast_game_update", mock_bcast):
                await handler._process_batch(leader_id, 100, batch, adapter)

        mock_bcast.assert_called_once()
        call_args = mock_bcast.call_args
        assert call_args.args[0] == leader_id
