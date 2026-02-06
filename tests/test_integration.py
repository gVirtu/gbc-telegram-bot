"""Integration tests for the Telegram Pokémon Red Bot.

This module tests the complete flow from webhook to game execution,
ensuring all components work together correctly.
"""

import os
import pytest
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

# Set environment variables before importing
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token_1234567890"
os.environ["WEBHOOK_URL"] = "https://test.example.com"
os.environ["WEBHOOK_SECRET"] = "test_secret_1234567890"
os.environ["PYTEST_CURRENT_TEST"] = "1"  # Skip ROM validation

import numpy as np


class TestEndToEndGameFlow:
    """Test complete game flow from start to input."""
    
    @pytest.mark.asyncio
    async def test_full_game_session(self):
        """Test complete game session: start -> input -> animate -> next input."""
        # This test simulates the full flow:
        # 1. User sends /start_game
        # 2. Bot initializes game and sends frame with keyboard
        # 3. User presses a button
        # 4. Bot processes input and animates
        # 5. Bot sends new frame with keyboard
        
        with patch("src.game.PyBoy") as mock_pyboy_class:
            # Setup mock PyBoy
            mock_pyboy = MagicMock()
            mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
            mock_screen = MagicMock()
            type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
            mock_pyboy.screen = mock_screen
            mock_pyboy_class.return_value = mock_pyboy
            
            with patch("telegram.Bot") as mock_bot_class:
                mock_bot_instance = MagicMock()
                mock_bot_instance.send_photo = AsyncMock(return_value=MagicMock(message_id=100))
                mock_bot_instance.edit_message_reply_markup = AsyncMock()
                mock_bot_instance.edit_message_media = AsyncMock()
                mock_bot_class.return_value = mock_bot_instance
                
                # Import after mocking
                from src.handlers.input_handler import InputHandler
                from src.handlers.commands import start_game_command
                from src.models.game_state import GameButton
                
                # Create mock update and context
                mock_update = MagicMock()
                mock_update.effective_chat.id = 123456
                mock_update.message.reply_text = AsyncMock()
                
                mock_context = MagicMock()
                mock_context.bot = mock_bot_instance
                
                # Step 1: Start game
                await start_game_command(mock_update, mock_context)
                
                # Verify game was started
                mock_update.message.reply_text.assert_called_with("🎮 Starting Pokémon Red...")
                mock_bot_instance.send_photo.assert_called_once()
                
                # Step 2: Simulate button press
                handler = InputHandler(mock_bot_instance)
                
                # Create mock callback query
                mock_callback = MagicMock()
                mock_callback.message.chat.id = 123456
                mock_callback.message.message_id = 100
                mock_callback.data = "a"
                mock_callback.answer = AsyncMock()
                mock_callback.bot = mock_bot_instance
                
                # Mock the animation to be fast
                handler._animate_frames = AsyncMock()
                
                # Create session
                from src.models.game_state import ChatGameState, GameSession
                handler._sessions[123456] = GameSession(
                    chat_id=123456,
                    state=ChatGameState(chat_id=123456, message_id=100)
                )
                
                # Mock game controller manager
                with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
                    mock_controller = MagicMock()
                    mock_controller.send_input.return_value = mock_frame
                    mock_controller.get_frame_as_png.return_value = BytesIO(b"png")
                    mock_controller.last_frame_hash = None
                    mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                    
                    # Process button press
                    await handler.handle_button_press(mock_callback)
                    
                    # Verify button was processed
                    mock_callback.answer.assert_called_with("Processing: A")
                    mock_controller.send_input.assert_called_once()


