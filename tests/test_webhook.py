"""Tests for webhook handler.

This module tests FastAPI webhook routes and update processing.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Set environment variables before importing
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
os.environ["WEBHOOK_URL"] = "https://test.example.com"
os.environ["WEBHOOK_SECRET"] = "test_secret_1234567890"

from fastapi.testclient import TestClient

from src.handlers.webhook import WebhookHandler, get_webhook_handler


class TestWebhookHandler:
    """Test WebhookHandler class."""
    
    @pytest.fixture
    def handler(self):
        """Create webhook handler."""
        return WebhookHandler()
    
    def test_init(self, handler):
        """Test handler initialization."""
        assert handler.telegram_app is None
        assert handler.input_handler is None
    
    def test_validate_webhook_path_valid(self, handler):
        """Test validating correct webhook path."""
        with patch("src.handlers.webhook.settings") as mock_settings:
            mock_settings.get_webhook_path.return_value = "/webhook/abc123"
            
            assert handler._validate_webhook_path("/webhook/abc123") is True
    
    def test_validate_webhook_path_invalid(self, handler):
        """Test validating incorrect webhook path."""
        with patch("src.handlers.webhook.settings") as mock_settings:
            mock_settings.get_webhook_path.return_value = "/webhook/abc123"
            
            assert handler._validate_webhook_path("/webhook/wrong") is False
    
    def test_validate_telegram_token_valid(self, handler):
        """Test validating correct token."""
        with patch("src.handlers.webhook.settings") as mock_settings:
            mock_settings.telegram_bot_token.get_secret_value.return_value = "test_token"
            
            assert handler._validate_telegram_token("test_token") is True
    
    def test_validate_telegram_token_invalid(self, handler):
        """Test validating incorrect token."""
        with patch("src.handlers.webhook.settings") as mock_settings:
            mock_settings.telegram_bot_token.get_secret_value.return_value = "test_token"
            
            assert handler._validate_telegram_token("wrong_token") is False


class TestWebhookRoutes:
    """Test FastAPI webhook routes."""
    
    @pytest.fixture
    def app(self):
        """Create FastAPI app."""
        handler = WebhookHandler()
        
        # Mock the telegram app initialization
        with patch("telegram.ext.ApplicationBuilder") as mock_builder:
            mock_app = MagicMock()
            mock_app.bot = MagicMock()
            mock_builder.return_value.token.return_value.build.return_value = mock_app
            
            with patch("src.handlers.webhook.get_input_handler") as mock_get_handler:
                mock_handler = MagicMock()
                mock_handler.handle_button_press = AsyncMock()
                mock_get_handler.return_value = mock_handler
                
                # Mock process_update to avoid complex Telegram mocking
                with patch.object(handler, "process_update", new=AsyncMock()):
                    app = handler.create_app()
                    handler.telegram_app = mock_app
                    handler.input_handler = mock_handler
                    
                    return app
    
    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)
    
    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    def test_webhook_valid_callback(self, client):
        """Test webhook with valid callback query."""
        update_data = {
            "update_id": 123,
            "callback_query": {
                "id": "query_id",
                "from": {"id": 123, "is_bot": False, "first_name": "Test"},
                "message": {
                    "message_id": 789,
                    "chat": {"id": 123456, "type": "group"},
                    "date": 1234567890,
                },
                "data": "a",
            },
        }
        
        with patch("src.handlers.webhook.settings") as mock_settings:
            mock_settings.get_webhook_path.return_value = "/webhook/test"
            
            response = client.post("/webhook/test", json=update_data)
            
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
    
    def test_webhook_valid_command(self, client):
        """Test webhook with valid command."""
        update_data = {
            "update_id": 123,
            "message": {
                "message_id": 100,
                "from": {"id": 123, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 123456, "type": "group"},
                "date": 1234567890,
                "text": "/start_game",
            },
        }
        
        with patch("src.handlers.webhook.settings") as mock_settings:
            mock_settings.get_webhook_path.return_value = "/webhook/test"
            
            response = client.post("/webhook/test", json=update_data)
            
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
    
    def test_webhook_with_token_valid(self, client):
        """Test webhook endpoint with token validation."""
        update_data = {
            "update_id": 123,
            "message": {
                "message_id": 100,
                "from": {"id": 123, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 123456, "type": "group"},
                "date": 1234567890,
                "text": "/help",
            },
        }
        
        with patch("src.handlers.webhook.settings") as mock_settings:
            mock_settings.telegram_bot_token.get_secret_value.return_value = "test_token"
            
            # Mock process_update to avoid complex mocking
            with patch.object(WebhookHandler, "process_update", new=AsyncMock()):
                response = client.post("/webhook/test_token", json=update_data)
                
                assert response.status_code == 200
                assert response.json()["status"] == "ok"
    
    def test_webhook_with_token_invalid(self, client):
        """Test webhook endpoint with invalid token."""
        update_data = {"update_id": 123, "message": {"text": "/help"}}
        
        with patch("src.handlers.webhook.settings") as mock_settings:
            mock_settings.telegram_bot_token.get_secret_value.return_value = "test_token"
            
            response = client.post("/webhook/wrong_token", json=update_data)
            
            assert response.status_code == 401


class TestUpdateProcessing:
    """Test update processing logic."""
    
    @pytest.fixture
    def handler(self):
        """Create handler with mocked dependencies."""
        handler = WebhookHandler()
        handler.telegram_app = MagicMock()
        handler.input_handler = MagicMock()
        handler.input_handler.handle_button_press = AsyncMock()
        return handler
    
    @pytest.mark.asyncio
    async def test_process_callback_query(self, handler):
        """Test processing callback query update."""
        # Create a mock Update object directly instead of using de_json
        mock_update = MagicMock()
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.data = "a"
        mock_update.message = None
        
        with patch("telegram.Update.de_json", return_value=mock_update):
            update_data = {"update_id": 123, "callback_query": {"data": "a"}}
            
            await handler.process_update(update_data)
            
            # Should call input handler for button press
            handler.input_handler.handle_button_press.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_command(self, handler):
        """Test processing command message."""
        mock_update = MagicMock()
        mock_update.callback_query = None
        mock_update.message = MagicMock()
        mock_update.message.text = "/help"
        
        with patch("telegram.Update.de_json", return_value=mock_update):
            with patch("src.handlers.commands.help_command") as mock_help:
                mock_help.return_value = AsyncMock()
                
                update_data = {"update_id": 123, "message": {"text": "/help"}}
                await handler.process_update(update_data)
                
                mock_help.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_unknown_command(self, handler):
        """Test processing unknown command."""
        mock_update = MagicMock()
        mock_update.callback_query = None
        mock_update.message = MagicMock()
        mock_update.message.text = "/unknown_command"
        mock_update.message.bot = MagicMock()
        
        with patch("telegram.Update.de_json", return_value=mock_update):
            with patch("src.handlers.commands.unknown_command") as mock_unknown:
                mock_unknown.return_value = AsyncMock()
                
                update_data = {"update_id": 123, "message": {"text": "/unknown_command"}}
                await handler.process_update(update_data)
                
                mock_unknown.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_refresh_callback(self, handler):
        """Test processing refresh callback."""
        mock_update = MagicMock()
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.data = "refresh"
        mock_update.message = None
        
        with patch("telegram.Update.de_json", return_value=mock_update):
            with patch("src.handlers.commands.current_frame_command") as mock_refresh:
                mock_refresh.return_value = AsyncMock()
                
                update_data = {"update_id": 123, "callback_query": {"data": "refresh"}}
                await handler.process_update(update_data)
                
                mock_refresh.assert_called_once()


class TestSingleton:
    """Test singleton pattern."""
    
    def test_get_webhook_handler_creates_new(self):
        """Test getting handler creates new instance."""
        # Reset singleton
        import src.handlers.webhook as wh
        original = wh._webhook_handler
        wh._webhook_handler = None
        
        try:
            handler = get_webhook_handler()
            assert handler is not None
            assert isinstance(handler, WebhookHandler)
        finally:
            wh._webhook_handler = original
    
    def test_get_webhook_handler_returns_same(self):
        """Test getting handler returns same instance."""
        # Reset singleton
        import src.handlers.webhook as wh
        original = wh._webhook_handler
        wh._webhook_handler = None
        
        try:
            handler1 = get_webhook_handler()
            handler2 = get_webhook_handler()
            
            assert handler1 is handler2
        finally:
            wh._webhook_handler = original
