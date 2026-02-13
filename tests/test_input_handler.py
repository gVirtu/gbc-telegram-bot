"""Tests for input handler.

This module tests the first-vote-wins logic, state transitions,
and input processing flow.
"""

import asyncio
import os
import pytest
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


class TestInputHandlerInitialization:
    """Test InputHandler initialization."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create a mock Telegram bot."""
        return MagicMock()
    
    def test_init_with_bot(self, mock_bot):
        """Test initialization with bot."""
        handler = InputHandler(mock_bot)
        
        assert handler.bot == mock_bot
        assert handler._sessions == {}
        assert handler._processing == set()

    def test_processing_set_isolated(self):
        """Test that processing set is isolated per handler instance."""
        from src.handlers.input_handler import InputHandler
        
        bot = MagicMock()
        handler1 = InputHandler(bot)
        handler2 = InputHandler(bot)
        
        handler1._processing.add(123)
        
        assert 123 in handler1._processing
        assert 123 not in handler2._processing, "Processing sets should be isolated"


class TestButtonPressHandling:
    """Test button press handling with first-vote-wins logic."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.send_photo = AsyncMock()
        bot.edit_message_reply_markup = AsyncMock()
        bot.edit_message_media = AsyncMock()
        return bot
    
    @pytest.fixture
    def handler(self, mock_bot):
        """Create handler with mocked bot."""
        return InputHandler(mock_bot)
    
    @pytest.fixture
    def mock_callback_query(self):
        """Create a mock callback query."""
        cq = MagicMock()
        cq.message.chat.id = 123456
        cq.message.message_id = 789
        cq.data = "a"
        cq.answer = AsyncMock()
        return cq
    
    @pytest.mark.asyncio
    async def test_invalid_callback(self, handler, mock_callback_query):
        """Test button press with invalid callback data."""
        mock_callback_query.data = "invalid"
        
        await handler.handle_button_press(mock_callback_query)
        
        mock_callback_query.answer.assert_called_once_with("Invalid button")
    
    @pytest.mark.asyncio
    async def test_input_already_in_progress(self, handler, mock_callback_query):
        """Test button press while input already processing adds to queue."""
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            # Add to processing set
            handler._processing.add(123456)
            
            # Create a session
            handler._sessions[123456] = GameSession(
                chat_id=123456,
                state=ChatGameState(chat_id=123456, message_id=789)
            )
            
            await handler.handle_button_press(mock_callback_query)
            
            # Queue-based system should add to queue, not reject
            mock_callback_query.answer.assert_called_once()
            call_args = mock_callback_query.answer.call_args[0][0]
            assert "Adicionado à fila" in call_args or "Adicionado à sua sequência" in call_args
    
    @pytest.mark.asyncio
    async def test_outdated_message(self, handler, mock_callback_query):
        """Test button press on outdated message is rejected."""
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            # Create session with different message ID
            handler._sessions[123456] = GameSession(
                chat_id=123456,
                state=ChatGameState(chat_id=123456, message_id=999)
            )
            
            mock_callback_query.message.message_id = 789
            
            await handler.handle_button_press(mock_callback_query)
            
            # Should reject with outdated message
            mock_callback_query.answer.assert_called_once()
            call_args = mock_callback_query.answer.call_args[0][0]
            assert "desatualizada" in call_args
    
    @pytest.mark.asyncio
    async def test_successful_button_press(self, handler, mock_callback_query):
        """Test successful button press creates queue task."""
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            with patch("src.handlers.input_handler.asyncio.create_task") as mock_create_task:
                # Create session
                handler._sessions[123456] = GameSession(
                    chat_id=123456,
                    state=ChatGameState(chat_id=123456, message_id=789)
                )
                
                await handler.handle_button_press(mock_callback_query)
                
                # Should acknowledge with button name
                mock_callback_query.answer.assert_called_once_with("Processando: A")
                
                # Should create a task for queue processing
                mock_create_task.assert_called_once()
                
                # Verify queue was populated
                assert 123456 in handler._input_queues
                assert not handler._input_queues[123456].is_empty()


class TestStartGame:
    """Test starting a new game."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create mock bot."""
        bot = MagicMock()
        bot.send_photo = AsyncMock(return_value=MagicMock(message_id=100))
        return bot
    
    @pytest.fixture
    def handler(self, mock_bot):
        """Create handler."""
        return InputHandler(mock_bot)
    
    @pytest.mark.asyncio
    async def test_start_game_creates_session(self, handler, mock_bot):
        """Test starting game creates session."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager") as mock_state:
                mock_controller = MagicMock()
                mock_controller.is_initialized.return_value = True
                mock_controller.get_frame.return_value = MagicMock()
                mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
                mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                
                message_id = await handler.start_game(123456)
                
                assert message_id == 100
                assert 123456 in handler._sessions
                assert handler._sessions[123456].state.message_id == 100
    
    @pytest.mark.asyncio
    async def test_start_game_sends_photo(self, handler, mock_bot):
        """Test starting game sends photo message."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager") as mock_state:
                mock_controller = MagicMock()
                mock_controller.is_initialized.return_value = True
                mock_controller.get_frame.return_value = MagicMock()
                mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
                mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                
                await handler.start_game(123456)
                
                mock_bot.send_photo.assert_called_once()
                call_args = mock_bot.send_photo.call_args
                assert call_args[1]["chat_id"] == 123456