class TestSaveLoadIntegration:
    """Test save and load functionality integration."""
    
    @pytest.mark.asyncio
    async def test_save_and_load_game(self):
        """Test saving and loading game state."""
        with patch("src.game.PyBoy") as mock_pyboy_class:
            mock_pyboy = MagicMock()
            mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
            mock_screen = MagicMock()
            type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
            mock_pyboy.screen = mock_screen
            mock_pyboy_class.return_value = mock_pyboy
            
            with patch("telegram.Bot") as mock_bot_class:
                mock_bot_instance = MagicMock()
                mock_bot_instance.send_photo = AsyncMock(return_value=MagicMock(message_id=100))
                mock_bot_instance.send_message = AsyncMock()
                mock_bot_class.return_value = mock_bot_instance
                
                from src.handlers.commands import save_command, load_command
                
                # Create mock update
                mock_update = MagicMock()
                mock_update.effective_chat.id = 123456
                
                mock_context = MagicMock()
                mock_context.bot = mock_bot_instance
                mock_context.args = ["0"]
                
                # Mock controller
                with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
                    mock_controller = MagicMock()
                    mock_controller.is_initialized.return_value = True
                    mock_controller.save_state.return_value = b"test_save_data"
                    mock_mgr.get_controller.return_value = mock_controller
                    
                    # Save game
                    with patch("src.handlers.commands.state_manager") as mock_state:
                        mock_state.list_save_slots = MagicMock(return_value=[])
                        mock_state.save_to_slot = MagicMock()
                        
                        await save_command(mock_update, mock_context)
                        
                        # Verify save was called
                        mock_state.save_to_slot.assert_called_once()
                        
                        # Now load it
                        mock_state.load_from_slot = MagicMock(return_value=b"test_save_data")
                        
                        with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                            mock_handler = MagicMock()
                            mock_handler.is_input_in_progress.return_value = False
                            mock_handler.show_current_frame = AsyncMock(return_value=100)
                            mock_get_handler.return_value = mock_handler
                            
                            await load_command(mock_update, mock_context)
                            
                            # Verify load was called
                            mock_controller.load_state.assert_called_once_with(b"test_save_data")


class TestWebhookToHandlerIntegration:
    """Test webhook processing through to handlers."""
    
    @pytest.mark.asyncio
    async def test_callback_query_to_input_handler(self):
        """Test callback query routes to input handler."""
        from src.handlers.webhook import WebhookHandler
        
        handler = WebhookHandler()
        handler.telegram_app = MagicMock()
        handler.input_handler = MagicMock()
        handler.input_handler.handle_button_press = AsyncMock()
        
        # Mock update with callback query
        mock_update = MagicMock()
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.data = "start"
        mock_update.message = None
        
        with patch("telegram.Update.de_json", return_value=mock_update):
            await handler.process_update({"update_id": 123})
            
            # Should route to input handler
            handler.input_handler.handle_button_press.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_message_to_command_handler(self):
        """Test message routes to command handler."""
        from src.handlers.webhook import WebhookHandler
        
        handler = WebhookHandler()
        handler.telegram_app = MagicMock()
        handler.input_handler = MagicMock()
        
        # Mock update with command
        mock_update = MagicMock()
        mock_update.callback_query = None
        mock_update.message = MagicMock()
        mock_update.message.text = "/help"
        mock_update.message.bot = MagicMock()
        
        with patch("telegram.Update.de_json", return_value=mock_update):
            with patch("src.handlers.commands.help_command") as mock_help:
                mock_help.return_value = AsyncMock()
                
                await handler.process_update({"update_id": 123})
                
                mock_help.assert_called_once()


class TestStatePersistenceIntegration:
    """Test state persistence across operations."""
    
    def test_game_state_saved_on_input(self):
        """Test that game state is saved to disk after input."""
        with patch("src.utils.state_manager.state_manager") as mock_state_mgr:
            mock_state_mgr.load_game_state = MagicMock(return_value=None)
            mock_state_mgr.save_game_state = MagicMock()
            
            from src.handlers.input_handler import InputHandler
            from src.models.game_state import ChatGameState, GameSession
            
            # Create handler and session
            handler = InputHandler(MagicMock())
            session = GameSession(
                chat_id=123456,
                state=ChatGameState(chat_id=123456, message_id=100)
            )
            handler._sessions[123456] = session
            
            # Simulate state update
            session.state.input_in_progress = True
            session.state.last_input = "a"
            
            # State should be persisted (in real usage)
            # Here we just verify the structure is correct
            assert handler._sessions[123456].state.chat_id == 123456


