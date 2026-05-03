import pytest
from unittest.mock import MagicMock, patch

from src.adapters.base import CommandContext
from src.handlers.commands import maintenance_command, COMMAND_HANDLERS


def make_ctx(mock_adapter, args=None, chat_id=123):
    return CommandContext(
        chat_id=chat_id,
        user_id=456,
        user_name="TestUser",
        args=args if args is not None else [],
        adapter=mock_adapter,
        raw=None,
    )


@pytest.mark.asyncio
async def test_maintenance_command_in_command_handlers():
    assert 'maintenance' in COMMAND_HANDLERS
    assert COMMAND_HANDLERS['maintenance'] == maintenance_command


@pytest.mark.asyncio
async def test_maintenance_command_shows_status_when_no_args(mock_adapter):
    ctx = make_ctx(mock_adapter, args=[])

    with patch('src.handlers.commands.check_admin_permission', return_value=(True, None)):
        with patch('src.handlers.commands.state_manager') as mock_state:
            with patch('src.handlers.commands.translation_manager') as mock_tm:
                mock_config = MagicMock()
                mock_config.maintenance_mode = False
                mock_state.get_or_create_chat_config.return_value = mock_config

                def mock_translate(key, chat_id, **kwargs):
                    if key == 'commands.maintenance.disabled':
                        return 'disabled'
                    if key == 'commands.maintenance.enabled':
                        return 'enabled'
                    if key == 'commands.maintenance.status':
                        return 'Maintenance mode is {status}.'.format(**kwargs)
                    return key
                mock_tm.get.side_effect = mock_translate

                await maintenance_command(ctx)

                mock_adapter.send_text.assert_called_once()
                call_args = mock_adapter.send_text.call_args[0]
                assert call_args[0] == 123
                assert 'disabled' in call_args[1]


@pytest.mark.asyncio
async def test_maintenance_command_enables_maintenance_mode(mock_adapter):
    ctx = make_ctx(mock_adapter, args=['on'])

    with patch('src.handlers.commands.check_admin_permission', return_value=(True, None)):
        with patch('src.handlers.commands.state_manager') as mock_state:
            with patch('src.handlers.commands.translation_manager'):
                mock_config = MagicMock()
                mock_config.maintenance_mode = False
                mock_state.get_or_create_chat_config.return_value = mock_config

                await maintenance_command(ctx)

                assert mock_config.maintenance_mode is True
                mock_state.save_chat_config.assert_called_once_with(mock_config)


@pytest.mark.asyncio
async def test_maintenance_command_disables_maintenance_mode(mock_adapter):
    ctx = make_ctx(mock_adapter, args=['off'])

    with patch('src.handlers.commands.check_admin_permission', return_value=(True, None)):
        with patch('src.handlers.commands.state_manager') as mock_state:
            with patch('src.handlers.commands.translation_manager'):
                mock_config = MagicMock()
                mock_config.maintenance_mode = True
                mock_state.get_or_create_chat_config.return_value = mock_config

                await maintenance_command(ctx)

                assert mock_config.maintenance_mode is False
                mock_state.save_chat_config.assert_called_once_with(mock_config)


@pytest.mark.asyncio
async def test_maintenance_command_rejects_non_admin(mock_adapter):
    ctx = make_ctx(mock_adapter, args=['on'])

    with patch('src.handlers.commands.check_admin_permission', return_value=(False, "Admin only")):
        await maintenance_command(ctx)

        mock_adapter.send_text.assert_called_once_with(123, "Admin only")


@pytest.mark.asyncio
async def test_maintenance_command_rejects_invalid_args(mock_adapter):
    ctx = make_ctx(mock_adapter, args=['invalid'])

    with patch('src.handlers.commands.check_admin_permission', return_value=(True, None)):
        with patch('src.handlers.commands.translation_manager') as mock_tm:
            mock_tm.get.return_value = "Invalid argument. Use `on` or `off`."

            await maintenance_command(ctx)

            mock_adapter.send_text.assert_called_once()
            call_args = mock_adapter.send_text.call_args[0]
            assert call_args[0] == 123
            assert 'Invalid argument' in call_args[1]
