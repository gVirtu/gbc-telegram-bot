"""Tests for command handlers.

This module tests all bot commands including /start_game, /current_frame,
/save, /load, /status, and /help.
"""

import os
import pytest
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

# Set environment variables before importing
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
os.environ["WEBHOOK_URL"] = "https://test.example.com"
os.environ["WEBHOOK_SECRET"] = "test_secret_1234567890"

from telegram import Update

from src.handlers.commands import (
    start_game_command,
    current_frame_command,
    save_command,
    load_command,
    status_command,
    help_command,
    unknown_command,
    COMMAND_HANDLERS,
)
from src.models.game_state import GameButton


class MockUpdate:
    """Mock Telegram Update object."""
    
    def __init__(self, chat_id=123456, text="", args=None):
        self.effective_chat = MagicMock()
        self.effective_chat.id = chat_id
        self.message = MagicMock()
        self.message.reply_text = AsyncMock()
        self.message.text = text


class MockContext:
    """Mock Telegram Context object."""
    
    def __init__(self, args=None):
        self.bot = MagicMock()
        self.args = args or []


class TestStartGameCommand:
    """Test /start_game command."""
    
    @pytest.fixture
    def update(self):
        """Create mock update."""
        return MockUpdate()
    
    @pytest.fixture
    def context(self):
        """Create mock context."""
        return MockContext()
    
    @pytest.mark.asyncio
    async def test_start_game_success(self, update, context):
        """Test successful game start."""
        with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
            mock_handler = MagicMock()
            mock_handler.cleanup_session = MagicMock()
            mock_handler.start_game = AsyncMock(return_value=100)
            mock_get_handler.return_value = mock_handler
            
            await start_game_command(update, context)
            
            # Should clean up existing session
            mock_handler.cleanup_session.assert_called_once_with(123456)
            # Should start new game
            mock_handler.start_game.assert_called_once_with(123456)
    
    @pytest.mark.asyncio
    async def test_start_game_error(self, update, context):
        """Test game start with error."""
        with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
            mock_handler = MagicMock()
            mock_handler.cleanup_session = MagicMock()
            mock_handler.start_game = AsyncMock(side_effect=Exception("ROM not found"))
            mock_get_handler.return_value = mock_handler
            
            await start_game_command(update, context)
            
            # Should send error message
            update.message.reply_text.assert_called_with(
                "❌ Failed to start game. Please make sure the ROM file is available."
            )


class TestCurrentFrameCommand:
    """Test /current_frame command."""
    
    @pytest.fixture
    def update(self):
        return MockUpdate()
    
    @pytest.fixture
    def context(self):
        return MockContext()
    
    @pytest.mark.asyncio
    async def test_no_active_game(self, update, context):
        """Test showing frame with no active game."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_mgr.get_controller.return_value = None
            
            await current_frame_command(update, context)
            
            update.message.reply_text.assert_called_with(
                "No active game! Use /start_game to begin playing."
            )
    
    @pytest.mark.asyncio
    async def test_input_in_progress(self, update, context):
        """Test showing frame while input processing."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller
            
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = True
                mock_get_handler.return_value = mock_handler
                
                await current_frame_command(update, context)
                
                update.message.reply_text.assert_called_with(
                    "⏳ Input is being processed. Please wait..."
                )
    
    @pytest.mark.asyncio
    async def test_show_frame_success(self, update, context):
        """Test successfully showing current frame."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller
            
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = False
                mock_handler.show_current_frame = AsyncMock(return_value=100)
                mock_get_handler.return_value = mock_handler
                
                await current_frame_command(update, context)
                
                mock_handler.show_current_frame.assert_called_once_with(123456)


class TestSaveCommand:
    """Test /save command."""
    
    @pytest.fixture
    def update(self):
        return MockUpdate()
    
    @pytest.fixture
    def context(self):
        return MockContext()
    
    @pytest.mark.asyncio
    async def test_save_no_game(self, update, context):
        """Test saving with no active game."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_mgr.get_controller.return_value = None
            
            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []
                
                await save_command(update, context)
                
                update.message.reply_text.assert_called_with(
                    "No active game! Use /start_game first."
                )
    
    @pytest.mark.asyncio
    async def test_save_to_specific_slot(self, update, context):
        """Test saving to specific slot."""
        context.args = ["2"]
        
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.save_state.return_value = b"save_data"
            mock_mgr.get_controller.return_value = mock_controller
            
            with patch("src.handlers.commands.state_manager") as mock_state:
                mock_state.save_to_slot = MagicMock()
                mock_state.list_save_slots = MagicMock(return_value=[])
                
                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []
                    mock_settings.save_slots = 5
                    
                    await save_command(update, context)
                    
                    mock_state.save_to_slot.assert_called_once()
                    call_args = mock_state.save_to_slot.call_args
                    assert call_args[1]["slot_number"] == 2
    
    @pytest.mark.asyncio
    async def test_save_invalid_slot(self, update, context):
        """Test saving to invalid slot."""
        context.args = ["99"]
        
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller
            
            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.save_slots = 5
                mock_settings.allowed_chat_ids = []
                
                await save_command(update, context)
                
                update.message.reply_text.assert_called_with(
                    "❌ Invalid slot number. Use 0-4."
                )
    
    @pytest.mark.asyncio
    async def test_save_no_slot_argument(self, update, context):
        """Test saving without slot argument."""
        context.args = []
        
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.save_state.return_value = b"save_data"
            mock_mgr.get_controller.return_value = mock_controller
            
            with patch("src.handlers.commands.state_manager") as mock_state:
                mock_state.list_save_slots = MagicMock(return_value=[])
                mock_state.save_to_slot = MagicMock()
                
                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.save_slots = 5
                    mock_settings.allowed_chat_ids = []
                    
                    await save_command(update, context)
                    
                    # Should find first available slot (0)
                    mock_state.save_to_slot.assert_called_once()
                    call_args = mock_state.save_to_slot.call_args
                    assert call_args[1]["slot_number"] == 0


