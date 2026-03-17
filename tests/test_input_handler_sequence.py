"""Tests for InputHandler.handle_sequence_input."""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from src.handlers.input_handler import InputHandler
from src.models.game_state import GameButton, GameSession, ChatGameState
from src.models.input_queue import PendingBuffer


def _make_session(chat_id: int, message_id: int) -> GameSession:
    state = ChatGameState(chat_id=chat_id, message_id=message_id)
    return GameSession(chat_id=chat_id, state=state)


def _make_adapter(platform: str = "discord") -> MagicMock:
    adapter = MagicMock()
    adapter.platform = platform
    return adapter


class TestHandleSequenceInput:

    @pytest.fixture
    def handler(self):
        return InputHandler()

    @pytest.mark.asyncio
    async def test_returns_false_when_no_active_game(self, handler):
        """Returns (False, error) when no session exists."""
        adapter = _make_adapter()
        with patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False):
            mock_sm.load_game_state.return_value = None
            ok, msg = await handler.handle_sequence_input(
                buttons=[GameButton.UP],
                chat_id=100,
                message_id=42,
                user_id=1,
                user_name="Alice",
                adapter=adapter,
            )
        assert ok is False
        assert msg  # some error message

    @pytest.mark.asyncio
    async def test_returns_false_when_message_outdated(self, handler):
        """Returns (False, error) when message_id doesn't match session."""
        adapter = _make_adapter()
        handler._sessions[100] = _make_session(100, message_id=99)
        with patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False):
            ok, msg = await handler.handle_sequence_input(
                buttons=[GameButton.UP],
                chat_id=100,
                message_id=999,  # wrong
                user_id=1,
                user_name="Alice",
                adapter=adapter,
            )
        assert ok is False
        assert msg

    @pytest.mark.asyncio
    async def test_returns_false_when_buffer_full(self, handler):
        """Returns (False, error) atomically when buffer cannot fit all buttons."""
        adapter = _make_adapter()
        session = _make_session(100, message_id=42)
        handler._sessions[100] = session
        # Fill buffer to max_size - 1, then try to add 2 buttons (won't fit atomically)
        buffer = PendingBuffer(max_size=2)
        buffer.add(1, "Bob", GameButton.DOWN)  # 1 item, space for 1 more
        handler._pending_buffers[100] = buffer
        with patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False):
            ok, msg = await handler.handle_sequence_input(
                buttons=[GameButton.UP, GameButton.LEFT],  # 2 buttons, only 1 space
                chat_id=100,
                message_id=42,
                user_id=1,
                user_name="Alice",
                adapter=adapter,
            )
        assert ok is False
        assert buffer.total_buttons() == 1  # nothing was added

    @pytest.mark.asyncio
    async def test_adds_all_buttons_to_buffer_on_success(self, handler):
        """All buttons are added to the buffer on success."""
        adapter = _make_adapter()
        session = _make_session(100, message_id=42)
        handler._sessions[100] = session
        buttons = [GameButton.UP, GameButton.RIGHT, GameButton.A]
        with patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.state_manager"), \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch.object(handler, "_is_processing", return_value=True):
            ok, msg = await handler.handle_sequence_input(
                buttons=buttons,
                chat_id=100,
                message_id=42,
                user_id=1,
                user_name="Alice",
                adapter=adapter,
            )
        assert ok is True
        buffer = handler._pending_buffers[100]
        assert buffer.total_buttons() == 3
        assert [b.button for b in buffer.items] == buttons

    @pytest.mark.asyncio
    async def test_drain_event_set_immediately_not_debounce(self, handler):
        """Drain event is set immediately; no debounce timer is created."""
        adapter = _make_adapter()
        session = _make_session(100, message_id=42)
        handler._sessions[100] = session
        with patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.state_manager"), \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch.object(handler, "_is_processing", return_value=True):
            await handler.handle_sequence_input(
                buttons=[GameButton.UP],
                chat_id=100,
                message_id=42,
                user_id=1,
                user_name="Alice",
                adapter=adapter,
            )
        drain = handler._drain_events.get(100)
        assert drain is not None and drain.is_set(), "drain event must be set immediately"
        # No buffer timer task should have been created
        assert 100 not in handler._buffer_tasks

    @pytest.mark.asyncio
    async def test_uses_leader_chat_id_for_buffer(self, handler):
        """Buffer is keyed to leader_id, not the originating chat_id."""
        adapter = _make_adapter()
        # chat_id=200 is a mirror of leader=100
        leader_session = _make_session(100, message_id=42)
        handler._sessions[200] = _make_session(200, message_id=42)
        handler._sessions[100] = leader_session
        with patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.state_manager"), \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch.object(handler, "_is_processing", return_value=True):
            ok, _ = await handler.handle_sequence_input(
                buttons=[GameButton.B],
                chat_id=200,   # originating chat is the mirror
                message_id=42,
                user_id=1,
                user_name="Alice",
                adapter=adapter,
            )
        assert ok is True
        assert 100 in handler._pending_buffers   # keyed to leader
        assert 200 not in handler._pending_buffers

    @pytest.mark.asyncio
    async def test_starts_processing_loop_when_not_running(self, handler):
        """Starts _process_queue_loop if not already processing."""
        adapter = _make_adapter()
        session = _make_session(100, message_id=42)
        handler._sessions[100] = session
        mock_config = MagicMock()
        mock_config.platform = "discord"
        with patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.asyncio") as mock_asyncio, \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch.object(handler, "_is_processing", return_value=False), \
             patch.object(handler, "_get_adapter_for_chat", return_value=adapter):
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_asyncio.create_task = MagicMock()
            await handler.handle_sequence_input(
                buttons=[GameButton.UP],
                chat_id=100,
                message_id=42,
                user_id=1,
                user_name="Alice",
                adapter=adapter,
            )
        mock_asyncio.create_task.assert_called_once()
