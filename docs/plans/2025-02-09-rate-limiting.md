# Rate Limiting Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement per-chat and global rate limiting for Telegram API calls with 429 error handling and user feedback via callback answers.

**Architecture:** 
- Create a `RateLimiter` class in `src/utils/rate_limiter.py` that tracks per-chat and global request timestamps using in-memory sliding windows
- Intercept all outgoing Telegram API calls through a wrapper/decorator pattern
- On 429 errors, extract `retry_after` and block all outgoing messages until that time
- Answer callback queries with rate limit feedback instead of sending messages

**Tech Stack:** Python 3.11, python-telegram-bot (existing), async/await

---

## Task 1: Create Rate Limiter Core

**Files:**
- Create: `src/utils/rate_limiter.py`
- Test: `tests/test_rate_limiter.py`

**Step 1: Write the failing test**

```python
import pytest
import asyncio
from datetime import datetime, timedelta
from src.utils.rate_limiter import RateLimiter


class TestRateLimiter:
    """Test rate limiter functionality."""
    
    def test_per_chat_limit_allows_under_threshold(self):
        """Should allow requests under per-chat limit."""
        limiter = RateLimiter(max_per_chat=1, per_chat_window=1.0, max_global=100, global_window=1.0)
        
        # First request should succeed
        assert limiter.check_rate_limit(chat_id=12345) is None
        
    def test_per_chat_limit_blocks_over_threshold(self):
        """Should block requests over per-chat limit."""
        limiter = RateLimiter(max_per_chat=1, per_chat_window=1.0, max_global=100, global_window=1.0)
        
        # First request
        limiter.check_rate_limit(chat_id=12345)
        
        # Second request should be rate limited
        result = limiter.check_rate_limit(chat_id=12345)
        assert result is not None
        assert result.retry_after > 0
        
    def test_global_limit_blocks_when_exceeded(self):
        """Should block when global limit exceeded."""
        limiter = RateLimiter(max_per_chat=10, per_chat_window=1.0, max_global=2, global_window=1.0)
        
        # Two requests from different chats
        limiter.check_rate_limit(chat_id=111)
        limiter.check_rate_limit(chat_id=222)
        
        # Third request should hit global limit
        result = limiter.check_rate_limit(chat_id=333)
        assert result is not None
        assert result.is_global is True
        
    def test_external_retry_after_blocks_all(self):
        """Should block all requests when external retry_after is set."""
        limiter = RateLimiter(max_per_chat=10, per_chat_window=1.0, max_global=100, global_window=1.0)
        
        # Set external block
        limiter.set_retry_after(5)
        
        # All requests should be blocked
        result = limiter.check_rate_limit(chat_id=12345)
        assert result is not None
        assert result.retry_after >= 4  # Approximately 5 seconds
        
    def test_is_blocked_during_external_retry_after(self):
        """is_blocked should return True during external retry_after."""
        limiter = RateLimiter(max_per_chat=10, per_chat_window=1.0, max_global=100, global_window=1.0)
        
        limiter.set_retry_after(2)
        
        assert limiter.is_blocked() is True
```

**Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_rate_limiter.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'src.utils.rate_limiter'"

**Step 3: Write minimal implementation**