class TestLoadCommand:
    """Test /load command."""
    
    @pytest.fixture
    def update(self):
        return MockUpdate()
    
    @pytest.fixture
    def context(self):
        return MockContext()
    
    @pytest.mark.asyncio
    async def test_load_no_game(self, update, context):
        """Test loading with no active game."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_mgr.get_controller.return_value = None
            
            await load_command(update, context)
            
            update.message.reply_text.assert_called_with(
                "No active game! Use /start_game first."
            )
    
    @pytest.mark.asyncio
    async def test_load_input_in_progress(self, update, context):
        """Test loading while input processing."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller
            
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = True
                mock_get_handler.return_value = mock_handler
                
                await load_command(update, context)
                
                update.message.reply_text.assert_called_with(
                    "⏳ Cannot load while input is being processed. Please wait..."
                )
    
    @pytest.mark.asyncio
    async def test_load_no_slots_available(self, update, context):
        """Test loading when no slots available."""
        context.args = []
        
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller
            
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = False
                mock_get_handler.return_value = mock_handler
                
                with patch("src.handlers.commands.state_manager") as mock_state:
                    mock_state.list_save_slots = MagicMock(return_value=[])
                    
                    await load_command(update, context)
                    
                    update.message.reply_text.assert_called_with(
                        "No save slots found. Use /save [slot] to create one."
                    )
    
    @pytest.mark.asyncio
    async def test_load_success(self, update, context):
        """Test successful load."""
        context.args = ["0"]
        
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller
            
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = False
                mock_handler.show_current_frame = AsyncMock(return_value=100)
                mock_get_handler.return_value = mock_handler
                
                with patch("src.handlers.commands.state_manager") as mock_state:
                    mock_state.load_from_slot = MagicMock(return_value=b"save_data")
                    
                    await load_command(update, context)
                    
                    mock_controller.load_state.assert_called_once_with(b"save_data")
                    update.message.reply_text.assert_called_with(
                        "📂 Loaded game from slot 0!"
                    )


class TestStatusCommand:
    """Test /status command."""
    
    @pytest.fixture
    def update(self):
        return MockUpdate()
    
    @pytest.fixture
    def context(self):
        return MockContext()
    
    @pytest.mark.asyncio
    async def test_status_no_game(self, update, context):
        """Test status with no active game."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_mgr.get_controller.return_value = None
            
            await status_command(update, context)
            
            call_args = update.message.reply_text.call_args
            assert "No active game" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_status_with_game(self, update, context):
        """Test status with active game."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller
            
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = False
                mock_handler._get_session.return_value = None
                mock_get_handler.return_value = mock_handler
                
                with patch("src.handlers.commands.state_manager") as mock_state:
                    mock_state.list_save_slots = MagicMock(return_value=[])
                    
                    await status_command(update, context)
                    
                    call_args = update.message.reply_text.call_args
                    assert "Game is active" in call_args[0][0]


class TestHelpCommand:
    """Test /help command."""
    
    @pytest.fixture
    def update(self):
        return MockUpdate()
    
    @pytest.fixture
    def context(self):
        return MockContext()
    
    @pytest.mark.asyncio
    async def test_help_shows_commands(self, update, context):
        """Test help shows available commands."""
        with patch("src.handlers.commands.create_help_text") as mock_help:
            mock_help.return_value = "Test help text"
            
            await help_command(update, context)
            
            update.message.reply_text.assert_called_once()
            call_args = update.message.reply_text.call_args
            assert call_args[0][0] == "Test help text"


class TestUnknownCommand:
    """Test unknown command handler."""
    
    @pytest.fixture
    def update(self):
        return MockUpdate()
    
    @pytest.fixture
    def context(self):
        return MockContext()
    
    @pytest.mark.asyncio
    async def test_unknown_command(self, update, context):
        """Test unknown command response."""
        await unknown_command(update, context)
        
        update.message.reply_text.assert_called_with(
            "❓ Unknown command. Use /help to see available commands."
        )


class TestCommandHandlersDict:
    """Test command handlers dictionary."""
    
    def test_all_commands_present(self):
        """Test all expected commands are in the dictionary."""
        expected_commands = [
            "start_game",
            "current_frame",
            "save",
            "load",
            "status",
            "help",
        ]
        
        for cmd in expected_commands:
            assert cmd in COMMAND_HANDLERS
    
    def test_handlers_are_callable(self):
        """Test all handlers are callable."""
        for handler in COMMAND_HANDLERS.values():
            assert callable(handler)
