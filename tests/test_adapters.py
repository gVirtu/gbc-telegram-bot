"""Tests for BotAdapter implementations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from telegram.error import TelegramError


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


@pytest.mark.asyncio
class TestTelegramAdapterUpdateChatPhoto:
    """Tests for TelegramAdapter.update_chat_photo() sentinel + delete flow."""

    def _make_adapter(self):
        from src.adapters.telegram import TelegramAdapter

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        mock_bot.set_chat_photo = AsyncMock()
        mock_bot.delete_message = AsyncMock()
        adapter = TelegramAdapter(bot=mock_bot)
        return adapter, mock_bot

    async def test_sends_silent_sentinel_message(self):
        adapter, mock_bot = self._make_adapter()
        sentinel_msg = MagicMock()
        sentinel_msg.message_id = 42
        mock_bot.send_message.return_value = sentinel_msg

        with patch("src.adapters.telegram.translation_manager") as mock_tm:
            mock_tm.get.return_value = "Updating group photo..."
            await adapter.update_chat_photo(chat_id=100, image_bytes=b"img")

        mock_bot.send_message.assert_called_once()
        _, kwargs = mock_bot.send_message.call_args
        assert kwargs.get("disable_notification") is True

    async def test_calls_set_chat_photo_after_sentinel(self):
        adapter, mock_bot = self._make_adapter()
        sentinel_msg = MagicMock()
        sentinel_msg.message_id = 42
        mock_bot.send_message.return_value = sentinel_msg

        with patch("src.adapters.telegram.translation_manager") as mock_tm:
            mock_tm.get.return_value = "Updating group photo..."
            await adapter.update_chat_photo(chat_id=100, image_bytes=b"img")

        mock_bot.set_chat_photo.assert_called_once()

    async def test_deletes_sentinel_and_system_message(self):
        adapter, mock_bot = self._make_adapter()
        sentinel_msg = MagicMock()
        sentinel_msg.message_id = 42
        mock_bot.send_message.return_value = sentinel_msg

        with patch("src.adapters.telegram.translation_manager") as mock_tm:
            mock_tm.get.return_value = "Updating group photo..."
            await adapter.update_chat_photo(chat_id=100, image_bytes=b"img")

        assert mock_bot.delete_message.call_count == 2
        mock_bot.delete_message.assert_any_call(chat_id=100, message_id=42)
        mock_bot.delete_message.assert_any_call(chat_id=100, message_id=43)

    async def test_delete_failure_does_not_raise(self):
        adapter, mock_bot = self._make_adapter()
        sentinel_msg = MagicMock()
        sentinel_msg.message_id = 42
        mock_bot.send_message.return_value = sentinel_msg
        mock_bot.delete_message.side_effect = TelegramError("Not found")

        with patch("src.adapters.telegram.translation_manager") as mock_tm:
            mock_tm.get.return_value = "Updating group photo..."
            # Should not raise
            await adapter.update_chat_photo(chat_id=100, image_bytes=b"img")

    async def test_sentinel_delete_failure_still_attempts_system_message_delete(self):
        adapter, mock_bot = self._make_adapter()
        sentinel_msg = MagicMock()
        sentinel_msg.message_id = 42
        mock_bot.send_message.return_value = sentinel_msg

        call_count = 0

        async def delete_side_effect(chat_id, message_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TelegramError("First delete failed")

        mock_bot.delete_message.side_effect = delete_side_effect

        with patch("src.adapters.telegram.translation_manager") as mock_tm:
            mock_tm.get.return_value = "Updating group photo..."
            await adapter.update_chat_photo(chat_id=100, image_bytes=b"img")

        assert mock_bot.delete_message.call_count == 2

    async def test_uses_translation_manager_for_sentinel_text(self):
        adapter, mock_bot = self._make_adapter()
        sentinel_msg = MagicMock()
        sentinel_msg.message_id = 42
        mock_bot.send_message.return_value = sentinel_msg

        with patch("src.adapters.telegram.translation_manager") as mock_tm:
            mock_tm.get.return_value = "Updating group photo..."
            await adapter.update_chat_photo(chat_id=100, image_bytes=b"img")

        mock_tm.get.assert_called_once_with("game.avatar_updating", 100)
