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
                    message=f"Aguardando liberação do Telegram. Tente de novo em {int(retry_after)}s."
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
                message=f"O bot está sobrecarregado. Tente de novo em {int(retry_after)}s."
            )
        
        # Check per-chat limit
        chat_deque = self._chat_requests[chat_id]
        if len(chat_deque) >= self.max_per_chat:
            oldest_chat = chat_deque[0]
            retry_after = (oldest_chat + self.per_chat_window) - now
            return RateLimitResult(
                retry_after=max(0.1, retry_after),
                is_global=False,
                message=f"Muitos comandos de uma vez! Tente de novo em {int(retry_after)}s."
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
