"""Tests for rate limiter module."""

import pytest
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
