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

from telegram import Update

from src.handlers.commands import (
    start_game_command,
    resume_command,
    print_command,
    save_command,
    load_command,
    status_command,
    help_command,
    unknown_command,
    message_command,
    _ensure_game_active,
    COMMAND_HANDLERS,
)
from src.models.game_state import GameButton


class MockUpdate:
    """Mock Telegram Update object."""

    def __init__(self, chat_id=123456, text="", args=None):
        self.effective_chat = MagicMock()
        self.effective_chat.id = chat_id
        self.effective_chat.type = "private"  # Default to private chat for backward compatibility
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

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

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

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await start_game_command(update, context)

                # Should send error message
                update.message.reply_text.assert_called_with(
                    "❌ Não consegui iniciar o jogo. Por favor, tente novamente ou entre em contato com o administrador do bot."
                )


class TestResumeCommand:
    """Test /resume command."""

    @pytest.fixture
    def update(self):
        return MockUpdate()

    @pytest.fixture
    def context(self):
        return MockContext()

    @pytest.mark.asyncio
    async def test_resume_with_active_game(self, update, context):
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

                    await resume_command(update, context)

                    mock_handler.resume_game.assert_called_once_with(123456)

    @pytest.mark.asyncio
    async def test_resume_auto_starts_game(self, update, context):
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

                        await resume_command(update, context)

                        # Should auto-start the game
                        mock_mgr.get_or_create_controller.assert_called_once_with(123456)
                        mock_handler.resume_game.assert_called_once_with(123456)

    @pytest.mark.asyncio
    async def test_input_in_progress(self, update, context):
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

                    await resume_command(update, context)

                    update.message.reply_text.assert_called_with(
                        "⏳ Um botão foi pressionado recentemente. Por favor aguarde..."
                    )