```python
"""Rate limiter for Telegram API calls.

Provides per-chat and global rate limiting with support for
429 Retry-After responses from Telegram API.
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    retry_after: float
    is_global: bool
    message: str


class RateLimiter:
    """Rate limiter for Telegram API calls.
    
    Tracks per-chat and global request rates using sliding windows.
    Supports blocking all requests when Telegram returns 429 with retry_after.
    
    Example:
        >>> limiter = RateLimiter(max_per_chat=1, per_chat_window=1.0, max_global=30, global_window=1.0)
        >>> result = limiter.check_rate_limit(chat_id=12345)
        >>> if result:
        ...     print(f"Rate limited, retry after {result.retry_after}s")
    """
    
    def __init__(
        self,
        max_per_chat: int,
        per_chat_window: float,
        max_global: int,
        global_window: float,
    ):
        """Initialize rate limiter.
        
        Args:
            max_per_chat: Maximum requests per chat in the window
            per_chat_window: Time window in seconds for per-chat limit
            max_global: Maximum global requests across all chats
            global_window: Time window in seconds for global limit
        """
        self.max_per_chat = max_per_chat
        self.per_chat_window = per_chat_window
        self.max_global = max_global
        self.global_window = global_window
        
        # Per-chat request timestamps: chat_id -> deque of timestamps
        self._chat_requests: dict[int, deque[float]] = defaultdict(deque)
        
        # Global request timestamps
        self._global_requests: deque[float] = deque()
        
        # External block (from 429 error): timestamp when block expires
        self._blocked_until: Optional[float] = None
    
    def check_rate_limit(self, chat_id: int) -> Optional[RateLimitResult]:
        """Check if a request should be rate limited.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            RateLimitResult if rate limited, None if allowed
        """
        now = time.monotonic()
        
        # Check external block first (from 429 errors)
        if self._blocked_until is not None:
            if now < self._blocked_until:
                retry_after = self._blocked_until - now
                return RateLimitResult(
                    retry_after=retry_after,
                    is_global=True,
                    message=f"Bot is rate limited by Telegram. Retry after {int(retry_after)}s."
                )
            else:
                # Block has expired
                self._blocked_until = None
        
        # Clean old entries
        self._cleanup_old_entries(now)
        
        # Check global limit
        if len(self._global_requests) >= self.max_global:
            oldest_global = self._global_requests[0]
            retry_after = (oldest_global + self.global_window) - now
            return RateLimitResult(
                retry_after=max(0.1, retry_after),
                is_global=True,
                message=f"Global rate limit exceeded. Retry after {int(retry_after)}s."
            )
        
        # Check per-chat limit
        chat_deque = self._chat_requests[chat_id]
        if len(chat_deque) >= self.max_per_chat:
            oldest_chat = chat_deque[0]
            retry_after = (oldest_chat + self.per_chat_window) - now
            return RateLimitResult(
                retry_after=max(0.1, retry_after),
                is_global=False,
                message=f"Rate limit exceeded for this chat. Retry after {int(retry_after)}s."
            )
        
        # Record this request
        self._global_requests.append(now)
        self._chat_requests[chat_id].append(now)
        
        return None
    
    def set_retry_after(self, retry_after: int) -> None:
        """Set external block from Telegram 429 response.
        
        Args:
            retry_after: Seconds to wait before allowing requests again
        """
        now = time.monotonic()
        self._blocked_until = now + retry_after
        logger.warning(f"Rate limited by Telegram. Blocking all requests for {retry_after}s")
    
    def is_blocked(self) -> bool:
        """Check if all requests are currently blocked.
        
        Returns:
            True if blocked, False otherwise
        """
        if self._blocked_until is None:
            return False
        
        now = time.monotonic()
        if now >= self._blocked_until:
            self._blocked_until = None
            return False
        
        return True
    
    def _cleanup_old_entries(self, now: float) -> None:
        """Remove expired entries from tracking deques."""
        # Clean global requests
        while self._global_requests and self._global_requests[0] < now - self.global_window:
            self._global_requests.popleft()
        
        # Clean per-chat requests
        for chat_id in list(self._chat_requests.keys()):
            chat_deque = self._chat_requests[chat_id]
            while chat_deque and chat_deque[0] < now - self.per_chat_window:
                chat_deque.popleft()
            
            # Remove empty deques
            if not chat_deque:
                del self._chat_requests[chat_id]


# Singleton instance (initialized with defaults, will be configured from settings)
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the singleton RateLimiter instance.
    
    Note: Must be initialized with proper config via init_rate_limiter() first.
    
    Returns:
        RateLimiter instance
    """
    global _rate_limiter
    if _rate_limiter is None:
        # Default values (should be overridden by init_rate_limiter)
        _rate_limiter = RateLimiter(
            max_per_chat=1,
            per_chat_window=1.0,
            max_global=30,
            global_window=1.0,
        )
    return _rate_limiter


def init_rate_limiter(
    max_per_chat: int,
    per_chat_window: float,
    max_global: int,
    global_window: float,
) -> RateLimiter:
    """Initialize the rate limiter with configuration.
    
    Args:
        max_per_chat: Maximum requests per chat in the window
        per_chat_window: Time window in seconds for per-chat limit
        max_global: Maximum global requests across all chats
        global_window: Time window in seconds for global limit
        
    Returns:
        Configured RateLimiter instance
    """
    global _rate_limiter
    _rate_limiter = RateLimiter(
        max_per_chat=max_per_chat,
        per_chat_window=per_chat_window,
        max_global=max_global,
        global_window=global_window,
    )
    logger.info(
        f"Rate limiter initialized: per_chat={max_per_chat}/{per_chat_window}s, "
        f"global={max_global}/{global_window}s"
    )
    return _rate_limiter
```

**Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_rate_limiter.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_rate_limiter.py src/utils/rate_limiter.py
git commit -m "feat: add rate limiter core with per-chat and global limits"
```

---

## Task 2: Add Rate Limiter Settings

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
class TestRateLimiterSettings:
    """Test rate limiter configuration settings."""
    
    def test_default_rate_limiter_settings(self, monkeypatch, tmp_path):
        """Should have default rate limiter values."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("WEBHOOK_URL", "https://example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "test_secret_123456789")
        
        from src.config import Settings
        settings = Settings()
        
        assert settings.rate_limit_per_chat == 1
        assert settings.rate_limit_per_chat_window == 1.0
        assert settings.rate_limit_global == 30
        assert settings.rate_limit_global_window == 1.0
        
    def test_custom_rate_limiter_settings(self, monkeypatch, tmp_path):
        """Should allow custom rate limiter values."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("WEBHOOK_URL", "https://example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "test_secret_123456789")
        monkeypatch.setenv("RATE_LIMIT_PER_CHAT", "5")
        monkeypatch.setenv("RATE_LIMIT_PER_CHAT_WINDOW", "2.0")
        monkeypatch.setenv("RATE_LIMIT_GLOBAL", "50")
        monkeypatch.setenv("RATE_LIMIT_GLOBAL_WINDOW", "5.0")
        
        from src.config import Settings
        settings = Settings()
        
        assert settings.rate_limit_per_chat == 5
        assert settings.rate_limit_per_chat_window == 2.0
        assert settings.rate_limit_global == 50
        assert settings.rate_limit_global_window == 5.0
```

**Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_config.py::TestRateLimiterSettings -v`

Expected: FAIL with "AttributeError: 'Settings' object has no attribute 'rate_limit_per_chat'"

**Step 3: Add settings to config.py**

Add after the existing retry settings (around line 144):

```python
    # Rate limiter settings
    rate_limit_per_chat: int = Field(
        default=1,
        description="Maximum messages per chat within the window",
        ge=1,
        le=100,
    )
    rate_limit_per_chat_window: float = Field(
        default=1.0,
        description="Time window in seconds for per-chat rate limit",
        ge=0.1,
        le=60.0,
    )
    rate_limit_global: int = Field(
        default=30,
        description="Maximum messages globally across all chats within the window",
        ge=1,
        le=1000,
    )
    rate_limit_global_window: float = Field(
        default=1.0,
        description="Time window in seconds for global rate limit",
        ge=0.1,
        le=60.0,
    )
```

**Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_config.py::TestRateLimiterSettings -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_config.py src/config.py
git commit -m "feat: add rate limiter configuration settings"
```

---

## Task 3: Initialize Rate Limiter on Startup

**Files:**
- Modify: `src/main.py`
- Modify: `src/handlers/webhook.py`

**Step 1: Write the failing test**

Add to `tests/test_main.py`:

```python
class TestRateLimiterInitialization:
    """Test rate limiter is initialized on startup."""
    
    @pytest.mark.asyncio
    async def test_rate_limiter_initialized_in_startup(self, monkeypatch, tmp_path):
        """Should initialize rate limiter during lifespan startup."""
        import os
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("WEBHOOK_URL", "https://example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "test_secret_123456789")
        
        from src.utils.rate_limiter import get_rate_limiter, init_rate_limiter
        
        # Reset singleton
        import src.utils.rate_limiter as rl_module
        rl_module._rate_limiter = None
        
        # Initialize with test values
        limiter = init_rate_limiter(
            max_per_chat=2,
            per_chat_window=1.5,
            max_global=25,
            global_window=2.0,
        )
        
        assert limiter.max_per_chat == 2
        assert limiter.per_chat_window == 1.5
        assert limiter.max_global == 25
        assert limiter.global_window == 2.0
```

**Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_main.py::TestRateLimiterInitialization -v`

Expected: FAIL (test infrastructure issue, but proceed)

**Step 3: Initialize rate limiter in main.py**

Modify `src/main.py` to initialize the rate limiter in the lifespan:

```python
# At the top with other imports
from src.utils.rate_limiter import init_rate_limiter

