import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.handlers.commands import maintenance_command, COMMAND_HANDLERS


@pytest.fixture
def mock_update():
    """Create a mock Update object."""
    update = MagicMock()
    update.effective_chat.id = 123
    update.effective_chat.type = "group"
    update.effective_user.id = 456
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Create a mock Context object."""
    context = MagicMock()
    context.args = []
    context.bot = MagicMock()
    return context


@pytest.mark.asyncio
async def test_maintenance_command_in_command_handlers():
    """Test that maintenance command is registered."""
    assert 'maintenance' in COMMAND_HANDLERS
    assert COMMAND_HANDLERS['maintenance'] == maintenance_command


@pytest.mark.asyncio
async def test_maintenance_command_shows_status_when_no_args(mock_update, mock_context):
    """Test that /maintenance shows current status when no args."""
    with patch('src.handlers.commands.check_admin_permission', return_value=(True, None)):
        with patch('src.handlers.commands.state_manager') as mock_state:
            mock_config = MagicMock()
            mock_config.maintenance_mode = False
            mock_state.get_or_create_chat_config.return_value = mock_config
            
            await maintenance_command(mock_update, mock_context)
            
            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args[0][0]
            assert 'disabled' in call_args


@pytest.mark.asyncio
async def test_maintenance_command_enables_maintenance_mode(mock_update, mock_context):
    """Test that /maintenance on enables maintenance mode."""
    mock_context.args = ['on']
    
    with patch('src.handlers.commands.check_admin_permission', return_value=(True, None)):
            with patch('src.handlers.commands.state_manager') as mock_state:
                mock_config = MagicMock()
                mock_config.maintenance_mode = False
                mock_state.get_or_create_chat_config.return_value = mock_config
                
                await maintenance_command(mock_update, mock_context)
                
                assert mock_config.maintenance_mode is True
                mock_state.save_chat_config.assert_called_once_with(mock_config)


@pytest.mark.asyncio
async def test_maintenance_command_disables_maintenance_mode(mock_update, mock_context):
    """Test that /maintenance off disables maintenance mode."""
    mock_context.args = ['off']
    
    with patch('src.handlers.commands.check_admin_permission', return_value=(True, None)):
        with patch('src.handlers.commands.state_manager') as mock_state:
            mock_config = MagicMock()
            mock_config.maintenance_mode = True
            mock_state.get_or_create_chat_config.return_value = mock_config
            
            await maintenance_command(mock_update, mock_context)
            
            assert mock_config.maintenance_mode is False
            mock_state.save_chat_config.assert_called_once_with(mock_config)


@pytest.mark.asyncio
async def test_maintenance_command_rejects_non_admin(mock_update, mock_context):
    """Test that non-admins cannot use /maintenance."""
    mock_context.args = ['on']
    
    with patch('src.handlers.commands.check_admin_permission', return_value=(False, "Admin only")):
        await maintenance_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once_with("Admin only")


@pytest.mark.asyncio
async def test_maintenance_command_rejects_invalid_args(mock_update, mock_context):
    """Test that invalid args show error."""
    mock_context.args = ['invalid']
    
    with patch('src.handlers.commands.check_admin_permission', return_value=(True, None)):
        await maintenance_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert 'Invalid argument' in call_args
