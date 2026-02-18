import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.handlers.webhook import WebhookHandler


@pytest.fixture
def webhook_handler():
    """Create a WebhookHandler instance."""
    return WebhookHandler()


@pytest.fixture
def mock_update():
    """Create a mock Update with callback query."""
    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.message.chat.id = 123
    update.callback_query.from_user.id = 456
    update.callback_query.data = "btn_up"
    update.callback_query.answer = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_callback_blocked_when_maintenance_mode_enabled_and_non_admin(webhook_handler, mock_update):
    """Test that button press is blocked when maintenance mode is on and user is not admin."""
    with patch('src.handlers.webhook.state_manager') as mock_state:
        mock_config = MagicMock()
        mock_config.maintenance_mode = True
        mock_state.get_or_create_chat_config.return_value = mock_config
        
        # Mock get_chat_member to return non-admin
        mock_member = MagicMock()
        mock_member.status = "member"
        mock_update.callback_query.bot.get_chat_member = AsyncMock(return_value=mock_member)
        
        # Mock is_valid_button_callback to return True
        with patch('src.handlers.webhook.is_valid_button_callback', return_value=True):
            await webhook_handler._handle_callback_query(mock_update)
            
            # Verify callback was answered with maintenance message
            mock_update.callback_query.answer.assert_called_once_with(
                "No momento estamos em manutenção, apenas admins podem enviar comandos."
            )


@pytest.mark.asyncio
async def test_callback_allowed_when_maintenance_mode_enabled_and_admin(webhook_handler, mock_update):
    """Test that button press is allowed when maintenance mode is on and user is admin."""
    with patch('src.handlers.webhook.state_manager') as mock_state:
        mock_config = MagicMock()
        mock_config.maintenance_mode = True
        mock_state.get_or_create_chat_config.return_value = mock_config
        
        # Mock get_chat_member to return admin
        mock_member = MagicMock()
        mock_member.status = "administrator"
        mock_update.callback_query.bot.get_chat_member = AsyncMock(return_value=mock_member)
        
        # Mock is_valid_button_callback to return True
        with patch('src.handlers.webhook.is_valid_button_callback', return_value=True):
            # Mock input_handler
            webhook_handler.input_handler = MagicMock()
            webhook_handler.input_handler.handle_button_press = AsyncMock()
            
            await webhook_handler._handle_callback_query(mock_update)
            
            # Verify handle_button_press was called
            webhook_handler.input_handler.handle_button_press.assert_called_once_with(mock_update.callback_query)


@pytest.mark.asyncio
async def test_callback_allowed_when_maintenance_mode_disabled(webhook_handler, mock_update):
    """Test that button press is allowed when maintenance mode is off."""
    with patch('src.handlers.webhook.state_manager') as mock_state:
        mock_config = MagicMock()
        mock_config.maintenance_mode = False
        mock_state.get_or_create_chat_config.return_value = mock_config
        
        # Mock is_valid_button_callback to return True
        with patch('src.handlers.webhook.is_valid_button_callback', return_value=True):
            # Mock input_handler
            webhook_handler.input_handler = MagicMock()
            webhook_handler.input_handler.handle_button_press = AsyncMock()
            
            await webhook_handler._handle_callback_query(mock_update)
            
            # Verify handle_button_press was called without checking admin status
            webhook_handler.input_handler.handle_button_press.assert_called_once_with(mock_update.callback_query)
            mock_update.callback_query.bot.get_chat_member.assert_not_called()
