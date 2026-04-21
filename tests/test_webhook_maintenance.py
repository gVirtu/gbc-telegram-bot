import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.adapters.telegram import _admin_cache

from src.handlers.webhook import WebhookHandler


@pytest.fixture
def webhook_handler():
    """Create a WebhookHandler instance."""
    handler = WebhookHandler()
    # Set up a mock telegram adapter
    mock_adapter = MagicMock()
    mock_adapter.is_admin = AsyncMock(return_value=False)
    mock_adapter.answer_interaction = AsyncMock()
    mock_adapter.build_game_keyboard = AsyncMock(return_value=None)
    handler._telegram_adapter = mock_adapter
    return handler


@pytest.fixture
def mock_update():
    """Create a mock Update with callback query."""
    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.message.chat.id = 123
    update.callback_query.message.message_id = 999
    update.callback_query.from_user.id = 456
    update.callback_query.from_user.first_name = "TestUser"
    update.callback_query.from_user.username = None
    update.callback_query.data = "up"
    update.callback_query.answer = AsyncMock()
    update.effective_chat = MagicMock()
    update.effective_chat.type = "group"
    update.effective_chat.id = 123
    update.effective_user = MagicMock()
    update.effective_user.id = 456
    update.effective_user.first_name = "TestUser"
    update.effective_user.username = None
    update.message = None
    return update


@pytest.mark.asyncio
async def test_callback_blocked_when_maintenance_mode_enabled_and_non_admin(webhook_handler, mock_update):
    """Test that button press is blocked when maintenance mode is on and user is not admin."""
    with patch('src.handlers.webhook.state_manager') as mock_state:
        mock_config = MagicMock()
        mock_config.maintenance_mode = True
        mock_state.get_or_create_chat_config.return_value = mock_config

        # Clear cache
        _admin_cache.clear()

        # Adapter reports non-admin
        webhook_handler._telegram_adapter.is_admin = AsyncMock(return_value=False)

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

        # Clear cache
        _admin_cache.clear()

        # Adapter reports admin
        webhook_handler._telegram_adapter.is_admin = AsyncMock(return_value=True)

        # Mock is_valid_button_callback to return True
        with patch('src.handlers.webhook.is_valid_button_callback', return_value=True):
            # Mock input_handler
            webhook_handler.input_handler = MagicMock()
            webhook_handler.input_handler.handle_button_press = AsyncMock()

            await webhook_handler._handle_callback_query(mock_update)

            # Verify handle_button_press was called
            webhook_handler.input_handler.handle_button_press.assert_called_once()
            call_kwargs = webhook_handler.input_handler.handle_button_press.call_args
            assert call_kwargs.kwargs.get("chat_id") == 123 or call_kwargs.args[1] == 123


@pytest.mark.asyncio
async def test_callback_allowed_when_maintenance_mode_disabled(webhook_handler, mock_update):
    """Test that button press is allowed when maintenance mode is off."""
    with patch('src.handlers.webhook.state_manager') as mock_state:
        mock_config = MagicMock()
        mock_config.maintenance_mode = False
        mock_state.get_or_create_chat_config.return_value = mock_config

        # Clear cache
        _admin_cache.clear()

        # Mock is_valid_button_callback to return True
        with patch('src.handlers.webhook.is_valid_button_callback', return_value=True):
            # Mock input_handler
            webhook_handler.input_handler = MagicMock()
            webhook_handler.input_handler.handle_button_press = AsyncMock()

            await webhook_handler._handle_callback_query(mock_update)

            # Verify handle_button_press was called without checking admin status
            webhook_handler.input_handler.handle_button_press.assert_called_once()
            webhook_handler._telegram_adapter.is_admin.assert_not_called()
