"""Tests for command handlers.

This module tests all bot commands including /start_game, /resume, /print,
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

from src.adapters.base import CommandContext

from src.handlers.commands import (
    start_game_command,
    resume_command,
    reboot_command,
    print_command,
    save_command,
    load_command,
    status_command,
    help_command,
    unknown_command,
    message_command,
    language_command,
    _ensure_game_active,
    COMMAND_HANDLERS,
)
from src.models.game_state import GameButton


def make_ctx(mock_adapter, args=None, chat_id=123456, user_id=456):
    return CommandContext(
        chat_id=chat_id,
        user_id=user_id,
        user_name="TestUser",
        args=args or [],
        adapter=mock_adapter,
        raw=None,
    )


class TestStartGameCommand:
    """Test /start_game command."""

    @pytest.mark.asyncio
    async def test_start_game_success(self, mock_adapter, mock_ctx):
        """Test successful game start."""
        with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
            mock_handler = MagicMock()
            mock_handler.cleanup_session = MagicMock()
            mock_handler.start_game = AsyncMock(return_value=100)
            mock_get_handler.return_value = mock_handler

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await start_game_command(mock_ctx)

                # Should clean up existing session
                mock_handler.cleanup_session.assert_called_once_with(123456)
                # Should start new game
                mock_handler.start_game.assert_called_once_with(123456, mock_adapter)

    @pytest.mark.asyncio
    async def test_start_game_error(self, mock_adapter, mock_ctx):
        """Test game start with error."""
        with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
            mock_handler = MagicMock()
            mock_handler.cleanup_session = MagicMock()
            mock_handler.start_game = AsyncMock(side_effect=Exception("ROM not found"))
            mock_get_handler.return_value = mock_handler

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await start_game_command(mock_ctx)

                # Should send error message
                mock_adapter.send_text.assert_called_with(
                    123456,
                    mock_adapter.send_text.call_args[0][1],
                )


class TestResumeCommand:
    """Test /resume command."""

    @pytest.mark.asyncio
    async def test_resume_with_active_game(self, mock_adapter, mock_ctx):
        """Test resuming when game is already active."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller

            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = False
                mock_handler.resume_game = AsyncMock(return_value=100)
                mock_get_handler.return_value = mock_handler

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []

                    await resume_command(mock_ctx)

                    mock_handler.resume_game.assert_called_once_with(123456, mock_adapter)

    @pytest.mark.asyncio
    async def test_resume_auto_starts_game(self, mock_adapter, mock_ctx):
        """Test resume auto-starts game when not active."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            # First call returns None (no game), second returns controller (after auto-start)
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.side_effect = [None, mock_controller]
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            with patch("src.handlers.commands.state_manager") as mock_state:
                mock_state.list_save_slots.return_value = []
                mock_state.load_from_slot.return_value = None  # No slot 1

                with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                    mock_handler = MagicMock()
                    mock_handler.is_input_in_progress.return_value = False
                    mock_handler.resume_game = AsyncMock(return_value=100)
                    mock_get_handler.return_value = mock_handler

                    with patch("src.handlers.commands.settings") as mock_settings:
                        mock_settings.allowed_chat_ids = []

                        await resume_command(mock_ctx)

                        # Should auto-start the game
                        mock_mgr.get_or_create_controller.assert_called_once_with(
                            123456, auto_load=True
                        )
                        mock_handler.resume_game.assert_called_once_with(123456, mock_adapter)

    @pytest.mark.asyncio
    async def test_input_in_progress(self, mock_adapter, mock_ctx):
        """Test resuming while input processing."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller

            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = True
                mock_get_handler.return_value = mock_handler

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []

                    await resume_command(mock_ctx)

                    mock_adapter.send_text.assert_called_once()
                    call_text = mock_adapter.send_text.call_args[0][1]
                    assert "wait" in call_text.lower() or "processing" in call_text.lower() or "button" in call_text.lower()


