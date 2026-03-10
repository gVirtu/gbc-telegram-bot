"""Tests for allowed_chat_ids enforcement in the Discord handler."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_slash_interaction(channel_id: int) -> MagicMock:
    """Build a minimal discord.Interaction mock for slash commands."""
    interaction = MagicMock()
    interaction.channel_id = channel_id
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.delete_original_response = AsyncMock()
    user = MagicMock()
    user.id = 999
    user.display_name = "TestUser"
    interaction.user = user
    return interaction


def _make_button_interaction(channel_id: int, custom_id: str = "a") -> MagicMock:
    """Build a minimal discord.Interaction mock for component (button) interactions."""
    import discord

    interaction = MagicMock()
    interaction.channel_id = channel_id
    interaction.type = discord.InteractionType.component
    interaction.data = {"custom_id": custom_id}
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    user = MagicMock()
    user.id = 999
    user.display_name = "TestUser"
    interaction.user = user
    message = MagicMock()
    message.id = 42
    interaction.message = message
    return interaction


class TestIsChatAllowed:
    """Unit tests for the module-level _is_chat_allowed helper."""

    def test_empty_allowlist_allows_all(self):
        from src.handlers.discord_handler import _is_chat_allowed

        with patch("src.handlers.discord_handler.settings") as mock:
            mock.allowed_chat_ids = []
            assert _is_chat_allowed(12345) is True

    def test_channel_in_allowlist(self):
        from src.handlers.discord_handler import _is_chat_allowed

        with patch("src.handlers.discord_handler.settings") as mock:
            mock.allowed_chat_ids = [100, 200]
            assert _is_chat_allowed(100) is True

    def test_channel_not_in_allowlist(self):
        from src.handlers.discord_handler import _is_chat_allowed

        with patch("src.handlers.discord_handler.settings") as mock:
            mock.allowed_chat_ids = [100, 200]
            assert _is_chat_allowed(999) is False


class TestSlashCommandAllowedChatIds:
    """Test _run_command blocks/allows based on allowed_chat_ids.

    Slash command callbacks are accessed via bot.tree.get_command(name).callback.
    The DiscordAdapter constructor is patched so _get_discord_adapter() fallback
    (which calls DiscordAdapter(bot)) returns a MagicMock without needing a real bot token.
    """

    @pytest.mark.asyncio
    async def test_allowed_channel_runs_handler(self):
        """Slash command from an allowed channel: handler is called."""
        from src.handlers.discord_handler import create_discord_bot

        handler_fn = AsyncMock()
        with patch("src.handlers.discord_handler.settings") as mock_settings, \
             patch("src.handlers.discord_handler.COMMAND_HANDLERS", {"status": handler_fn}), \
             patch("src.handlers.discord_handler.DiscordAdapter"):
            mock_settings.allowed_chat_ids = [100]

            bot = create_discord_bot()
            interaction = _make_slash_interaction(channel_id=100)

            cmd = bot.tree.get_command("status")
            await cmd.callback(interaction)

        interaction.response.defer.assert_awaited_once()
        handler_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disallowed_channel_sends_unauthorized(self):
        """Slash command from a disallowed channel: ephemeral Unauthorized, handler not called."""
        from src.handlers.discord_handler import create_discord_bot

        handler_fn = AsyncMock()
        with patch("src.handlers.discord_handler.settings") as mock_settings, \
             patch("src.handlers.discord_handler.COMMAND_HANDLERS", {"status": handler_fn}), \
             patch("src.handlers.discord_handler.DiscordAdapter"):
            mock_settings.allowed_chat_ids = [100]

            bot = create_discord_bot()
            interaction = _make_slash_interaction(channel_id=999)

            cmd = bot.tree.get_command("status")
            await cmd.callback(interaction)

        interaction.response.send_message.assert_awaited_once_with(
            "Unauthorized.", ephemeral=True
        )
        interaction.response.defer.assert_not_awaited()
        handler_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_allowlist_allows_all_slash(self):
        """Empty allowed_chat_ids: any channel's slash commands are allowed."""
        from src.handlers.discord_handler import create_discord_bot

        handler_fn = AsyncMock()
        with patch("src.handlers.discord_handler.settings") as mock_settings, \
             patch("src.handlers.discord_handler.COMMAND_HANDLERS", {"status": handler_fn}), \
             patch("src.handlers.discord_handler.DiscordAdapter"):
            mock_settings.allowed_chat_ids = []

            bot = create_discord_bot()
            interaction = _make_slash_interaction(channel_id=99999)

            cmd = bot.tree.get_command("status")
            await cmd.callback(interaction)

        interaction.response.defer.assert_awaited_once()
        handler_fn.assert_awaited_once()