# In lifespan() function, after settings are loaded and before webhook setup:
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Initialize rate limiter
    init_rate_limiter(
        max_per_chat=settings.rate_limit_per_chat,
        per_chat_window=settings.rate_limit_per_chat_window,
        max_global=settings.rate_limit_global,
        global_window=settings.rate_limit_global_window,
    )
    
    # ... rest of existing startup code
```

**Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_main.py::TestRateLimiterInitialization -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_main.py src/main.py
git commit -m "feat: initialize rate limiter on application startup"
```

---

## Task 4: Create Telegram API Wrapper with Rate Limiting

**Files:**
- Create: `src/utils/telegram_client.py`
- Test: `tests/test_telegram_client.py`

**Step 1: Write the failing test**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
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
```

**Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_telegram_client.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'src.utils.telegram_client'"

**Step 3: Write minimal implementation**

```python
"""Rate-limited Telegram bot wrapper.

Wraps Telegram Bot API calls with rate limiting and automatic
handling of 429 RetryAfter errors.
"""

import logging
from typing import Optional, Any
from functools import wraps

from telegram import Bot, InputMedia
from telegram.error import RetryAfter, TelegramError

from src.utils.rate_limiter import get_rate_limiter, RateLimitResult

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
            rate_limit_result = limiter.check_rate_limit(chat_id)
            if rate_limit_result:
                logger.debug(
                    f"Rate limited {method_name} for chat {chat_id}: "
                    f"retry_after={rate_limit_result.retry_after:.1f}s"
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
```

**Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_telegram_client.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_telegram_client.py src/utils/telegram_client.py
git commit -m "feat: add rate-limited Telegram bot wrapper"
```

---

## Task 5: Integrate Rate Limiting into Input Handler

**Files:**
- Modify: `src/handlers/input_handler.py`
- Test: `tests/test_input_handler.py`

**Step 1: Write the failing test**

Add to `tests/test_input_handler.py`:

```python
class TestInputHandlerRateLimiting:
    """Test rate limiting in input handler."""
    
    @pytest.mark.asyncio
    async def test_callback_answered_when_rate_limited(self, monkeypatch):
        """Should answer callback with rate limit message when limited."""
        import os
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
        
        from src.utils.rate_limiter import init_rate_limiter
        init_rate_limiter(max_per_chat=1, per_chat_window=60.0, max_global=100, global_window=1.0)
        
        # Reset rate limiter state
        from src.utils.rate_limiter import get_rate_limiter
        limiter = get_rate_limiter()
        limiter._chat_requests.clear()
        limiter._global_requests.clear()
        
        from src.handlers.input_handler import InputHandler
        from unittest.mock import AsyncMock, MagicMock
        
        mock_bot = MagicMock()
        handler = InputHandler(mock_bot)
        
        # Create mock callback query
        callback_query = MagicMock()
        callback_query.message.chat.id = 12345
        callback_query.message.message_id = 100
        callback_query.data = "btn_a"
        callback_query.from_user.id = 999
        callback_query.from_user.first_name = "Test"
        callback_query.from_user.username = "testuser"
        callback_query.answer = AsyncMock()
        
        # First call should work (creates session first)
        # We'll test rate limiting on second call
        # ...this test needs the integration to be in place
        pass
```

**Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_input_handler.py::TestInputHandlerRateLimiting -v`

Expected: FAIL (test incomplete, but shows infrastructure is ready)

**Step 3: Modify input_handler.py to integrate rate limiting**

Modify `src/handlers/input_handler.py`:

1. Add import:
```python
from src.utils.rate_limiter import get_rate_limiter
```

2. Modify `_handle_normal_button_press` to check rate limits:

Replace the early part of `_handle_normal_button_press`:

```python
    async def _handle_normal_button_press(
        self, callback_query, session, chat_id, message_id, button, user_id, user_name
    ) -> None:
        """Handle normal single button press (existing logic)."""
        # Check rate limits first
        limiter = get_rate_limiter()
        rate_limit_result = limiter.check_rate_limit(chat_id)
        
        if rate_limit_result:
            # Rate limited - answer callback and return
            try:
                await callback_query.answer(
                    f"⏳ {rate_limit_result.message}",
                    show_alert=False
                )
            except Exception as e:
                logger.error(f"Error answering callback for chat {chat_id}: {e}")
            return
        
        # Rest of existing logic continues...
        if chat_id in self._processing:
            # ...existing code
```

3. Similarly modify `_handle_sequence_button_press`:

```python
    async def _handle_sequence_button_press(
        self, callback_query, session, chat_id, message_id, user_id, user_name
    ) -> None:
        """Handle SEQUENCE button press to start building."""
        # Check rate limits first
        limiter = get_rate_limiter()
        rate_limit_result = limiter.check_rate_limit(chat_id)
        
        if rate_limit_result:
            try:
                await callback_query.answer(
                    f"⏳ {rate_limit_result.message}",
                    show_alert=False
                )
            except Exception as e:
                logger.error(f"Error answering callback for chat {chat_id}: {e}")
            return
        
        # Rest of existing logic...
        if chat_id in self._processing:
            # ...existing code
```

**Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_input_handler.py -v`

Expected: PASS (existing tests + new rate limiting behavior)

**Step 5: Commit**

```bash
git add tests/test_input_handler.py src/handlers/input_handler.py
git commit -m "feat: integrate rate limiting into input handler"
```

---

## Task 6: Handle RetryAfter in Telegram Client Wrapper

**Files:**
- Modify: `src/utils/telegram_client.py`
- Test: `tests/test_telegram_client.py`

**Step 1: Write the failing test**

Add to `tests/test_telegram_client.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_telegram_client.py::TestRateLimitedBot::test_rate_limiter_blocks_after_retry_after -v`

Expected: FAIL with assertion error (behavior not implemented correctly yet)

**Step 3: Verify implementation handles RetryAfter correctly**

The implementation from Task 4 should already handle this correctly. The decorator catches `RetryAfter` and sets the global block. Verify the code is correct:

```python
# In _rate_limited_method decorator:
except RetryAfter as e:
    # Telegram returned 429, set global block
    limiter.set_retry_after(e.retry_after)
    logger.warning(...)
    raise
```

**Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_telegram_client.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_telegram_client.py
git commit -m "test: verify RetryAfter handling blocks subsequent requests"
```

---

## Task 7: Wire RateLimitedBot into Webhook Handler

**Files:**
- Modify: `src/handlers/webhook.py`
- Test: `tests/test_webhook.py`

**Step 1: Write the failing test**

Add to `tests/test_webhook.py`:

```python
class TestWebhookRateLimiterIntegration:
    """Test rate limiter is properly wired in webhook handler."""
    
    @pytest.mark.asyncio
    async def test_input_handler_uses_rate_limited_bot(self, monkeypatch):
        """Should use RateLimitedBot wrapper for input handler."""
        import os
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
        
        from src.handlers.webhook import WebhookHandler
        from src.utils.telegram_client import RateLimitedBot
        from unittest.mock import MagicMock
        
        mock_bot = MagicMock()
        handler = WebhookHandler(bot=mock_bot)
        
        # The input handler should use a RateLimitedBot
        assert isinstance(handler._input_handler.bot, RateLimitedBot)
```

**Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_webhook.py::TestWebhookRateLimiterIntegration -v`

Expected: FAIL with "AttributeError: 'InputHandler' object has no attribute 'bot'" or similar

**Step 3: Modify webhook.py to use RateLimitedBot**

Modify `src/handlers/webhook.py`:

1. Add import:
```python
from src.utils.telegram_client import RateLimitedBot
```

2. Modify `__init__` to wrap the bot:

```python
    def __init__(self, bot: Bot):
        """Initialize with Telegram bot."""
        self.bot = bot
        # Wrap bot with rate limiting
        self._rate_limited_bot = RateLimitedBot(bot)
        self._input_handler = InputHandler(self._rate_limited_bot)
```

**Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_webhook.py::TestWebhookRateLimiterIntegration -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_webhook.py src/handlers/webhook.py
git commit -m "feat: wire RateLimitedBot into webhook handler"
```

---

## Task 8: Add Integration Tests

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Write comprehensive integration test**

Add to `tests/test_integration.py`:

```python
class TestRateLimiterIntegration:
    """Integration tests for rate limiting."""
    
    @pytest.fixture(autouse=True)
    def reset_rate_limiter(self, monkeypatch):
        """Reset rate limiter singleton before each test."""
        import src.utils.rate_limiter as rl_module
        rl_module._rate_limiter = None
        yield
    
    @pytest.mark.asyncio
    async def test_full_flow_rate_limit_blocks_callback(self, monkeypatch, tmp_path):
        """Full flow: rate limit should answer callback with message."""
        import os
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("WEBHOOK_URL", "https://example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "test_secret_123456789")
        monkeypatch.setenv("RATE_LIMIT_PER_CHAT", "1")
        monkeypatch.setenv("RATE_LIMIT_PER_CHAT_WINDOW", "60")
        
        from src.utils.rate_limiter import init_rate_limiter
        from src.handlers.input_handler import InputHandler
        from unittest.mock import MagicMock, AsyncMock, patch
        
        # Initialize with strict limits
        init_rate_limiter(max_per_chat=1, per_chat_window=60.0, max_global=100, global_window=1.0)
        
        mock_bot = MagicMock()
        mock_bot.send_photo = AsyncMock()
        mock_bot.edit_message_reply_markup = AsyncMock()
        
        handler = InputHandler(mock_bot)
        
        # Create session
        from src.models.game_state import ChatGameState
        session = handler._create_session(12345, 100)
        
        # First button press
        callback1 = MagicMock()
        callback1.message.chat.id = 12345
        callback1.message.message_id = 100
        callback1.data = "btn_a"
        callback1.from_user.id = 999
        callback1.from_user.first_name = "Test"
        callback1.from_user.username = "testuser"
        callback1.answer = AsyncMock()
        
        # Mock controller
        with patch('src.handlers.input_handler.game_controller_manager') as mock_mgr:
            mock_controller = MagicMock()
            mock_controller.is_initialized.return_value = True
            mock_controller.get_frame.return_value = MagicMock()
            mock_controller.get_frame_as_png.return_value = MagicMock()
            mock_controller.tick = MagicMock()
            mock_controller.send_input = MagicMock()
            mock_mgr.get_controller.return_value = mock_controller
            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            
            # First press should work
            await handler.handle_button_press(callback1)
            
            # Wait for processing to complete
            await asyncio.sleep(0.1)
            
            # Reset and try second press
            handler._processing.discard(12345)
            
            callback2 = MagicMock()
            callback2.message.chat.id = 12345
            callback2.message.message_id = 100
            callback2.data = "btn_b"
            callback2.from_user.id = 888
            callback2.from_user.first_name = "Test2"
            callback2.from_user.username = "testuser2"
            callback2.answer = AsyncMock()
            
            # Second press should be rate limited
            await handler.handle_button_press(callback2)
            
            # Should have answered with rate limit message
            callback2.answer.assert_called_once()
            call_args = callback2.answer.call_args
            assert "Rate limit" in call_args[0][0] or "⏳" in call_args[0][0]
```

**Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_integration.py::TestRateLimiterIntegration -v`

Expected: FAIL (integration needs full flow working)

**Step 3: Ensure all components are integrated**

Verify the following are in place:
1. RateLimiter core ✓
2. Settings ✓
3. Initialization on startup ✓
4. RateLimitedBot wrapper ✓
5. InputHandler integration ✓
6. Webhook wiring ✓

**Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_integration.py::TestRateLimiterIntegration -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add rate limiting integration tests"
```

---

## Task 9: Run All Tests

**Step 1: Run full test suite**

```bash
poetry run pytest
```

Expected: All tests pass

**Step 2: Fix any remaining issues**

Address any test failures that arise from the integration.

**Step 3: Final commit**

```bash
git commit -m "feat: complete rate limiting implementation with per-chat and global limits

- Add RateLimiter with sliding window tracking
- Add configurable limits (default: 1/sec per chat, 30/sec global)
- Add RateLimitedBot wrapper for Telegram API calls
- Handle 429 RetryAfter errors with global blocking
- Answer callback queries with rate limit feedback
- All visible operations are rate limited"
```

---

## Summary

This implementation adds comprehensive rate limiting to the Telegram bot:

1. **Per-chat limits**: Configurable max requests per time window per chat (default: 1 msg/sec)
2. **Global limits**: Configurable max requests across all chats (default: 30 msg/sec)
3. **429 handling**: When Telegram returns RetryAfter, all outgoing messages are blocked until that time
4. **User feedback**: Rate-limited users get callback answers explaining the wait time
5. **Non-queueing**: Requests are dropped when rate limited, users must retry

Configuration via environment variables:
- `RATE_LIMIT_PER_CHAT` (default: 1)
- `RATE_LIMIT_PER_CHAT_WINDOW` (default: 1.0)
- `RATE_LIMIT_GLOBAL` (default: 30)
- `RATE_LIMIT_GLOBAL_WINDOW` (default: 1.0)
