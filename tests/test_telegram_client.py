"""Tests for rate-limited Telegram client wrapper."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram.error import RetryAfter

from src.utils.telegram_client import RateLimitedBot
from src.utils.rate_limiter import RateLimitException


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
        from src.utils.rate_limiter import init_rate_limiter
        init_rate_limiter(max_per_chat=10, per_chat_window=1.0, max_global=100, global_window=1.0)
        
        await rate_limited_bot.send_message(chat_id=12345, text="Hello")
        
        mock_bot.send_message.assert_called_once_with(chat_id=12345, text="Hello")
    
    @pytest.mark.asyncio
    async def test_blocks_request_when_rate_limited(self, rate_limited_bot, mock_bot):
        """Should block request when rate limited."""
        from src.utils.rate_limiter import init_rate_limiter
        init_rate_limiter(max_per_chat=1, per_chat_window=60.0, max_global=100, global_window=1.0)
        
        # First request
        await rate_limited_bot.send_message(chat_id=12345, text="First")
        
        # Second request should be blocked
        result = await rate_limited_bot.send_message(chat_id=12345, text="Second")
        
        assert result is False
        mock_bot.send_message.assert_called_once()  # Only first call
    
    @pytest.mark.asyncio
    async def test_catches_retry_after_and_blocks(self, rate_limited_bot, mock_bot):
        """Should catch RetryAfter and set global block."""
        from src.utils.rate_limiter import init_rate_limiter, get_rate_limiter
        init_rate_limiter(max_per_chat=100, per_chat_window=1.0, max_global=100, global_window=1.0)
        
        # Simulate Telegram returning 429
        mock_bot.send_message.side_effect = RetryAfter(5)
        
        with pytest.raises(RetryAfter):
            await rate_limited_bot.send_message(chat_id=12345, text="Test")
        
        # Rate limiter should now be blocked
        limiter = get_rate_limiter()
        assert limiter.is_blocked() is True
        
    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_after_retry_after(self, rate_limited_bot, mock_bot):
        """Should block subsequent requests after catching RetryAfter."""
        from src.utils.rate_limiter import init_rate_limiter, get_rate_limiter
        init_rate_limiter(max_per_chat=100, per_chat_window=1.0, max_global=100, global_window=1.0)
        
        # Reset limiter state
        limiter = get_rate_limiter()
        limiter._blocked_until = None
        
        # First call raises RetryAfter
        mock_bot.send_message.side_effect = [
            RetryAfter(5),  # First call fails
            AsyncMock()      # Second call would succeed but should be blocked
        ]
        
        with pytest.raises(RetryAfter):
            await rate_limited_bot.send_message(chat_id=12345, text="First")
        
        # Now all calls should be rate limited (globally blocked)
        result = await rate_limited_bot.send_message(chat_id=99999, text="Second")
        assert result is False
        
    @pytest.mark.asyncio
    async def test_edit_message_media_rate_limited(self, rate_limited_bot, mock_bot):
        """Should rate limit edit_message_media calls."""
        from src.utils.rate_limiter import init_rate_limiter
        init_rate_limiter(max_per_chat=1, per_chat_window=60.0, max_global=100, global_window=1.0)
        
        mock_media = MagicMock()
        
        # First edit
        await rate_limited_bot.edit_message_media(
            chat_id=12345, message_id=100, media=mock_media
        )
        
        # Second edit should be blocked
        result = await rate_limited_bot.edit_message_media(
            chat_id=12345, message_id=101, media=mock_media
        )
        
        assert result is False