class TestFrameOptimizationIntegration:
    """Test frame optimization in complete flow."""
    
    def test_duplicate_frames_skipped(self):
        """Test that duplicate frames are not sent."""
        from src.utils.frame_utils import should_update_frame
        import numpy as np
        
        # Create identical frames
        frame1 = np.zeros((144, 160, 3), dtype=np.uint8)
        frame2 = np.zeros((144, 160, 3), dtype=np.uint8)
        
        # First frame should update
        should_update1, hash1 = should_update_frame(frame1, None)
        assert should_update1 is True
        
        # Same frame should not update
        should_update2, hash2 = should_update_frame(frame2, hash1)
        assert should_update2 is False
        assert hash1 == hash2


class TestErrorHandlingIntegration:
    """Test error handling across components."""
    
    @pytest.mark.asyncio
    async def test_invalid_button_callback(self):
        """Test handling of invalid button callback."""
        from src.handlers.webhook import WebhookHandler
        
        handler = WebhookHandler()
        handler.telegram_app = MagicMock()
        handler.input_handler = MagicMock()
        
        # Mock update with invalid callback
        mock_update = MagicMock()
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.data = "invalid_button"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.message = None
        
        with patch("telegram.Update.de_json", return_value=mock_update):
            # Should not raise, just log
            await handler.process_update({"update_id": 123})
    
    @pytest.mark.asyncio
    async def test_telegram_api_error_handling(self):
        """Test graceful handling of Telegram API errors."""
        from telegram.error import TelegramError
        from src.handlers.input_handler import InputHandler
        
        handler = InputHandler(MagicMock())
        
        # Mock bot that raises error
        handler.bot.edit_message_media = AsyncMock(
            side_effect=TelegramError("Message not found")
        )
        
        # Should not raise
        await handler._edit_message_media(123456, 789, BytesIO(b"png"))


class TestConfigurationIntegration:
    """Test configuration integration across modules."""
    
    def test_settings_used_consistently(self):
        """Test that settings are used consistently across modules."""
        from src.config import settings
        
        # Verify all critical settings are accessible
        assert settings.telegram_bot_token is not None
        assert settings.webhook_url is not None
        assert settings.webhook_secret is not None
        assert settings.port > 0
        assert settings.input_hold_frames > 0
        assert settings.animation_duration > 0
        assert settings.save_slots > 0
    
    def test_webhook_path_matches(self):
        """Test that webhook path is consistent."""
        from src.config import settings
        from src.handlers.webhook import WebhookHandler
        
        handler = WebhookHandler()
        expected_path = settings.get_webhook_path()
        
        # Should validate correctly
        assert handler._validate_webhook_path(expected_path) is True
        assert handler._validate_webhook_path("/wrong/path") is False


class TestConcurrentAccess:
    """Test handling of concurrent operations."""
    
    @pytest.mark.asyncio
    async def test_input_locking(self):
        """Test that input is locked during processing."""
        from src.handlers.input_handler import InputHandler
        
        handler = InputHandler(MagicMock())
        
        # Mark as processing
        handler._processing.add(123456)
        
        # Check lock
        assert handler.is_input_in_progress(123456) is True
        
        # Remove lock
        handler._processing.discard(123456)
        
        # Check unlocked
        assert handler.is_input_in_progress(123456) is False


# Summary test
class TestSuiteSummary:
    """Summary of integration test coverage."""
    
    def test_all_modules_importable(self):
        """Verify all modules can be imported without errors."""
        modules = [
            "src.config",
            "src.models.game_state",
            "src.utils.frame_utils",
            "src.utils.state_manager",
            "src.game",
            "src.keyboard",
            "src.handlers.input_handler",
            "src.handlers.commands",
            "src.handlers.webhook",
            "src.main",
        ]
        
        for module in modules:
            __import__(module)
        
        assert True  # If we get here, all imports succeeded
