
import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.game_state import ChatConfig, SaveSlotInfo, GameButton
from src.handlers.commands import _ensure_game_active

@pytest.mark.asyncio
async def test_auto_save_on_input():
    """Test that input triggers auto-save when enabled."""
    from src.handlers.input_handler import InputHandler
    
    # Mock dependencies
    mock_bot = MagicMock()
    handler = InputHandler(mock_bot)
    
    # Mock chat config with auto-save enabled
    mock_config = ChatConfig(chat_id=123, auto_save_enabled=True)
    
    with patch("src.handlers.input_handler.state_manager") as mock_state_mgr:
        with patch("src.handlers.input_handler.game_controller_manager") as mock_game_mgr:
            # Setup mocks
            mock_state_mgr.get_or_create_chat_config.return_value = mock_config
            mock_state_mgr.find_next_auto_save_slot.return_value = 2
            
            mock_controller = MagicMock()
            mock_controller.save_state.return_value = b"save_data"
            mock_game_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            
            # Mock animation methods to avoid side effects
            handler._edit_message_keyboard = AsyncMock()
            handler._animate_frames = AsyncMock()
            handler._edit_message_caption = AsyncMock()
            handler._edit_message_media = AsyncMock()
            
            # Execute input processing
            await handler._process_input(123, GameButton.A, 456)
            
            # Verify auto-save was called
            mock_state_mgr.save_to_slot.assert_called_once()
            call_args = mock_state_mgr.save_to_slot.call_args
            assert call_args[1]["chat_id"] == 123
            assert call_args[1]["slot_number"] == 2
            assert call_args[1]["is_auto_save"] is True
            assert call_args[1]["state_data"] == b"save_data"

@pytest.mark.asyncio
async def test_no_auto_save_when_disabled():
    """Test that input does NOT trigger auto-save when disabled."""
    from src.handlers.input_handler import InputHandler
    
    # Mock dependencies
    mock_bot = MagicMock()
    handler = InputHandler(mock_bot)
    
    # Mock chat config with auto-save DISABLED
    mock_config = ChatConfig(chat_id=123, auto_save_enabled=False)
    
    with patch("src.handlers.input_handler.state_manager") as mock_state_mgr:
        with patch("src.handlers.input_handler.game_controller_manager") as mock_game_mgr:
            # Setup mocks
            mock_state_mgr.get_or_create_chat_config.return_value = mock_config
            
            mock_controller = MagicMock()
            mock_game_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            
            # Mock animation methods
            handler._edit_message_keyboard = AsyncMock()
            handler._animate_frames = AsyncMock()
            handler._edit_message_caption = AsyncMock()
            handler._edit_message_media = AsyncMock()
            
            # Execute input processing
            await handler._process_input(123, GameButton.A, 456)
            
            # Verify auto-save was NOT called
            mock_state_mgr.save_to_slot.assert_not_called()

@pytest.mark.asyncio
async def test_ensure_game_active_loads_latest_auto_save():
    """Test that _ensure_game_active loads the most recent auto-save."""
    chat_id = 123
    
    # Create mock slots
    now = datetime.now()
    slots = [
        SaveSlotInfo(slot_number=0, created_at=now - timedelta(hours=1), is_auto_save=True),
        SaveSlotInfo(slot_number=1, created_at=now, is_auto_save=False), # Newer but manual save
        SaveSlotInfo(slot_number=2, created_at=now - timedelta(minutes=30), is_auto_save=True), # Recent auto-save
        SaveSlotInfo(slot_number=3, created_at=now - timedelta(hours=2), is_auto_save=True),
    ]
    
    with patch("src.handlers.commands.state_manager") as mock_state_mgr:
        with patch("src.handlers.commands.game_controller_manager") as mock_game_mgr:
            # Setup mocks
            mock_game_mgr.get_controller.return_value = None # No active game
            mock_game_mgr.get_or_create_controller = AsyncMock(return_value=MagicMock())
            
            mock_state_mgr.list_save_slots.return_value = slots
            mock_state_mgr.load_from_slot.return_value = b"game_state"
            
            # Execute
            success, error = await _ensure_game_active(chat_id)
            
            # Verify success
            assert success is True
            assert error is None
            
            # Verify it loaded slot 2 (most recent auto-save)
            # Slot 1 is newer but not auto-save. Slot 0 and 3 are older auto-saves.
            mock_state_mgr.load_from_slot.assert_called_once_with(chat_id, 2)