class TestButtonInteractionAllowedChatIds:
    """Test on_interaction blocks/allows button presses based on allowed_chat_ids.

    The on_interaction listener is registered via @bot.listen("on_interaction").
    In discord.py 2.x, Bot.listen stores listeners in bot.extra_events[event_name].
    We retrieve it via bot.extra_events["on_interaction"][0].
    """

    def _get_on_interaction(self, bot):
        """Extract the on_interaction listener registered via @bot.listen."""
        listeners = bot.extra_events.get("on_interaction", [])
        assert listeners, "on_interaction listener not found in bot.extra_events"
        return listeners[0]

    @pytest.mark.asyncio
    async def test_allowed_channel_button_handled(self):
        """Button press from an allowed channel: routed to input handler."""
        from src.handlers.discord_handler import create_discord_bot

        input_handler = MagicMock()
        input_handler.handle_button_press = AsyncMock()
        config = MagicMock()
        config.platform = "discord"
        config.maintenance_mode = False

        with patch("src.handlers.discord_handler.settings") as mock_settings, \
             patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler", return_value=input_handler), \
             patch("src.handlers.discord_handler.is_valid_button_callback", return_value=True), \
             patch("src.handlers.discord_handler.DiscordAdapter"):
            mock_settings.allowed_chat_ids = [100]
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.save_chat_config = MagicMock()

            bot = create_discord_bot()
            on_interaction = self._get_on_interaction(bot)
            interaction = _make_button_interaction(channel_id=100, custom_id="a")

            await on_interaction(interaction)

        input_handler.handle_button_press.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disallowed_channel_button_ignored(self):
        """Button press from a disallowed channel: silently ignored, handler not called."""
        from src.handlers.discord_handler import create_discord_bot

        input_handler = MagicMock()
        input_handler.handle_button_press = AsyncMock()

        with patch("src.handlers.discord_handler.settings") as mock_settings, \
             patch("src.handlers.discord_handler.state_manager"), \
             patch("src.handlers.discord_handler.get_input_handler", return_value=input_handler), \
             patch("src.handlers.discord_handler.DiscordAdapter"):
            mock_settings.allowed_chat_ids = [100]

            bot = create_discord_bot()
            on_interaction = self._get_on_interaction(bot)
            interaction = _make_button_interaction(channel_id=999, custom_id="a")

            await on_interaction(interaction)

        input_handler.handle_button_press.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_allowlist_allows_all_buttons(self):
        """Empty allowed_chat_ids: button presses from any channel are allowed."""
        from src.handlers.discord_handler import create_discord_bot

        input_handler = MagicMock()
        input_handler.handle_button_press = AsyncMock()
        config = MagicMock()
        config.platform = "discord"
        config.maintenance_mode = False

        with patch("src.handlers.discord_handler.settings") as mock_settings, \
             patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.get_input_handler", return_value=input_handler), \
             patch("src.handlers.discord_handler.is_valid_button_callback", return_value=True), \
             patch("src.handlers.discord_handler.DiscordAdapter"):
            mock_settings.allowed_chat_ids = []
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.save_chat_config = MagicMock()

            bot = create_discord_bot()
            on_interaction = self._get_on_interaction(bot)
            interaction = _make_button_interaction(channel_id=99999, custom_id="a")

            await on_interaction(interaction)

        input_handler.handle_button_press.assert_awaited_once()
