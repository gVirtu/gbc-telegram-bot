
import asyncio
import pytest
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
            mock_controller.begin_polished_crystal_hooks.return_value = {}
            mock_game_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            
            # Mock animation methods to avoid side effects
            handler._edit_message_keyboard = AsyncMock()
            handler._edit_message_media = AsyncMock()
            
            # Execute input processing
            await handler._process_sequence(123, [GameButton.A], 456)
            
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
            mock_controller.begin_polished_crystal_hooks.return_value = {}
            mock_game_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            
            # Mock animation methods
            handler._edit_message_keyboard = AsyncMock()
            handler._edit_message_media = AsyncMock()
            
            # Execute input processing
            await handler._process_sequence(123, [GameButton.A], 456)
            
            # Verify auto-save was NOT called
            mock_state_mgr.save_to_slot.assert_not_called()

@pytest.mark.asyncio
async def test_ensure_game_active_loads_latest_auto_save():
    """Test that _ensure_game_active delegates to get_or_create_controller.

    Note: The actual save loading logic is now in get_or_create_controller in src.game.
    This test verifies _ensure_game_active properly delegates to it.
    """
    chat_id = 123
    
    with patch("src.handlers.commands.game_controller_manager") as mock_game_mgr:
        mock_controller = MagicMock()
        mock_controller.is_initialized.return_value = True
        mock_game_mgr.get_controller.return_value = None
        mock_game_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
        
        success, error = await _ensure_game_active(chat_id)
        
        assert success is True
        assert error is None
        mock_game_mgr.get_or_create_controller.assert_called_once_with(chat_id)
