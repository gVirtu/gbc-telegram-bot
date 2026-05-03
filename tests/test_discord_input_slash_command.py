"""Tests for the Discord /i (input sequence) slash command."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from src.models.game_state import GameButton, GameSession, ChatGameState


def _make_interaction(channel_id: int = 100, user_id: int = 999, user_name: str = "Alice"):
    interaction = MagicMock()
    interaction.channel_id = channel_id
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.user.display_name = user_name
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _make_handler_with_session(chat_id: int = 100, message_id: int = 42):
    from src.handlers.input_handler import InputHandler
    handler = InputHandler()
    session_state = ChatGameState(chat_id=chat_id, message_id=message_id)
    handler._sessions[chat_id] = GameSession(chat_id=chat_id, state=session_state)
    return handler


def _get_slash_i(bot):
    """Extract the /i command callback from the bot's command tree."""
    for cmd in bot.tree.get_commands():
        if cmd.name == "i":
            return cmd.callback
    raise AssertionError("/i command not found in bot tree")


def _make_bot():
    from src.handlers.discord_handler import create_discord_bot
    return create_discord_bot()


class TestInputSlashCommandRegistered:

    def test_slash_i_is_registered(self):
        """/i must appear in the bot's slash command tree."""
        bot = _make_bot()
        names = [cmd.name for cmd in bot.tree.get_commands()]
        assert "i" in names, f"/i not found in commands: {names}"


class TestInputSlashCommandNoSequence:

    @pytest.mark.asyncio
    async def test_no_sequence_sends_help_ephemeral(self):
        """/i with no argument sends an ephemeral help message."""
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler") as mock_get_handler:
            mock_sm.get_user_preference.return_value = "ULDR AB ST"
            mock_config = MagicMock(maintenance_mode=False)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            await slash_i(interaction, sequence=None)

        interaction.response.send_message.assert_awaited_once()
        msg = interaction.response.send_message.call_args.args[0] if interaction.response.send_message.call_args.args \
              else interaction.response.send_message.call_args.kwargs.get("content", "")
        assert "ULDR AB ST" in msg

    @pytest.mark.asyncio
    async def test_empty_string_sends_help_ephemeral(self):
        """/i with empty string is treated same as no argument."""
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler"):
            mock_sm.get_user_preference.return_value = None  # falls back to default
            mock_config = MagicMock(maintenance_mode=False)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            await slash_i(interaction, sequence="")

        interaction.response.send_message.assert_awaited_once()


class TestInputSlashCommandValid:

    @pytest.mark.asyncio
    async def test_valid_sequence_queues_buttons(self):
        """/i aaaaa with WASD mapping queues 5 LEFT inputs."""
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()
        handler = _make_handler_with_session()

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler", return_value=handler), \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.state_manager") as mock_ih_sm, \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch.object(handler, "_is_processing", return_value=True):
            mock_sm.get_user_preference.return_value = "WASD ZX CV"
            mock_sm.load_game_state.return_value = ChatGameState(chat_id=100, message_id=42)
            mock_config = MagicMock(maintenance_mode=False)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_ih_sm.get_or_create_chat_config.return_value = MagicMock()
            await slash_i(interaction, sequence="aaaaa")

        interaction.response.send_message.assert_awaited_once()
        msg = interaction.response.send_message.call_args.args[0] if interaction.response.send_message.call_args.args \
              else interaction.response.send_message.call_args.kwargs.get("content", "")
        # 'a' in WASD = LEFT = ⬅️; 5 times
        assert "⬅️" in msg

    @pytest.mark.asyncio
    async def test_uses_saved_mapping_preference(self):
        """/i uses the user's saved mapping, not the default."""
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()
        handler = _make_handler_with_session()

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler", return_value=handler), \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.state_manager") as mock_ih_sm, \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch.object(handler, "_is_processing", return_value=True):
            mock_sm.get_user_preference.return_value = "WASD ZX CV"
            mock_sm.load_game_state.return_value = ChatGameState(chat_id=100, message_id=42)
            mock_config = MagicMock(maintenance_mode=False)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_ih_sm.get_or_create_chat_config.return_value = MagicMock()
            await slash_i(interaction, sequence="w")  # 'w' = UP in WASD

        msg = interaction.response.send_message.call_args.args[0] if interaction.response.send_message.call_args.args \
              else interaction.response.send_message.call_args.kwargs.get("content", "")
        assert "⬆️" in msg  # UP emoji

    @pytest.mark.asyncio
    async def test_no_saved_preference_falls_back_to_wasd(self):
        """/i falls back to WASD ZX CV when no preference is saved."""
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()
        handler = _make_handler_with_session()

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler", return_value=handler), \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.state_manager") as mock_ih_sm, \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch.object(handler, "_is_processing", return_value=True):
            mock_sm.get_user_preference.return_value = None  # no preference
            mock_sm.load_game_state.return_value = ChatGameState(chat_id=100, message_id=42)
            mock_config = MagicMock(maintenance_mode=False)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_ih_sm.get_or_create_chat_config.return_value = MagicMock()
            await slash_i(interaction, sequence="w")  # 'w' = UP in WASD

        msg = interaction.response.send_message.call_args.args[0] if interaction.response.send_message.call_args.args \
              else interaction.response.send_message.call_args.kwargs.get("content", "")
        assert "⬆️" in msg