class TestShowCurrentFrame:
    """Test showing current frame."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create mock bot."""
        bot = MagicMock()
        bot.send_photo = AsyncMock(return_value=MagicMock(message_id=200))
        bot.edit_message_media = AsyncMock()
        bot.edit_message_reply_markup = AsyncMock()
        return bot
    
    @pytest.fixture
    def handler(self, mock_bot):
        """Create handler."""
        return InputHandler(mock_bot)
    
    @pytest.mark.asyncio
    async def test_show_frame_no_game(self, handler):
        """Test showing frame with no active game."""
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
                mock_mgr.get_controller.return_value = None
                
                result = await handler.show_current_frame(123456)
                
                assert result is None
    
    @pytest.mark.asyncio
    async def test_show_frame_edits_existing(self, handler, mock_bot):
        """Test showing frame edits existing message."""
        # Create session with existing message
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
            
            result = await handler.show_current_frame(123456)
            
            assert result == 100
            mock_bot.edit_message_media.assert_called_once()


class TestInputProcessing:
    """Test input processing flow."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create mock bot."""
        bot = MagicMock()
        bot.edit_message_reply_markup = AsyncMock()
        bot.edit_message_media = AsyncMock()
        bot.edit_message_caption = AsyncMock()
        return bot
    
    @pytest.fixture
    def handler(self, mock_bot):
        """Create handler."""
        return InputHandler(mock_bot)
    
    @pytest.fixture
    def mock_controller(self):
        """Create mock game controller."""
        controller = MagicMock()
        controller.send_input.return_value = MagicMock()
        controller.get_frame_as_png.return_value = BytesIO(b"png")
        controller.last_frame_hash = None
        return controller
    
    @pytest.mark.asyncio
    async def test_process_sequence_executes_button(self, handler, mock_bot, mock_controller):
        """Test input processing executes button press."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            
            await handler._process_sequence(123456, [GameButton.B], 789)
            
            # Check that send_input was called with correct button
            mock_controller.send_input.assert_called_once()
            call_args = mock_controller.send_input.call_args
            assert call_args[0][0] == GameButton.B  # First positional arg should be the button


class TestSessionManagement:
    """Test session management."""
    
    @pytest.fixture
    def handler(self):
        """Create handler."""
        bot = MagicMock()
        return InputHandler(bot)
    
    def test_is_input_in_progress(self, handler):
        """Test checking if input is in progress."""
        assert handler.is_input_in_progress(123456) is False
        
        handler._processing.add(123456)
        
        assert handler.is_input_in_progress(123456) is True
    
    def test_cleanup_session(self, handler):
        """Test cleaning up session."""
        # Create session
        handler._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456)
        )
        
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            result = handler.cleanup_session(123456)
            
            assert result is True
            assert 123456 not in handler._sessions
            mock_mgr.remove_controller.assert_called_once_with(123456)
    
    def test_cleanup_nonexistent_session(self, handler):
        """Test cleaning up nonexistent session."""
        result = handler.cleanup_session(999999)
        
        assert result is False


class TestSingleton:
    """Test singleton pattern."""
    
    @pytest.fixture
    def reset_singleton(self):
        """Reset singleton before each test."""
        # Reset the module-level singleton
        import src.handlers.input_handler as ih
        original = ih._input_handler
        ih._input_handler = None
        yield
        ih._input_handler = original
    
    def test_get_input_handler_creates_new(self, reset_singleton):
        """Test getting handler creates new instance."""
        mock_bot = MagicMock()
        
        handler = get_input_handler(mock_bot)
        
        assert handler is not None
        assert handler.bot == mock_bot
    
    def test_get_input_handler_returns_same(self, reset_singleton):
        """Test getting handler returns same instance."""
        mock_bot = MagicMock()
        
        handler1 = get_input_handler(mock_bot)
        handler2 = get_input_handler(mock_bot)
        
        assert handler1 is handler2


class TestErrorHandling:
    """Test error handling."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create mock bot."""
        bot = MagicMock()
        bot.send_message = AsyncMock()
        return bot
    
    @pytest.fixture
    def handler(self, mock_bot):
        """Create handler."""
        return InputHandler(mock_bot)
    
    @pytest.mark.asyncio
    async def test_send_error_message(self, handler, mock_bot):
        """Test sending error message."""
        await handler._send_error_message(123456, "Test error")
        
        mock_bot.send_message.assert_called_once_with(123456, "❌ Test error")
    
    @pytest.mark.asyncio
    async def test_send_error_message_handles_telegram_error(self, handler, mock_bot):
        """Test error handling when sending error fails."""
        mock_bot.send_message.side_effect = TelegramError("Network error")
        
        # Should not raise
        await handler._send_error_message(123456, "Test error")