class TestSaveCommand:
    """Test /save command."""

    @pytest.mark.asyncio
    async def test_save_auto_starts_game(self, mock_adapter):
        """Test save auto-starts game when not active."""
        ctx = make_ctx(mock_adapter, args=["2"])

        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.save_state.return_value = b"save_data"
            mock_mgr.get_controller.side_effect = [None, mock_controller]
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            with patch("src.handlers.commands.state_manager") as mock_state:
                mock_state.list_save_slots.return_value = []
                mock_state.load_from_slot.return_value = None  # No slot 1
                mock_state.save_to_slot = MagicMock()

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []
                    mock_settings.save_slots = 5

                    await save_command(ctx)

                    # Should auto-start the game
                    mock_mgr.get_or_create_controller.assert_called_once_with(
                        123456, auto_load=True
                    )
                    mock_state.save_to_slot.assert_called_once()
                    call_args = mock_state.save_to_slot.call_args
                    assert call_args[1]["slot_number"] == 2

    @pytest.mark.asyncio
    async def test_save_to_specific_slot(self, mock_adapter):
        """Test saving to specific slot."""
        ctx = make_ctx(mock_adapter, args=["2"])

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

                    await save_command(ctx)

                    mock_state.save_to_slot.assert_called_once()
                    call_args = mock_state.save_to_slot.call_args
                    assert call_args[1]["slot_number"] == 2

    @pytest.mark.asyncio
    async def test_save_invalid_slot(self, mock_adapter):
        """Test saving to invalid slot."""
        ctx = make_ctx(mock_adapter, args=["99"])

        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.save_slots = 5
                mock_settings.allowed_chat_ids = []

                await save_command(ctx)

                mock_adapter.send_text.assert_called_once()
                call_text = mock_adapter.send_text.call_args[0][1]
                assert "invalid" in call_text.lower() or "slot" in call_text.lower()

    @pytest.mark.asyncio
    async def test_save_no_slot_argument(self, mock_adapter, mock_ctx):
        """Test saving without slot argument."""
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

                    await save_command(mock_ctx)

                    # Should find first available slot (0)
                    mock_state.save_to_slot.assert_called_once()
                    call_args = mock_state.save_to_slot.call_args
                    assert call_args[1]["slot_number"] == 0