class TestInputSlashCommandTrimming:

    @pytest.mark.asyncio
    async def test_sequence_trimmed_to_max_length(self):
        """/i trims sequences longer than max_sequence_length."""
        from src.config import settings
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()
        handler = _make_handler_with_session()

        long_seq = "u" * (settings.max_sequence_length + 5)

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler", return_value=handler), \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.state_manager") as mock_ih_sm, \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch.object(handler, "_is_processing", return_value=True):
            mock_sm.get_user_preference.return_value = "ULDR AB ST"
            mock_sm.load_game_state.return_value = ChatGameState(chat_id=100, message_id=42)
            mock_config = MagicMock(maintenance_mode=False)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_ih_sm.get_or_create_chat_config.return_value = MagicMock()
            await slash_i(interaction, sequence=long_seq)

        # Must succeed (not error) and queue exactly max_sequence_length buttons
        interaction.response.send_message.assert_awaited_once()
        msg = interaction.response.send_message.call_args.args[0] if interaction.response.send_message.call_args.args \
              else interaction.response.send_message.call_args.kwargs.get("content", "")
        assert "⬆️" in msg  # UP queued
        # Trim warning must appear
        assert str(settings.max_sequence_length) in msg

    @pytest.mark.asyncio
    async def test_exact_max_length_not_trimmed(self):
        """/i does NOT trim when sequence length equals max_sequence_length."""
        from src.config import settings
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()
        handler = _make_handler_with_session()

        exact_seq = "u" * settings.max_sequence_length

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler", return_value=handler), \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.state_manager") as mock_ih_sm, \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch.object(handler, "_is_processing", return_value=True):
            mock_sm.get_user_preference.return_value = "ULDR AB ST"
            mock_sm.load_game_state.return_value = ChatGameState(chat_id=100, message_id=42)
            mock_config = MagicMock(maintenance_mode=False)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_ih_sm.get_or_create_chat_config.return_value = MagicMock()
            await slash_i(interaction, sequence=exact_seq)

        msg = interaction.response.send_message.call_args.args[0] if interaction.response.send_message.call_args.args \
              else interaction.response.send_message.call_args.kwargs.get("content", "")
        # No trim warning in the message
        assert "Trimmed" not in msg and "Limitado" not in msg


class TestInputSlashCommandInvalidChars:

    @pytest.mark.asyncio
    async def test_invalid_chars_sends_error(self):
        """/i reports invalid characters and does not queue anything."""
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler") as mock_get_handler:
            mock_sm.get_user_preference.return_value = "ULDR AB ST"
            mock_sm.load_game_state.return_value = ChatGameState(chat_id=100, message_id=42)
            mock_config = MagicMock(maintenance_mode=False)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            await slash_i(interaction, sequence="UXY")  # X and Y invalid for ULDR

        interaction.response.send_message.assert_awaited_once()
        msg = interaction.response.send_message.call_args.args[0] if interaction.response.send_message.call_args.args \
              else interaction.response.send_message.call_args.kwargs.get("content", "")
        assert "X" in msg or "Y" in msg
        # handle_sequence_input was never called
        mock_get_handler.return_value.handle_sequence_input.assert_not_called()


class TestInputSlashCommandHandlerFailure:

    @pytest.mark.asyncio
    async def test_handler_error_sends_error_message(self):
        """/i sends the error text when handle_sequence_input returns False."""
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()
        handler = MagicMock()
        handler.handle_sequence_input = AsyncMock(return_value=(False, "Queue is full"))

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler", return_value=handler):
            mock_sm.get_user_preference.return_value = "ULDR AB ST"
            mock_sm.load_game_state.return_value = ChatGameState(chat_id=100, message_id=42)
            mock_config = MagicMock(maintenance_mode=False)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            await slash_i(interaction, sequence="UU")

        interaction.response.send_message.assert_awaited_once()
        msg = interaction.response.send_message.call_args.args[0] if interaction.response.send_message.call_args.args \
              else interaction.response.send_message.call_args.kwargs.get("content", "")
        assert "Queue is full" in msg


class TestInputSlashCommandMaintenanceMode:

    @pytest.mark.asyncio
    async def test_maintenance_mode_blocks_non_admin(self):
        """Non-admin users cannot use /i during maintenance mode."""
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.adapters.base.get_adapter") as mock_get_adapter:
            mock_config = MagicMock()
            mock_config.maintenance_mode = True
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_adapter = MagicMock()
            mock_adapter.is_admin = AsyncMock(return_value=False)
            mock_get_adapter.return_value = mock_adapter
            await slash_i(interaction, sequence="UU")

        interaction.response.send_message.assert_awaited_once()
        # handle_sequence_input was never reached
        mock_sm.get_user_preference.assert_not_called()

    @pytest.mark.asyncio
    async def test_maintenance_mode_allows_admin(self):
        """Admin users can use /i during maintenance mode."""
        bot = _make_bot()
        slash_i = _get_slash_i(bot)
        interaction = _make_interaction()
        handler = MagicMock()
        handler.handle_sequence_input = AsyncMock(return_value=(False, "no session"))

        with patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.adapters.base.get_adapter") as mock_get_adapter, \
             patch("src.handlers.discord_handler.get_input_handler", return_value=handler):
            mock_config = MagicMock()
            mock_config.maintenance_mode = True
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_sm.get_user_preference.return_value = "ULDR AB ST"
            mock_sm.load_game_state.return_value = None
            mock_adapter = MagicMock()
            mock_adapter.is_admin = AsyncMock(return_value=True)
            mock_get_adapter.return_value = mock_adapter
            await slash_i(interaction, sequence="UU")

        # Admin proceeds: get_user_preference was called (not blocked early)
        mock_sm.get_user_preference.assert_called_once()