class TestSaveCommand:
    """Test /save command."""

    @pytest.fixture
    def update(self):
        return MockUpdate()

    @pytest.fixture
    def context(self):
        return MockContext()

    @pytest.mark.asyncio
    async def test_save_auto_starts_game(self, update, context):
        """Test save auto-starts game when not active."""
        context.args = ["2"]

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

                    await save_command(update, context)

                    # Should auto-start the game
                    mock_mgr.get_or_create_controller.assert_called_once_with(123456)
                    mock_state.save_to_slot.assert_called_once()
                    call_args = mock_state.save_to_slot.call_args
                    assert call_args[1]["slot_number"] == 2

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
                    "❌ Slot inválido. Use 0-4."
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
    async def test_load_auto_starts_game(self, update, context):
        """Test load auto-starts game when not active.

        Note: Save loading logic is now handled internally by get_or_create_controller.
        This test verifies the command properly triggers game initialization.
        """
        context.args = ["0"]

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

                    await load_command(update, context)

                    mock_mgr.get_or_create_controller.assert_called_once_with(123456)

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

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []

                    await load_command(update, context)

                    update.message.reply_text.assert_called_with(
                        "⏳ Um botão foi pressionado recentemente. Antes de carregar, por favor aguarde."
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

                    with patch("src.handlers.commands.settings") as mock_settings:
                        mock_settings.allowed_chat_ids = []

                        await load_command(update, context)

                        update.message.reply_text.assert_called_with(
                            "Nenhum slot de salvamento encontrado. Use /save [slot] para criar um."
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

                    with patch("src.handlers.commands.settings") as mock_settings:
                        mock_settings.allowed_chat_ids = []
                        mock_settings.save_slots = 5

                        await load_command(update, context)

                        mock_controller.load_state.assert_called_once_with(b"save_data")
                        update.message.reply_text.assert_called_with(
                            "📂 Carregado jogo do slot 0!"
                        )


class TestLoadBackupCommand:
    """Test /load backup YYYYMMDD subcommand."""

    @pytest.fixture
    def update(self):
        return MockUpdate()

    @pytest.fixture
    def context(self):
        return MockContext()

    def _active_game_patches(self, mock_mgr, mock_handler):
        """Set up mocks for an active, non-processing game."""
        mock_controller = MagicMock()
        mock_controller.is_initialized.return_value = True
        mock_mgr.get_controller.return_value = mock_controller
        mock_handler.is_input_in_progress.return_value = False
        return mock_controller

    @pytest.mark.asyncio
    async def test_load_backup_valid_date_admin(self, update, context):
        """Admin loading a valid backup date succeeds."""
        context.args = ["backup", "20260215"]

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

                        await load_command(update, context)

                        mock_backup_mgr.load_backup.assert_called_once_with(123456, "20260215")
                        mock_controller.load_state.assert_called_once_with(b"backup_bytes")
                        update.message.reply_text.assert_called_with(
                            "✅ Backup de 20260215 carregado com sucesso."
                        )

    @pytest.mark.asyncio
    async def test_load_backup_not_admin(self, update, context):
        """Non-admin in group chat gets permission error."""
        update.effective_chat.type = "supergroup"
        context.args = ["backup", "20260215"]

        with patch("src.handlers.commands._check_admin_permission", return_value=(False, "🔒 Apenas administradores do grupo podem usar este comando.")):
            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await load_command(update, context)

                update.message.reply_text.assert_called_with(
                    "🔒 Apenas administradores do grupo podem usar este comando."
                )

    @pytest.mark.asyncio
    async def test_load_backup_invalid_date(self, update, context):
        """Invalid date format returns a helpful error message."""
        context.args = ["backup", "not-a-date"]

        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                self._active_game_patches(mock_mgr, mock_handler)
                mock_get_handler.return_value = mock_handler

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []
                    mock_settings.save_slots = 5

                    await load_command(update, context)

                    update.message.reply_text.assert_called_with(
                        "Formato de data inválido. Use YYYYMMDD (ex: 20260215)"
                    )

    @pytest.mark.asyncio
    async def test_load_backup_not_found(self, update, context):
        """Missing backup lists available dates."""
        context.args = ["backup", "20260101"]

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

                        await load_command(update, context)

                        update.message.reply_text.assert_called_with(
                            "Backup 20260101 não encontrado. Disponíveis: 20260102, 20260103"
                        )

    @pytest.mark.asyncio
    async def test_load_backup_missing_date_arg(self, update, context):
        """'/load backup' without a date shows usage hint."""
        context.args = ["backup"]

        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            with patch("src.handlers.commands.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                self._active_game_patches(mock_mgr, mock_handler)
                mock_get_handler.return_value = mock_handler

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []
                    mock_settings.save_slots = 5

                    await load_command(update, context)

                    update.message.reply_text.assert_called_with("Uso: /load backup YYYYMMDD")


class TestStatusCommand:
    """Test /status command."""

    @pytest.fixture
    def update(self):
        return MockUpdate()

    @pytest.fixture
    def context(self):
        return MockContext()

    @pytest.mark.asyncio
    async def test_status_auto_starts_game(self, update, context):
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

                        await status_command(update, context)

                        # Should auto-start and show active status
                        mock_mgr.get_or_create_controller.assert_called_once_with(123456)
                        call_args = update.message.reply_text.call_args
                        assert "Jogo ativo" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_status_with_active_game(self, update, context):
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

                        await status_command(update, context)

                        call_args = update.message.reply_text.call_args
                        assert "Jogo ativo" in call_args[0][0]


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
            "❓ Comando desconhecido. Use /help para ver os comandos disponíveis."
        )


class TestCommandHandlersDict:
    """Test command handlers dictionary."""

    def test_all_commands_present(self):
        """Test all expected commands are in the dictionary."""
        expected_commands = [
            "start_game",
            "resume",
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
            mock_mgr.get_or_create_controller.assert_called_once_with(123456)

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
            mock_mgr.get_or_create_controller.assert_called_once_with(123456)

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
            assert "Não consegui iniciar o jogo" in error


class TestPrintCommand:
    """Test /print command."""

    @pytest.fixture
    def update(self):
        return MockUpdate()

    @pytest.fixture
    def context(self):
        return MockContext()

    @pytest.mark.asyncio
    async def test_print_auto_starts_game(self, update, context):
        """Test print auto-starts game when not active."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.get_frame_as_png.return_value = b"png_data"
            mock_mgr.get_controller.side_effect = [None, mock_controller]
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)

            with patch("src.handlers.commands.state_manager") as mock_state:
                mock_state.list_save_slots.return_value = []
                mock_state.load_from_slot.return_value = None  # No slot 1

                context.bot.send_photo = AsyncMock()

                with patch("src.handlers.commands.settings") as mock_settings:
                    mock_settings.allowed_chat_ids = []

                    await print_command(update, context)

                    # Should auto-start the game
                    mock_mgr.get_or_create_controller.assert_called_once_with(123456)
                    context.bot.send_photo.assert_called_once()

    @pytest.mark.asyncio
    async def test_print_with_active_game(self, update, context):
        """Test print when game is already active."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.get_frame_as_png.return_value = b"png_data"
            mock_mgr.get_controller.return_value = mock_controller

            context.bot.send_photo = AsyncMock()

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await print_command(update, context)

                context.bot.send_photo.assert_called_once()
                call_args = context.bot.send_photo.call_args
                assert call_args[1]["caption"] == ""

    @pytest.mark.asyncio
    async def test_print_error(self, update, context):
        """Test print with error."""
        with patch("src.handlers.commands.game_controller_manager") as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.get_frame_as_png.side_effect = Exception("Frame error")
            mock_mgr.get_controller.return_value = mock_controller

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await print_command(update, context)

                update.message.reply_text.assert_called_with(
                    "❌ Não consegui capturar a tela. Tente novamente."
                )


class TestAdminPermissions:
    """Test admin permission checking for restricted commands."""

    @pytest.mark.asyncio
    async def test_check_admin_permission_private_chat(self):
        """Test that private chats always allow commands."""
        mock_update = MockUpdate(chat_id=123456)
        mock_update.effective_chat.type = "private"
        mock_context = MagicMock()

        from src.handlers.commands import _check_admin_permission
        is_allowed, error_msg = await _check_admin_permission(mock_update, mock_context)

        assert is_allowed is True
        assert error_msg is None

    @pytest.mark.asyncio
    async def test_check_admin_permission_group_admin(self):
        """Test that group admins are allowed."""
        mock_update = MockUpdate(chat_id=123456)
        mock_update.effective_chat.type = "group"
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 789

        mock_context = MagicMock()
        mock_chat_member = MagicMock()
        mock_chat_member.status = "administrator"
        mock_context.bot.get_chat_member = AsyncMock(return_value=mock_chat_member)

        from src.handlers.commands import _check_admin_permission
        is_allowed, error_msg = await _check_admin_permission(mock_update, mock_context)

        assert is_allowed is True
        assert error_msg is None

    @pytest.mark.asyncio
    async def test_check_admin_permission_group_creator(self):
        """Test that group creators are allowed."""
        mock_update = MockUpdate(chat_id=123456)
        mock_update.effective_chat.type = "supergroup"
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 789

        mock_context = MagicMock()
        mock_chat_member = MagicMock()
        mock_chat_member.status = "creator"
        mock_context.bot.get_chat_member = AsyncMock(return_value=mock_chat_member)

        from src.handlers.commands import _check_admin_permission
        is_allowed, error_msg = await _check_admin_permission(mock_update, mock_context)

        assert is_allowed is True
        assert error_msg is None

    @pytest.mark.asyncio
    async def test_check_admin_permission_group_regular_member(self):
        """Test that regular group members are denied."""
        mock_update = MockUpdate(chat_id=123456)
        mock_update.effective_chat.type = "group"
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 999  # Different user ID to avoid cache collision

        mock_context = MagicMock()
        mock_chat_member = MagicMock()
        mock_chat_member.status = "member"
        mock_context.bot.get_chat_member = AsyncMock(return_value=mock_chat_member)

        from src.handlers.commands import _check_admin_permission, _admin_cache

        # Clear cache to avoid interference from other tests
        _admin_cache.clear()

        is_allowed, error_msg = await _check_admin_permission(mock_update, mock_context)

        assert is_allowed is False
        assert "administradores" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_admin_cache_functionality(self):
        """Test that admin status is cached."""
        mock_update = MockUpdate(chat_id=123456)
        mock_update.effective_chat.type = "group"
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 789

        mock_context = MagicMock()
        mock_chat_member = MagicMock()
        mock_chat_member.status = "administrator"
        mock_context.bot.get_chat_member = AsyncMock(return_value=mock_chat_member)

        from src.handlers.commands import _check_admin_permission, _admin_cache

        # Clear cache
        _admin_cache.clear()

        # First call - should hit API
        await _check_admin_permission(mock_update, mock_context)
        assert mock_context.bot.get_chat_member.call_count == 1

        # Second call - should use cache
        await _check_admin_permission(mock_update, mock_context)
        assert mock_context.bot.get_chat_member.call_count == 1  # Still 1, not 2

    @pytest.mark.asyncio
    async def test_start_game_blocked_for_non_admin(self):
        """Test that /start_game is blocked for non-admins in groups."""
        mock_update = MockUpdate(chat_id=123456)
        mock_update.effective_chat.type = "group"
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 888  # Different user ID

        mock_context = MagicMock()
        mock_chat_member = MagicMock()
        mock_chat_member.status = "member"
        mock_context.bot.get_chat_member = AsyncMock(return_value=mock_chat_member)

        from src.handlers.commands import _admin_cache
        _admin_cache.clear()

        with patch("src.handlers.commands.settings") as mock_settings:
            mock_settings.allowed_chat_ids = []

            await start_game_command(mock_update, mock_context)

            # Should send error message (only the permission denial, not the game start messages)
            # The last call should be the permission denial
            assert mock_update.message.reply_text.called
            last_call = mock_update.message.reply_text.call_args[0][0]
            assert "administradores" in last_call.lower()

    @pytest.mark.asyncio
    async def test_save_allowed_for_admin(self):
        """Test that /save works for admins in groups."""
        mock_update = MockUpdate(chat_id=123456)
        mock_update.effective_chat.type = "group"
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 789

        mock_context = MagicMock()
        mock_chat_member = MagicMock()
        mock_chat_member.status = "administrator"
        mock_context.bot.get_chat_member = AsyncMock(return_value=mock_chat_member)

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

                        await save_command(mock_update, mock_context)

                        # Should succeed (not blocked)
                        # Check that save was attempted
                        assert mock_controller.save_state.called

    @pytest.mark.asyncio
    async def test_load_allowed_in_private_chat(self):
        """Test that /load works in private chats without admin check."""
        mock_update = MockUpdate(chat_id=123456)
        mock_update.effective_chat.type = "private"

        mock_context = MagicMock()
        mock_context.args = ["1"]

        # Note: bot.get_chat_member should NOT be called for private chats
        mock_context.bot.get_chat_member = AsyncMock()

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

                            await load_command(mock_update, mock_context)

                            # Should NOT call get_chat_member (private chat bypass)
                            assert not mock_context.bot.get_chat_member.called


class TestMessageCommand:
    """Test /m command for custom message base text."""

    @pytest.fixture
    def update(self):
        return MockUpdate()

    @pytest.fixture
    def context(self):
        return MockContext()

    @pytest.mark.asyncio
    async def test_message_command_sets_custom_text(self, update, context):
        """Test setting custom message base text."""
        context.args = ["Vamos", "jogar!"]

        with patch("src.handlers.commands.state_manager") as mock_state:
            mock_config = MagicMock()
            mock_config.message_base_text = None
            mock_state.get_or_create_chat_config.return_value = mock_config
            mock_state.save_chat_config = MagicMock()

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await message_command(update, context)

                assert mock_config.message_base_text == "Vamos jogar!"
                mock_state.save_chat_config.assert_called_once_with(mock_config)
                update.message.reply_text.assert_called_with(
                    '✅ Mensagem definida: "Vamos jogar!"'
                )

    @pytest.mark.asyncio
    async def test_message_command_clears_text(self, update, context):
        """Test clearing custom message base text (no args)."""
        context.args = []

        with patch("src.handlers.commands.state_manager") as mock_state:
            mock_config = MagicMock()
            mock_config.message_base_text = "Custom text"
            mock_state.get_or_create_chat_config.return_value = mock_config
            mock_state.save_chat_config = MagicMock()

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await message_command(update, context)

                assert mock_config.message_base_text is None
                mock_state.save_chat_config.assert_called_once_with(mock_config)
                update.message.reply_text.assert_called_with(
                    '✅ Mensagem personalizada removida..'
                )

    @pytest.mark.asyncio
    async def test_message_command_text_too_long(self, update, context):
        """Test validation for text length limit."""
        context.args = ["x" * 241]  # 241 characters

        with patch("src.handlers.commands.state_manager") as mock_state:
            mock_config = MagicMock()
            mock_state.get_or_create_chat_config.return_value = mock_config

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await message_command(update, context)

                # Should not save, should show error
                mock_state.save_chat_config.assert_not_called()
                update.message.reply_text.assert_called_with(
                    "❌ Texto muito longo. Use no máximo 240 caracteres."
                )

    @pytest.mark.asyncio
    async def test_message_command_non_admin_blocked(self, update, context):
        """Test that /m is blocked for non-admins in groups."""
        update.effective_chat.type = "group"
        update.effective_user = MagicMock()
        update.effective_user.id = 999

        context.args = ["Hello"]

        with patch("src.handlers.commands._check_admin_permission") as mock_check:
            mock_check.return_value = (False, "🔒 Apenas administradores do grupo podem usar este comando.")

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []

                await message_command(update, context)

                update.message.reply_text.assert_called_with(
                    "🔒 Apenas administradores do grupo podem usar este comando."
                )

    @pytest.mark.asyncio
    async def test_message_command_in_command_handlers(self):
        """Test that 'm' is registered in COMMAND_HANDLERS."""
        assert "m" in COMMAND_HANDLERS
        assert COMMAND_HANDLERS["m"] == message_command