class TestLoadCommand:
    """Test /load command."""

    @pytest.mark.asyncio
    async def test_load_auto_starts_game(self, mock_adapter):
        """Test load auto-starts game when not active.

        Note: Save loading logic is now handled internally by get_or_create_controller.
        This test verifies the command properly triggers game initialization.
        """
        ctx = make_ctx(mock_adapter, args=["0"])

        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = None
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = False
                mock_handler.show_current_frame = AsyncMock(return_value=100)
                mock_get_handler.return_value = mock_handler

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []
                    mock_settings.save_slots = 5

                    await load_command(ctx)

                    mock_mgr.get_or_create_controller.assert_called_once_with(
                        123456, auto_load=True
                    )

    @pytest.mark.asyncio
    async def test_load_input_in_progress(self, mock_adapter, mock_ctx):
        """Test loading while input processing."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller

            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = True
                mock_get_handler.return_value = mock_handler

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []

                    await load_command(mock_ctx)

                    mock_adapter.send_text.assert_called_once()
                    call_text = mock_adapter.send_text.call_args[0][1]
                    assert "wait" in call_text.lower() or "loading" in call_text.lower() or "button" in call_text.lower()

    @pytest.mark.asyncio
    async def test_load_no_slots_available(self, mock_adapter, mock_ctx):
        """Test loading when no slots available."""
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

                    with patch("src.handlers.commands.settings") as mock_settings:
                        mock_settings.allowed_chat_ids = []

                        await load_command(mock_ctx)

                        mock_adapter.send_text.assert_called_once()
                        call_text = mock_adapter.send_text.call_args[0][1]
                        assert "slot" in call_text.lower() or "save" in call_text.lower()

    @pytest.mark.asyncio
    async def test_load_success(self, mock_adapter):
        """Test successful load."""
        ctx = make_ctx(mock_adapter, args=["0"])

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

                    with patch("src.handlers.commands.settings") as mock_settings:
                        mock_settings.allowed_chat_ids = []
                        mock_settings.save_slots = 5

                        with patch("src.handlers.commands.broadcast_text", new_callable=AsyncMock) as mock_bcast:
                            await load_command(ctx)

                            mock_controller.load_state.assert_called_once_with(b"save_data")
                            mock_bcast.assert_called_once()
                            call_text = mock_bcast.call_args[0][1]
                            assert "0" in call_text or "load" in call_text.lower()


class TestLoadBackupCommand:
    """Test /load backup YYYYMMDD subcommand."""

    def _active_game_patches(self, mock_mgr, mock_handler):
        """Set up mocks for an active, non-processing game."""
        mock_controller = MagicMock()
        mock_controller.is_initialized.return_value = True
        mock_mgr.get_controller.return_value = mock_controller
        mock_handler.is_input_in_progress.return_value = False
        return mock_controller

    @pytest.mark.asyncio
    async def test_load_backup_valid_date_admin(self, mock_adapter):
        """Admin loading a valid backup date succeeds."""
        ctx = make_ctx(mock_adapter, args=["backup", "20260215"])

        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_controller = self._active_game_patches(mock_mgr, mock_handler)
                mock_get_handler.return_value = mock_handler

                mock_backup_mgr = MagicMock()
                mock_backup_mgr.load_backup.return_value = b"backup_bytes"

                with patch("src.handlers.commands._get_backup_manager", return_value=mock_backup_mgr):
                    with patch("src.handlers.commands.settings") as mock_settings:
                        mock_settings.allowed_chat_ids = []
                        mock_settings.save_slots = 5

                        with patch("src.handlers.commands.broadcast_text", new_callable=AsyncMock) as mock_bcast:
                            await load_command(ctx)

                            mock_backup_mgr.load_backup.assert_called_once_with(123456, "20260215")
                            mock_controller.load_state.assert_called_once_with(b"backup_bytes")
                            mock_bcast.assert_called_once()
                            call_text = mock_bcast.call_args[0][1]
                            assert "20260215" in call_text

    @pytest.mark.asyncio
    async def test_load_backup_not_admin(self, mock_adapter):
        """Non-admin in group chat gets permission error."""
        ctx = make_ctx(mock_adapter, args=["backup", "20260215"])
        ctx.adapter.is_admin = AsyncMock(return_value=False)

        with patch("src.handlers.commands.check_admin_permission", return_value=(False, "🔒 Only group administrators can use this command.")):
            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await load_command(ctx)

                mock_adapter.send_text.assert_called_with(
                    123456,
                    "🔒 Only group administrators can use this command.",
                )

    @pytest.mark.asyncio
    async def test_load_backup_invalid_date(self, mock_adapter):
        """Invalid date format returns a helpful error message."""
        ctx = make_ctx(mock_adapter, args=["backup", "not-a-date"])

        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                self._active_game_patches(mock_mgr, mock_handler)
                mock_get_handler.return_value = mock_handler

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []
                    mock_settings.save_slots = 5

                    await load_command(ctx)

                    mock_adapter.send_text.assert_called_once()
                    call_text = mock_adapter.send_text.call_args[0][1]
                    assert "date" in call_text.lower() or "format" in call_text.lower() or "yyyymmdd" in call_text.lower()

    @pytest.mark.asyncio
    async def test_load_backup_not_found(self, mock_adapter):
        """Missing backup lists available dates."""
        ctx = make_ctx(mock_adapter, args=["backup", "20260101"])

        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                self._active_game_patches(mock_mgr, mock_handler)
                mock_get_handler.return_value = mock_handler

                mock_backup_mgr = MagicMock()
                mock_backup_mgr.load_backup.return_value = None
                mock_backup_mgr.list_backups.return_value = ["20260102", "20260103"]

                with patch("src.handlers.commands._get_backup_manager", return_value=mock_backup_mgr):
                    with patch("src.handlers.commands.settings") as mock_settings:
                        mock_settings.allowed_chat_ids = []
                        mock_settings.save_slots = 5
                        mock_settings.default_language = "pt-BR"

                        await load_command(ctx)

                        mock_adapter.send_text.assert_called_once()
                        call_text = mock_adapter.send_text.call_args[0][1]
                        assert "20260101" in call_text

    @pytest.mark.asyncio
    async def test_load_backup_missing_date_arg(self, mock_adapter):
        """'/load backup' without a date shows usage hint."""
        ctx = make_ctx(mock_adapter, args=["backup"])

        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                self._active_game_patches(mock_mgr, mock_handler)
                mock_get_handler.return_value = mock_handler

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []
                    mock_settings.save_slots = 5

                    await load_command(ctx)

                    mock_adapter.send_text.assert_called_once()
                    call_text = mock_adapter.send_text.call_args[0][1]
                    assert "usage" in call_text.lower() or "backup" in call_text.lower() or "yyyymmdd" in call_text.lower()


class TestStatusCommand:
    """Test /status command."""

    @pytest.mark.asyncio
    async def test_status_auto_starts_game(self, mock_adapter, mock_ctx):
        """Test status auto-starts game when not active."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.side_effect = [None, mock_controller]
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            with patch("src.handlers.commands.state_manager") as mock_state:
                mock_state.list_save_slots.return_value = []
                mock_state.load_from_slot.return_value = None  # No slot 1
                mock_state.list_save_slots = MagicMock(return_value=[])

                with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                    mock_handler = MagicMock()
                    mock_handler.is_input_in_progress.return_value = False
                    mock_handler._get_session.return_value = None
                    mock_get_handler.return_value = mock_handler

                    with patch("src.handlers.commands.settings") as mock_settings:
                        mock_settings.allowed_chat_ids = []

                        await status_command(mock_ctx)

                        # Should auto-start and show active status
                        mock_mgr.get_or_create_controller.assert_called_once_with(
                            123456, auto_load=True
                        )
                        mock_adapter.send_text.assert_called_once()
                        call_text = mock_adapter.send_text.call_args[0][1]
                        assert "Game active" in call_text

    @pytest.mark.asyncio
    async def test_status_with_active_game(self, mock_adapter, mock_ctx):
        """Test status with already active game."""
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

                    with patch("src.handlers.commands.settings") as mock_settings:
                        mock_settings.allowed_chat_ids = []

                        await status_command(mock_ctx)

                        mock_adapter.send_text.assert_called_once()
                        call_text = mock_adapter.send_text.call_args[0][1]
                        assert "Game active" in call_text