class TestEditOperations:
    """Test message editing operations."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create mock bot."""
        bot = MagicMock()
        bot.edit_message_reply_markup = AsyncMock()
        bot.edit_message_media = AsyncMock()
        bot.edit_message_caption = AsyncMock()
        return bot
    
    @pytest.fixture
    def handler(self, mock_bot):
        """Create handler."""
        return InputHandler(mock_bot)
    
    @pytest.mark.asyncio
    async def test_edit_keyboard(self, handler, mock_bot):
        """Test editing message keyboard."""
        keyboard = MagicMock()
        
        await handler._edit_message_keyboard(123456, 789, keyboard)
        
        mock_bot.edit_message_reply_markup.assert_called_once_with(
            chat_id=123456,
            message_id=789,
            reply_markup=keyboard,
        )
    
    @pytest.mark.asyncio
    async def test_edit_keyboard_handles_error(self, handler, mock_bot):
        """Test editing keyboard handles Telegram errors."""
        mock_bot.edit_message_reply_markup.side_effect = TelegramError("Error")
        
        # Should not raise
        await handler._edit_message_keyboard(123456, 789, MagicMock())
    
    @pytest.mark.asyncio
    async def test_edit_media(self, handler, mock_bot):
        """Test editing message media."""
        photo_buffer = BytesIO(b"png")
        
        await handler._edit_message_media(123456, 789, photo_buffer, "caption")
        
        mock_bot.edit_message_media.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_edit_media_handles_error(self, handler, mock_bot):
        """Test editing media handles Telegram errors."""
        mock_bot.edit_message_media.side_effect = TelegramError("Error")
        
        # Should not raise
        await handler._edit_message_media(123456, 789, BytesIO(b"png"), "caption")


class TestSessionLoading:
    """Test loading existing sessions from state manager."""
    
    @pytest.fixture
    def handler(self):
        """Create handler."""
        bot = MagicMock()
        return InputHandler(bot)
    
    def test_get_session_loads_from_state(self, handler):
        """Test getting session loads from state manager."""
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
        """Test getting session returns None when no saved state."""
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            mock_state.load_game_state.return_value = None
            
            session = handler._get_session(123456)
            
            assert session is None
    
    def test_get_session_caches_in_memory(self, handler):
        """Test getting session caches it in memory."""
        with patch("src.handlers.input_handler.state_manager") as mock_state:
            mock_state.load_game_state.return_value = ChatGameState(
                chat_id=123456,
                message_id=100
            )
            
            # First call
            session1 = handler._get_session(123456)
            # Second call should use cached version
            session2 = handler._get_session(123456)

            assert session1 is session2
            mock_state.load_game_state.assert_called_once()


