"""Rate-limited Telegram bot wrapper.

Wraps Telegram Bot API calls with rate limiting and automatic
handling of 429 RetryAfter errors.
"""

import logging
from typing import Optional, Any
from functools import wraps

from telegram import Bot, InputMedia
from telegram.error import RetryAfter, TelegramError

from src.utils.rate_limiter import get_rate_limiter, RateLimitException

logger = logging.getLogger(__name__)


def _rate_limited_method(method_name: str):
    """Decorator to add rate limiting to a bot method.
    
    Args:
        method_name: Name of the method being wrapped (for logging)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, chat_id: int, *args, **kwargs):
            limiter = get_rate_limiter()
            
            # Check rate limit
            try:
                limiter.check_rate_limit(chat_id)
            except RateLimitException as e:
                logger.debug(
                    f"Rate limited {method_name} for chat {chat_id}: "
                    f"retry_after={e.retry_after:.1f}s"
                )
                return False
            
            try:
                return await func(self, chat_id, *args, **kwargs)
            except RetryAfter as e:
                # Telegram returned 429, set global block
                limiter.set_retry_after(e.retry_after)
                logger.warning(
                    f"Telegram rate limit hit in {method_name} for chat {chat_id}: "
                    f"retry_after={e.retry_after}s"
                )
                raise
            except TelegramError as e:
                logger.error(f"Telegram error in {method_name} for chat {chat_id}: {e}")
                raise
        
        return wrapper
    return decorator


class RateLimitedBot:
    """Wrapper around Telegram Bot with rate limiting.
    
    Intercepts all outgoing API calls to enforce:
    1. Per-chat rate limits
    2. Global rate limits  
    3. Telegram 429 Retry-After handling
    
    Example:
        >>> bot = RateLimitedBot(telegram_bot)
        >>> await bot.send_message(chat_id=12345, text="Hello")
        False  # Rate limited
        >>> await bot.send_message(chat_id=12345, text="Hello")
        Message(...)  # Success
    """
    
    def __init__(self, bot: Bot):
        """Initialize with a Telegram Bot instance.
        
        Args:
            bot: The underlying Telegram Bot
        """
        self._bot = bot
    
    @_rate_limited_method("send_message")
    async def send_message(
        self,
        chat_id: int,
        text: str,
        **kwargs
    ) -> Optional[Any]:
        """Send a text message with rate limiting.
        
        Args:
            chat_id: Target chat ID
            text: Message text
            **kwargs: Additional arguments for send_message
            
        Returns:
            Message object on success, False if rate limited
        """
        return await self._bot.send_message(chat_id=chat_id, text=text, **kwargs)
    
    @_rate_limited_method("send_photo")
    async def send_photo(
        self,
        chat_id: int,
        photo: Any,
        **kwargs
    ) -> Optional[Any]:
        """Send a photo with rate limiting.
        
        Args:
            chat_id: Target chat ID
            photo: Photo to send
            **kwargs: Additional arguments for send_photo
            
        Returns:
            Message object on success, False if rate limited
        """
        return await self._bot.send_photo(chat_id=chat_id, photo=photo, **kwargs)
    
    @_rate_limited_method("edit_message_media")
    async def edit_message_media(
        self,
        chat_id: int,
        message_id: int,
        media: InputMedia,
        **kwargs
    ) -> Optional[Any]:
        """Edit message media with rate limiting.
        
        Args:
            chat_id: Target chat ID
            message_id: Message ID to edit
            media: New media
            **kwargs: Additional arguments
            
        Returns:
            Message object on success, False if rate limited
        """
        return await self._bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=media,
            **kwargs
        )
    
    @_rate_limited_method("edit_message_reply_markup")
    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        **kwargs
    ) -> Optional[Any]:
        """Edit message reply markup with rate limiting.
        
        Args:
            chat_id: Target chat ID
            message_id: Message ID to edit
            **kwargs: Additional arguments
            
        Returns:
            Message object on success, False if rate limited
        """
        return await self._bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            **kwargs
        )
    
    def __getattr__(self, name: str) -> Any:
        """Pass through any other attributes to the underlying bot."""
        return getattr(self._bot, name)
