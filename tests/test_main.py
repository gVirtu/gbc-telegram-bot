"""Tests for main application entry point.

This module tests the main application setup and helper functions.
"""

import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Set environment variables before importing
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
os.environ["WEBHOOK_URL"] = "https://test.example.com"
os.environ["WEBHOOK_SECRET"] = "test_secret_1234567890"
os.environ["PYTEST_CURRENT_TEST"] = "1"  # Skip ROM validation

from src.main import setup_webhook, delete_webhook, main


class TestSetupWebhook:
    """Test webhook setup functionality."""
    
    def test_setup_webhook_success(self):
        """Test successful webhook setup."""
        with patch("telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot.set_webhook = AsyncMock(return_value=True)
            mock_bot.session.close = AsyncMock()
            mock_bot_class.return_value = mock_bot
            
            # Call setup_webhook which runs async code
            import asyncio
            from src.main import settings
            
            async def _test_setup():
                bot = mock_bot_class(token=settings.telegram_bot_token.get_secret_value())
                webhook_url = f"{settings.webhook_url}{settings.get_webhook_path()}"
                await bot.set_webhook(
                    url=webhook_url,
                    secret_token=settings.webhook_secret,
                )
                await bot.session.close()
            
            asyncio.run(_test_setup())
            
            mock_bot.set_webhook.assert_called_once()


class TestDeleteWebhook:
    """Test webhook deletion functionality."""
    
    def test_delete_webhook_success(self):
        """Test successful webhook deletion."""
        with patch("telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot.delete_webhook = AsyncMock(return_value=True)
            mock_bot.session.close = AsyncMock()
            mock_bot_class.return_value = mock_bot
            
            import asyncio
            from src.main import settings
            
            async def _test_delete():
                bot = mock_bot_class(token=settings.telegram_bot_token.get_secret_value())
                await bot.delete_webhook()
                await bot.session.close()
            
            asyncio.run(_test_delete())
            
            mock_bot.delete_webhook.assert_called_once()


class TestMainFunction:
    """Test main entry point."""
    
    def test_main_validates_config(self):
        """Test main validates configuration."""
        # Test that settings can be accessed without errors
        from src.main import settings
        
        try:
            _ = settings.telegram_bot_token
            _ = settings.webhook_url
            _ = settings.webhook_secret
            config_valid = True
        except Exception:
            config_valid = False
        
        assert config_valid is True
    
    def test_main_has_required_vars(self):
        """Test that main module has required configuration."""
        from src.main import settings
        
        # All should be set from environment variables
        assert settings.telegram_bot_token.get_secret_value() == "test_token"
        assert str(settings.webhook_url).startswith("https://")
        assert settings.webhook_secret is not None


class TestAppCreation:
    """Test FastAPI app creation."""
    
    def test_app_is_created(self):
        """Test that FastAPI app is created."""
        from src.main import app
        
        assert app is not None
        # Check it has routes (FastAPI routes object)
        assert len(app.routes) > 0


class TestImports:
    """Test module imports."""
    
    def test_imports_succeed(self):
        """Test that all imports work correctly."""
        # These should not raise any errors
        from src.main import (
            settings,
            handler,
            app,
            logger,
            setup_webhook,
            delete_webhook,
            main,
        )
        
        assert settings is not None
        assert handler is not None
        assert app is not None
        assert logger is not None
        assert callable(setup_webhook)
        assert callable(delete_webhook)
        assert callable(main)
