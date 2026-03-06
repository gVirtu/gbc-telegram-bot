"""Tests for BotAdapter implementations."""

from unittest.mock import MagicMock


class TestPreferredAnimationFormat:
    """Test preferred_animation_format property on adapters."""

    def test_telegram_adapter_returns_mp4(self):
        from src.adapters.telegram import TelegramAdapter

        mock_bot = MagicMock()
        adapter = TelegramAdapter(bot=mock_bot)
        assert adapter.preferred_animation_format == "mp4"

    def test_discord_adapter_returns_gif(self):
        from src.adapters.discord import DiscordAdapter

        mock_bot = MagicMock()
        adapter = DiscordAdapter(bot=mock_bot)
        assert adapter.preferred_animation_format == "avif"
