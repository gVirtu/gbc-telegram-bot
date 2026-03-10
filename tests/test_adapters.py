"""Tests for BotAdapter implementations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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


class TestTelegramAdapterCleanupAfterAvatarUpdate:
    """Test TelegramAdapter.cleanup_after_avatar_update."""

    def _make_adapter(self, mock_bot):
        from src.adapters.telegram import TelegramAdapter
        return TelegramAdapter(bot=mock_bot)

    @pytest.mark.asyncio
    async def test_no_op_when_latest_message_id_is_none(self):
        """cleanup_after_avatar_update does nothing when latest_message_id is None."""
        mock_bot = MagicMock()
        mock_bot.delete_message = AsyncMock()
        adapter = self._make_adapter(mock_bot)
        await adapter.cleanup_after_avatar_update(chat_id=1, latest_message_id=None)
        mock_bot.delete_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_deletes_subsequent_messages_until_exception(self):
        """cleanup_after_avatar_update deletes IDs latest+1, latest+2, ... stopping at first exception."""
        mock_bot = MagicMock()
        # Succeed on +1 and +2, fail on +3
        mock_bot.delete_message = AsyncMock(side_effect=[None, None, Exception("not found")])
        adapter = self._make_adapter(mock_bot)
        await adapter.cleanup_after_avatar_update(chat_id=1, latest_message_id=100)
        assert mock_bot.delete_message.call_count == 3
        calls = [c.args for c in mock_bot.delete_message.call_args_list]
        assert calls[0] == (1, 101)
        assert calls[1] == (1, 102)
        assert calls[2] == (1, 103)

    @pytest.mark.asyncio
    async def test_stops_at_max_probes_even_with_no_exception(self):
        """cleanup_after_avatar_update stops after MAX_PROBES=5 even if all succeed."""
        mock_bot = MagicMock()
        mock_bot.delete_message = AsyncMock(return_value=None)
        adapter = self._make_adapter(mock_bot)
        await adapter.cleanup_after_avatar_update(chat_id=1, latest_message_id=50)
        assert mock_bot.delete_message.call_count == 5


class TestTelegramAdapterSendMethodsTrackMessageId:
    """Test that send methods call update_latest_telegram_message_id."""

    def _make_adapter(self, mock_bot):
        from src.adapters.telegram import TelegramAdapter
        return TelegramAdapter(bot=mock_bot)

    @pytest.mark.asyncio
    async def test_send_game_message_tracks_id(self):
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        mock_bot.send_photo = AsyncMock(return_value=mock_msg)
        adapter = self._make_adapter(mock_bot)
        with patch("src.adapters.telegram.state_manager") as mock_sm:
            result = await adapter.send_game_message(
                chat_id=1, text="t", keyboard=None, image_bytes=b""
            )
        assert result == 42
        mock_sm.update_latest_telegram_message_id.assert_called_once_with(1, 42)

    @pytest.mark.asyncio
    async def test_send_text_tracks_id(self):
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 55
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        adapter = self._make_adapter(mock_bot)
        with patch("src.adapters.telegram.state_manager") as mock_sm:
            await adapter.send_text(chat_id=1, text="hello")
        mock_sm.update_latest_telegram_message_id.assert_called_once_with(1, 55)

    @pytest.mark.asyncio
    async def test_send_screenshot_tracks_id(self):
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 66
        mock_bot.send_photo = AsyncMock(return_value=mock_msg)
        adapter = self._make_adapter(mock_bot)
        with patch("src.adapters.telegram.state_manager") as mock_sm:
            await adapter.send_screenshot(chat_id=1, image_bytes=b"")
        mock_sm.update_latest_telegram_message_id.assert_called_once_with(1, 66)

    @pytest.mark.asyncio
    async def test_send_video_tracks_id(self):
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 77
        mock_msg.video = None
        mock_bot.send_video = AsyncMock(return_value=mock_msg)
        adapter = self._make_adapter(mock_bot)
        with patch("src.adapters.telegram.state_manager") as mock_sm:
            await adapter.send_video(chat_id=1, video=b"")
        mock_sm.update_latest_telegram_message_id.assert_called_once_with(1, 77)

    @pytest.mark.asyncio
    async def test_send_animation_tracks_id(self):
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 88
        mock_bot.send_animation = AsyncMock(return_value=mock_msg)
        adapter = self._make_adapter(mock_bot)
        with patch("src.adapters.telegram.state_manager") as mock_sm:
            await adapter.send_animation(chat_id=1, animation=b"")
        mock_sm.update_latest_telegram_message_id.assert_called_once_with(1, 88)