class TestHelpCommand:
    """Test /help command."""

    @pytest.mark.asyncio
    async def test_help_shows_commands(self, mock_adapter, mock_ctx):
        """Test help shows available commands."""
        with patch("src.handlers.commands.create_help_text") as mock_help:
            mock_help.return_value = "Test help text"

            await help_command(mock_ctx)

            mock_adapter.send_text.assert_called_once()
            call_args = mock_adapter.send_text.call_args
            assert call_args[0][1] == "Test help text"


class TestUnknownCommand:
    """Test unknown command handler."""

    @pytest.mark.asyncio
    async def test_unknown_command(self, mock_adapter, mock_ctx):
        """Test unknown command response."""
        await unknown_command(mock_ctx)

        mock_adapter.send_text.assert_called_once()
        call_text = mock_adapter.send_text.call_args[0][1]
        assert "unknown" in call_text.lower() or "help" in call_text.lower()


class TestCommandHandlersDict:
    """Test command handlers dictionary."""

    def test_all_commands_present(self):
        """Test all expected commands are in the dictionary."""
        expected_commands = [
            "start_game",
            "resume",
            "reboot",
            "print",
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


class TestEnsureGameActive:
    """Test _ensure_game_active helper function."""

    @pytest.mark.asyncio
    async def test_game_already_active(self):
        """Test when game is already active."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller

            success, error = await _ensure_game_active(123456)

            assert success is True
            assert error is None
            mock_mgr.get_or_create_controller.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_start_with_slot_1(self):
        """Test auto-start loads slot 1 when available.

        Note: Save loading logic is now in get_or_create_controller in src.game.
        This test verifies _ensure_game_active properly delegates to it.
        """
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = None
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            success, error = await _ensure_game_active(123456)

            assert success is True
            assert error is None
            mock_mgr.get_or_create_controller.assert_called_once_with(
                123456, auto_load=True
            )

    @pytest.mark.asyncio
    async def test_auto_start_without_slot_1(self):
        """Test auto-start uses initial state when slot 1 doesn't exist.

        Note: Save loading logic is now in get_or_create_controller in src.game.
        This test verifies _ensure_game_active properly delegates to it.
        """
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = None
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            success, error = await _ensure_game_active(123456)

            assert success is True
            assert error is None
            mock_mgr.get_or_create_controller.assert_called_once_with(
                123456, auto_load=True
            )

    @pytest.mark.asyncio
    async def test_slot_1_load_failure(self):
        """Test auto-start handles slot 1 load failure gracefully."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = None
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            with patch("src.handlers.commands.state_manager") as mock_state:
                from src.models.game_state import SaveSlotInfo
                mock_state.list_save_slots.return_value = [
                    SaveSlotInfo(slot_number=1, is_auto_save=False)
                ]
                mock_state.load_from_slot.return_value = b"corrupted_data"
                mock_controller.load_state.side_effect = Exception("Corrupted save")

                success, error = await _ensure_game_active(123456)

                assert success is True
                assert error is None
                # Should fall back to initial state

    @pytest.mark.asyncio
    async def test_auto_start_failure(self):
        """Test when auto-start fails completely."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_mgr.get_controller.return_value = None
            mock_mgr.get_or_create_controller = AsyncMock(side_effect=Exception("ROM not found"))

            success, error = await _ensure_game_active(123456)

            assert success is False
            assert error is not None
            assert "Failed to start the game" in error


class TestPrintCommand:
    """Test /print command."""

    @pytest.mark.asyncio
    async def test_print_auto_starts_game(self, mock_adapter):
        """Test print auto-starts game when not active."""
        ctx = make_ctx(mock_adapter)

        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.get_frame_as_png.return_value = b"png_data"
            mock_mgr.get_controller.side_effect = [None, mock_controller]
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            with patch("src.handlers.commands.state_manager") as mock_state:
                mock_state.list_save_slots.return_value = []
                mock_state.load_from_slot.return_value = None  # No slot 1

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []

                    await print_command(ctx)

                    # Should auto-start the game
                    mock_mgr.get_or_create_controller.assert_called_once_with(
                        123456, auto_load=True
                    )
                    mock_adapter.send_screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_print_with_active_game(self, mock_adapter, mock_ctx):
        """Test print when game is already active."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.get_frame_as_png.return_value = b"png_data"
            mock_mgr.get_controller.return_value = mock_controller

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await print_command(mock_ctx)

                mock_adapter.send_screenshot.assert_called_once()
                call_kwargs = mock_adapter.send_screenshot.call_args
                assert call_kwargs[1]["caption"] == "" or call_kwargs[0][2] == ""

    @pytest.mark.asyncio
    async def test_print_error(self, mock_adapter, mock_ctx):
        """Test print with error."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.get_frame_as_png.side_effect = Exception("Frame error")
            mock_mgr.get_controller.return_value = mock_controller

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []
                mock_settings.default_language = "pt-BR"

                await print_command(mock_ctx)

                mock_adapter.send_text.assert_called_once()
                call_text = mock_adapter.send_text.call_args[0][1]
                assert "failed" in call_text.lower() or "error" in call_text.lower() or "screen" in call_text.lower()


class TestAdminPermissions:
    """Test admin permission checking for restricted commands."""

    @pytest.mark.asyncio
    async def test_check_admin_permission_allowed(self, mock_adapter):
        """Test that is_admin returning True allows commands."""
        ctx = make_ctx(mock_adapter)
        ctx.adapter.is_admin = AsyncMock(return_value=True)

        from src.handlers.commands import check_admin_permission
        is_allowed, error_msg = await check_admin_permission(ctx)

        assert is_allowed is True
        assert error_msg is None

    @pytest.mark.asyncio
    async def test_check_admin_permission_group_admin(self, mock_adapter):
        """Test that group admins are allowed."""
        ctx = make_ctx(mock_adapter, user_id=789)
        ctx.adapter.is_admin = AsyncMock(return_value=True)

        from src.handlers.commands import check_admin_permission
        is_allowed, error_msg = await check_admin_permission(ctx)

        assert is_allowed is True
        assert error_msg is None

    @pytest.mark.asyncio
    async def test_check_admin_permission_group_creator(self, mock_adapter):
        """Test that group creators are allowed."""
        ctx = make_ctx(mock_adapter, user_id=789)
        ctx.adapter.is_admin = AsyncMock(return_value=True)

        from src.handlers.commands import check_admin_permission
        is_allowed, error_msg = await check_admin_permission(ctx)

        assert is_allowed is True
        assert error_msg is None

    @pytest.mark.asyncio
    async def test_check_admin_permission_group_regular_member(self, mock_adapter):
        """Test that regular group members are denied."""
        ctx = make_ctx(mock_adapter, user_id=999)
        ctx.adapter.is_admin = AsyncMock(return_value=False)

        from src.handlers.commands import check_admin_permission
        is_allowed, error_msg = await check_admin_permission(ctx)

        assert is_allowed is False
        assert error_msg is not None
        assert "admin" in error_msg.lower() or "administrator" in error_msg.lower() or "permission" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_admin_cache_functionality(self, mock_adapter):
        """Test that admin status is delegated to the adapter."""
        ctx = make_ctx(mock_adapter, user_id=789)
        ctx.adapter.is_admin = AsyncMock(return_value=True)

        from src.handlers.commands import check_admin_permission

        # First call
        await check_admin_permission(ctx)
        assert ctx.adapter.is_admin.call_count == 1

        # Second call - adapter is called again (no caching at this level)
        await check_admin_permission(ctx)
        assert ctx.adapter.is_admin.call_count == 2

    @pytest.mark.asyncio
    async def test_start_game_blocked_for_non_admin(self, mock_adapter):
        """Test that /start_game is blocked for non-admins in groups."""
        ctx = make_ctx(mock_adapter, user_id=888)
        ctx.adapter.is_admin = AsyncMock(return_value=False)

        with patch("src.handlers.commands.settings") as mock_settings:
            mock_settings.allowed_chat_ids = []

            await start_game_command(ctx)

            # Should send error message (permission denial)
            assert mock_adapter.send_text.called
            last_call_text = mock_adapter.send_text.call_args[0][1]
            assert "admin" in last_call_text.lower() or "administrator" in last_call_text.lower() or "permission" in last_call_text.lower()

    @pytest.mark.asyncio
    async def test_save_allowed_for_admin(self, mock_adapter):
        """Test that /save works for admins in groups."""
        ctx = make_ctx(mock_adapter, user_id=789)
        ctx.adapter.is_admin = AsyncMock(return_value=True)

        with patch('src.handlers.commands._ensure_game_active', new_callable=AsyncMock) as mock_ensure:
            mock_ensure.return_value = (True, None)
            with patch('src.handlers.commands.game_controller_manager') as mock_gcm:
                mock_controller = MagicMock()
                mock_controller.save_state = MagicMock(return_value=b"state_data")
                mock_gcm.get_controller.return_value = mock_controller

                with patch('src.handlers.commands.state_manager') as mock_sm:
                    mock_sm.list_save_slots = MagicMock(return_value=[])
                    mock_sm.save_to_slot = MagicMock()

                    with patch('src.handlers.commands.settings') as mock_settings:
                        mock_settings.allowed_chat_ids = []
                        mock_settings.save_slots = 5

                        await save_command(ctx)

                        # Should succeed (not blocked)
                        # Check that save was attempted
                        assert mock_controller.save_state.called

    @pytest.mark.asyncio
    async def test_load_allowed_in_private_chat(self, mock_adapter):
        """Test that /load works when adapter reports user is admin."""
        ctx = make_ctx(mock_adapter, args=["1"])
        ctx.adapter.is_admin = AsyncMock(return_value=True)

        with patch('src.handlers.commands._ensure_game_active', new_callable=AsyncMock) as mock_ensure:
            mock_ensure.return_value = (True, None)
            with patch('src.handlers.commands.game_controller_manager') as mock_gcm:
                mock_controller = MagicMock()
                mock_gcm.get_controller.return_value = mock_controller

                with patch('src.handlers.commands.get_input_handler') as mock_handler:
                    mock_input_handler = MagicMock()
                    mock_input_handler.is_input_in_progress.return_value = False
                    mock_input_handler.show_current_frame = AsyncMock()
                    mock_handler.return_value = mock_input_handler

                    with patch('src.handlers.commands.state_manager') as mock_sm:
                        mock_sm.load_from_slot.return_value = b"state_data"

                        with patch('src.handlers.commands.settings') as mock_settings:
                            mock_settings.allowed_chat_ids = []
                            mock_settings.save_slots = 5

                            await load_command(ctx)

                            # Should succeed - adapter.is_admin was called
                            ctx.adapter.is_admin.assert_called_once()


class TestMessageCommand:
    """Test /m command for custom message base text."""

    @pytest.mark.asyncio
    async def test_message_command_sets_custom_text(self, mock_adapter):
        """Test setting custom message base text."""
        ctx = make_ctx(mock_adapter, args=["Vamos", "jogar!"])

        with patch("src.handlers.commands.state_manager") as mock_state:
            mock_config = MagicMock()
            mock_config.message_base_text = None
            mock_state.get_or_create_chat_config.return_value = mock_config
            mock_state.save_chat_config = MagicMock()

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await message_command(ctx)

                assert mock_config.message_base_text == "Vamos jogar!"
                mock_state.save_chat_config.assert_called_once_with(mock_config)
                mock_adapter.send_text.assert_called_once()
                call_text = mock_adapter.send_text.call_args[0][1]
                assert "Vamos jogar!" in call_text

    @pytest.mark.asyncio
    async def test_message_command_clears_text(self, mock_adapter, mock_ctx):
        """Test clearing custom message base text (no args)."""
        with patch("src.handlers.commands.state_manager") as mock_state:
            mock_config = MagicMock()
            mock_config.message_base_text = "Custom text"
            mock_state.get_or_create_chat_config.return_value = mock_config
            mock_state.save_chat_config = MagicMock()

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await message_command(mock_ctx)

                assert mock_config.message_base_text is None
                mock_state.save_chat_config.assert_called_once_with(mock_config)
                mock_adapter.send_text.assert_called_once()
                call_text = mock_adapter.send_text.call_args[0][1]
                assert "clear" in call_text.lower() or "remov" in call_text.lower() or "custom" in call_text.lower()

    @pytest.mark.asyncio
    async def test_message_command_text_too_long(self, mock_adapter):
        """Test validation for text length limit."""
        ctx = make_ctx(mock_adapter, args=["x" * 241])  # 241 characters

        with patch("src.handlers.commands.state_manager") as mock_state:
            mock_config = MagicMock()
            mock_state.get_or_create_chat_config.return_value = mock_config

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await message_command(ctx)

                # Should not save, should show error
                mock_state.save_chat_config.assert_not_called()
                mock_adapter.send_text.assert_called_once()
                call_text = mock_adapter.send_text.call_args[0][1]
                assert "long" in call_text.lower() or "240" in call_text or "character" in call_text.lower()

    @pytest.mark.asyncio
    async def test_message_command_non_admin_blocked(self, mock_adapter):
        """Test that /m is blocked for non-admins in groups."""
        ctx = make_ctx(mock_adapter, args=["Hello"], user_id=999)

        with patch("src.handlers.commands.check_admin_permission") as mock_check:
            mock_check.return_value = (False, "🔒 Only group administrators can use this command.")

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await message_command(ctx)

                mock_adapter.send_text.assert_called_with(
                    123456,
                    "🔒 Only group administrators can use this command.",
                )

    @pytest.mark.asyncio
    async def test_message_command_in_command_handlers(self):
        """Test that 'm' is registered in COMMAND_HANDLERS."""
        assert "m" in COMMAND_HANDLERS
        assert COMMAND_HANDLERS["m"] == message_command


class TestRebootCommand:
    """Test /reboot command."""

    @pytest.mark.asyncio
    async def test_reboot_success(self, mock_adapter, mock_ctx):
        """Test successful reboot stops controller and starts fresh."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller
            mock_mgr.remove_controller = MagicMock(return_value=True)
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = False
                mock_handler._get_session.return_value = MagicMock()
                mock_handler._get_session.return_value.state.message_id = 100
                mock_handler.resume_game = AsyncMock(return_value=200)
                mock_get_handler.return_value = mock_handler

                with patch("src.handlers.commands._ensure_game_active") as mock_ensure:
                    mock_ensure.return_value = (True, None)

                    with patch("src.handlers.commands.settings") as mock_settings:
                        mock_settings.allowed_chat_ids = []

                        await reboot_command(mock_ctx)

                        # Should stop existing controller
                        mock_mgr.remove_controller.assert_called_once_with(123456)
                        # Should ensure game active with auto_load=False
                        mock_ensure.assert_called_once_with(123456, auto_load=False)
                        # Should resume game with new message
                        mock_handler.resume_game.assert_called_once_with(123456, mock_adapter)
                        # Should send success message
                        mock_adapter.send_text.assert_called()
                        call_text = mock_adapter.send_text.call_args[0][1]
                        assert "reboot" in call_text.lower() or "success" in call_text.lower()

    @pytest.mark.asyncio
    async def test_reboot_input_in_progress(self, mock_adapter, mock_ctx):
        """Test reboot while input processing."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = mock_controller

            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.is_input_in_progress.return_value = True
                mock_get_handler.return_value = mock_handler

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []

                    await reboot_command(mock_ctx)

                    mock_adapter.send_text.assert_called_once()
                    call_text = mock_adapter.send_text.call_args[0][1]
                    assert "wait" in call_text.lower() or "button" in call_text.lower() or "processing" in call_text.lower()

    @pytest.mark.asyncio
    async def test_reboot_non_admin_blocked(self, mock_adapter):
        """Test that /reboot is blocked for non-admins in groups."""
        ctx = make_ctx(mock_adapter, user_id=999)

        with patch("src.handlers.commands.check_admin_permission") as mock_check:
            mock_check.return_value = (
                False,
                "🔒 Only group administrators can use this command.",
            )

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await reboot_command(ctx)

                mock_adapter.send_text.assert_called_with(
                    123456,
                    "🔒 Only group administrators can use this command.",
                )

    @pytest.mark.asyncio
    async def test_reboot_in_command_handlers(self):
        """Test that 'reboot' is registered in COMMAND_HANDLERS."""
        assert "reboot" in COMMAND_HANDLERS
        assert COMMAND_HANDLERS["reboot"] == reboot_command


class TestEnsureGameActiveWithAutoLoad:
    """Test _ensure_game_active with auto_load parameter."""

    @pytest.mark.asyncio
    async def test_ensure_game_active_with_auto_load_true(self):
        """Test _ensure_game_active passes auto_load=True by default."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = None
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            success, error = await _ensure_game_active(123456)

            assert success is True
            mock_mgr.get_or_create_controller.assert_called_once_with(
                123456, auto_load=True
            )

    @pytest.mark.asyncio
    async def test_ensure_game_active_with_auto_load_false(self):
        """Test _ensure_game_active passes auto_load=False when specified."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_mgr.get_controller.return_value = None
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            success, error = await _ensure_game_active(123456, auto_load=False)

            assert success is True
            mock_mgr.get_or_create_controller.assert_called_once_with(
                123456, auto_load=False
            )


class TestLanguageCommand:
    """Test /language command."""

    @pytest.mark.asyncio
    async def test_language_show_current_no_args(self, mock_adapter, mock_ctx):
        """Test /language without args shows current language and options."""
        with patch("src.handlers.commands.state_manager") as mock_sm:
            from src.models.game_state import ChatConfig
            mock_config = ChatConfig(chat_id=123456, language="pt-BR")
            mock_sm.get_or_create_chat_config.return_value = mock_config

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []
                mock_settings.default_language = "pt-BR"

                with patch("src.handlers.commands.translation_manager") as mock_tm:
                    mock_tm.get.side_effect = lambda key, chat_id, **kwargs: f"translated_{key}"

                    await language_command(mock_ctx)

                    # Should call translation_manager.get for messages
                    assert mock_tm.get.call_count >= 3
                    # Should reply with status message
                    mock_adapter.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_language_change_success_admin(self, mock_adapter):
        """Test /language en-US successfully changes language for admin."""
        ctx = make_ctx(mock_adapter, args=["en-US"], user_id=999)

        with patch("src.handlers.commands.check_admin_permission") as mock_check:
            mock_check.return_value = (True, None)

            with patch("src.handlers.commands.state_manager") as mock_sm:
                from src.models.game_state import ChatConfig
                mock_config = ChatConfig(chat_id=123456, language="pt-BR")
                mock_sm.get_or_create_chat_config.return_value = mock_config

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []

                    with patch("src.handlers.commands.translation_manager") as mock_tm:
                        mock_tm.get.return_value = "Language changed!"

                        await language_command(ctx)

                        # Should update config language
                        assert mock_config.language == "en-US"
                        # Should save config
                        mock_sm.save_chat_config.assert_called_once_with(mock_config)
                        # Should invalidate cache
                        mock_tm.invalidate_cache.assert_called_once_with(123456)
                        # Should reply
                        mock_adapter.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_language_invalid_code(self, mock_adapter):
        """Test /language with invalid language code."""
        ctx = make_ctx(mock_adapter, args=["fr-FR"])  # Not supported

        with patch("src.handlers.commands.state_manager") as mock_sm:
            from src.models.game_state import ChatConfig
            mock_config = ChatConfig(chat_id=123456)
            mock_sm.get_or_create_chat_config.return_value = mock_config

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                with patch("src.handlers.commands.translation_manager") as mock_tm:
                    mock_tm.get.return_value = "Invalid language"

                    await language_command(ctx)

                    # Should not save config
                    mock_sm.save_chat_config.assert_not_called()
                    # Should reply with error
                    mock_adapter.send_text.assert_called_once()
                    call_text = mock_adapter.send_text.call_args[0][1]
                    assert "Invalid language" in call_text

    @pytest.mark.asyncio
    async def test_language_non_admin_blocked(self, mock_adapter):
        """Test /language blocked for non-admins in groups."""
        ctx = make_ctx(mock_adapter, args=["en-US"], user_id=999)

        with patch("src.handlers.commands.check_admin_permission") as mock_check:
            mock_check.return_value = (False, "🔒 Only group administrators can use this command.")

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await language_command(ctx)

                # Should reply with error
                mock_adapter.send_text.assert_called_once_with(
                    123456,
                    "🔒 Only group administrators can use this command.",
                )

    @pytest.mark.asyncio
    async def test_language_in_command_handlers(self):
        """Test that 'language' is registered in COMMAND_HANDLERS."""
        assert "language" in COMMAND_HANDLERS
        assert COMMAND_HANDLERS["language"] == language_command


@pytest.mark.asyncio
async def test_resume_command_noop_for_media_only_mirror(mock_adapter):
    """resume_command does nothing (no message) when called from a media-only mirror."""
    from src.handlers.commands import resume_command
    from src.adapters.base import CommandContext

    ctx = CommandContext(
        chat_id=20,
        user_id=1,
        user_name="User",
        args=[],
        adapter=mock_adapter,
        raw=None,
    )

    with patch("src.handlers.commands.is_media_only_mirror", return_value=True):
        await resume_command(ctx)

    mock_adapter.send_text.assert_not_called()
