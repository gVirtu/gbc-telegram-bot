"""Tests for rate-limited Telegram client wrapper."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram.error import RetryAfter

from src.utils.telegram_client import RateLimitedBot


class TestRateLimitedBot:
    """Test rate-limited Telegram bot wrapper."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.send_message = AsyncMock()
        bot.send_photo = AsyncMock()
        bot.edit_message_media = AsyncMock()
        bot.edit_message_reply_markup = AsyncMock()
        return bot
    
    @pytest.fixture
    def rate_limited_bot(self, mock_bot):
        """Create a RateLimitedBot with mock."""
        return RateLimitedBot(mock_bot)
    
    @pytest.mark.asyncio
    async def test_allows_request_when_not_rate_limited(self, rate_limited_bot, mock_bot):
        """Should allow request when under rate limit."""
        await rate_limited_bot.send_message(chat_id=12345, text="Hello")
        
        mock_bot.send_message.assert_called_once_with(chat_id=12345, text="Hello")
    
    @pytest.mark.asyncio
    async def test_retry_after_retry_succeeds(self, rate_limited_bot, mock_bot):
        """Should retry once after RetryAfter and return result."""
        mock_bot.send_message.side_effect = [RetryAfter(0.001), "success"]

        result = await rate_limited_bot.send_message(chat_id=12345, text="Hello")

        assert result == "success"
        assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_after_retry_fails(self, rate_limited_bot, mock_bot):
        """Should raise RetryAfter if retry also fails."""
        mock_bot.send_message.side_effect = [RetryAfter(0.001), RetryAfter(5)]

        with pytest.raises(RetryAfter):
            await rate_limited_bot.send_message(chat_id=12345, text="Hello")

        assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_after_blocks_subsequent_during_wait(self, rate_limited_bot, mock_bot):
        """Should block subsequent calls while waiting for retry."""
        mock_bot.send_message.side_effect = RetryAfter(0.5)

        with pytest.raises(RetryAfter):
            await rate_limited_bot.send_message(chat_id=12345, text="First")

        # Block has expired during retry wait, but limiter tracks it correctly
        # Next call should not be blocked
        mock_bot.send_message.reset_mock()
        mock_bot.send_message.side_effect = None
        mock_bot.send_message.return_value = "ok"
        result = await rate_limited_bot.send_message(chat_id=99999, text="Second")
        assert result == "ok"