class TestWaitButtonProcessing:
    """Test WAIT button processing."""

    @pytest.fixture
    def mock_bot(self):
        bot = MagicMock()
        bot.edit_message_reply_markup = AsyncMock()
        bot.edit_message_media = AsyncMock()
        return bot

    @pytest.fixture
    def handler(self, mock_bot):
        return InputHandler(mock_bot)

    @pytest.fixture
    def mock_controller(self):
        controller = MagicMock()
        controller.tick.return_value = MagicMock()
        controller.send_input.return_value = MagicMock()
        controller.get_frame_as_png.return_value = BytesIO(b"png")
        controller.last_frame_hash = None
        return controller

    @pytest.mark.asyncio
    async def test_wait_button_skips_send_input(self, handler, mock_bot, mock_controller):
        """Test WAIT button doesn't call send_input."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            handler._edit_message_keyboard = AsyncMock()
            handler._edit_message_media = AsyncMock()

            # Need to add get_session for state
            from src.models.game_state import ChatGameState, GameSession
            handler._sessions[123456] = GameSession(
                chat_id=123456,
                state=ChatGameState(chat_id=123456, message_id=789)
            )

            await handler._process_sequence(123456, [GameButton.WAIT], 789)

            # WAIT should NOT call send_input
            mock_controller.send_input.assert_not_called()
            # WAIT should call tick multiple times (for button execution + animation)
            assert mock_controller.tick.call_count > 1

    @pytest.mark.asyncio
    async def test_wait_button_ticks_emulator(self, handler, mock_bot, mock_controller):
        """Test WAIT button ticks the emulator."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.settings") as mock_settings:
                mock_settings.input_hold_frames = 30
                mock_settings.animation_duration = 0.1  # Short duration for testing
                mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                handler._edit_message_keyboard = AsyncMock()
                handler._edit_message_media = AsyncMock()

                # Need to add get_session for state
                from src.models.game_state import ChatGameState, GameSession
                handler._sessions[123456] = GameSession(
                    chat_id=123456,
                    state=ChatGameState(chat_id=123456, message_id=789)
                )

                await handler._process_sequence(123456, [GameButton.WAIT], 789)

                # First call should be for button execution with input_hold_frames
                from unittest.mock import call
                assert mock_controller.tick.call_args_list[0] == call(frames=30)
                # Subsequent calls are for animation with 1 frame each (synchronous generation)
                for tick_call in mock_controller.tick.call_args_list[1:]:
                    assert tick_call == call(1)

    @pytest.mark.asyncio
    async def test_wait_button_runs_animation(self, handler, mock_bot, mock_controller):
        """Test WAIT button still runs animation phase."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            handler._edit_message_keyboard = AsyncMock()
            handler._edit_message_media = AsyncMock()

            # Need to add get_session for state
            from src.models.game_state import ChatGameState, GameSession
            handler._sessions[123456] = GameSession(
                chat_id=123456,
                state=ChatGameState(chat_id=123456, message_id=789)
            )

            await handler._process_sequence(123456, [GameButton.WAIT], 789)

            # Animation is now inline - check that frames were captured and GIF/media updated
            # The _edit_message_media should be called to send the animation
            handler._edit_message_media.assert_called()

    @pytest.mark.asyncio
    async def test_normal_button_still_calls_send_input(self, handler, mock_bot, mock_controller):
        """Test non-WAIT buttons still call send_input."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            handler._edit_message_keyboard = AsyncMock()
            handler._edit_message_media = AsyncMock()

            # Need to add get_session for state
            from src.models.game_state import ChatGameState, GameSession
            handler._sessions[123456] = GameSession(
                chat_id=123456,
                state=ChatGameState(chat_id=123456, message_id=789)
            )

            await handler._process_sequence(123456, [GameButton.A], 789)

            # Normal buttons should call send_input
            mock_controller.send_input.assert_called_once()
            # Tick is also called during animation phase
            assert mock_controller.tick.call_count > 0
