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

# Clear settings cache
from src.config import get_settings, settings
get_settings.cache_clear()
settings._instance = None

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
    
    def test_validate_telegram_secret_valid(self, handler):
        """Test validating correct token."""
        with patch("src.handlers.webhook.settings") as mock_settings:
            mock_settings.webhook_secret = "test_token"
            
            assert handler._validate_telegram_secret("test_token") is True
    
    def test_validate_telegram_secret_invalid(self, handler):
        """Test validating incorrect token."""
        with patch("src.handlers.webhook.settings") as mock_settings:
            mock_settings.webhook_secret = "test_token"
            
            assert handler._validate_telegram_secret("wrong_token") is False


class TestWebhookRoutes:
    """Test FastAPI webhook routes."""
    
    @pytest.fixture
    def app(self):
        """Create FastAPI app."""
        handler = WebhookHandler()

        # Mock the telegram app initialization
        mock_app = MagicMock()
        mock_app.bot = MagicMock()

        mock_handler = MagicMock()
        mock_handler.handle_button_press = AsyncMock()

        # Create app
        app = handler.create_app()
        handler.telegram_app = mock_app
        handler.input_handler = mock_handler

        # Attach handler for later patching
        app.state.webhook_handler = handler

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
    
    def test_webhook_valid_callback(self, client, app):
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

        # Get the actual webhook path from settings
        from src.config import settings
        webhook_path = settings.get_webhook_path()
        webhook_secret = settings.webhook_secret

        # Mock process_update to avoid complex parsing
        with patch.object(app.state.webhook_handler, "process_update", new=AsyncMock()):
            response = client.post(webhook_path, json=update_data, headers={"X-Telegram-Bot-Api-Secret-Token": webhook_secret})

            assert response.status_code == 200
            assert response.json()["status"] == "ok"
    
    def test_webhook_valid_command(self, client, app):
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

        # Get the actual webhook path from settings
        from src.config import settings
        webhook_path = settings.get_webhook_path()
        webhook_secret = settings.webhook_secret

        # Mock process_update to avoid complex parsing
        with patch.object(app.state.webhook_handler, "process_update", new=AsyncMock()):
            response = client.post(webhook_path, json=update_data, headers={"X-Telegram-Bot-Api-Secret-Token": webhook_secret})

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
            mock_settings.get_webhook_hash.return_value = "test_token"
            mock_settings.webhook_secret = "secret_token"
            
            # Mock process_update to avoid complex mocking
            with patch.object(WebhookHandler, "process_update", new=AsyncMock()):
                response = client.post("/webhook/test_token", json=update_data, headers={"X-Telegram-Bot-Api-Secret-Token": "secret_token"})
                
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
        # Set up mock telegram adapter
        mock_adapter = MagicMock()
        mock_adapter.send_text = AsyncMock()
        mock_adapter.is_admin = AsyncMock(return_value=True)
        mock_adapter.answer_interaction = AsyncMock()
        mock_adapter.build_game_keyboard = MagicMock(return_value=None)
        handler._telegram_adapter = mock_adapter
        return handler

    @pytest.mark.asyncio
    async def test_process_callback_query(self, handler):
        """Test processing callback query update."""
        # Create a mock Update object directly instead of using de_json
        mock_update = MagicMock()
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.data = "a"
        mock_update.callback_query.message = MagicMock()
        mock_update.callback_query.message.chat.id = 123456
        mock_update.callback_query.message.message_id = 789
        mock_update.callback_query.from_user.id = 456
        mock_update.callback_query.from_user.first_name = "TestUser"
        mock_update.callback_query.from_user.username = None
        mock_update.message = None

        with patch("telegram.Update.de_json", return_value=mock_update):
            with patch("src.handlers.webhook.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []  # Allow all chats
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
        mock_update.message.chat.id = 123456
        mock_update.message.message_id = 789
        mock_update.effective_chat = MagicMock()
        mock_update.effective_chat.id = 123456
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 456
        mock_update.effective_user.first_name = "TestUser"
        mock_update.effective_user.username = None

        with patch("telegram.Update.de_json", return_value=mock_update):
            with patch("src.handlers.webhook.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []  # Allow all chats

                update_data = {"update_id": 123, "message": {"text": "/help"}}
                await handler.process_update(update_data)

                # Commands now use adapter.send_text instead of reply_text
                handler._telegram_adapter.send_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_unknown_command(self, handler):
        """Test processing unknown command."""
        mock_update = MagicMock()
        mock_update.callback_query = None
        mock_update.message = MagicMock()
        mock_update.message.text = "/unknown_command"
        mock_update.message.chat.id = 123456
        mock_update.message.message_id = 790
        mock_update.effective_chat = MagicMock()
        mock_update.effective_chat.id = 123456
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 456
        mock_update.effective_user.first_name = "TestUser"
        mock_update.effective_user.username = None

        with patch("telegram.Update.de_json", return_value=mock_update):
            with patch("src.handlers.webhook.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []  # Allow all chats
                update_data = {"update_id": 123, "message": {"text": "/unknown_command"}}
                await handler.process_update(update_data)
                # Unknown command calls adapter.send_text with the "unknown" translation
                handler._telegram_adapter.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_refresh_callback(self, handler):
        """Test processing refresh callback."""
        mock_update = MagicMock()
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.data = "refresh"
        mock_update.callback_query.message = MagicMock()
        mock_update.callback_query.message.chat.id = 123456
        mock_update.callback_query.message.message_id = 789
        mock_update.callback_query.from_user.id = 456
        mock_update.callback_query.from_user.first_name = "TestUser"
        mock_update.callback_query.from_user.username = None
        mock_update.effective_chat = MagicMock()
        mock_update.effective_chat.id = 123456
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 456
        mock_update.effective_user.first_name = "TestUser"
        mock_update.effective_user.username = None
        mock_update.message = None

        with patch("telegram.Update.de_json", return_value=mock_update):
            with patch("src.handlers.webhook.settings") as mock_settings:
                mock_settings.allowed_chat_ids = []  # Allow all chats
                with patch("src.handlers.commands.resume_command", new=AsyncMock()) as mock_refresh:
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


class TestHandleMessageTracksMessageId:
    """Test that _handle_message tracks message IDs and _handle_callback_query does not."""

    @pytest.fixture
    def handler(self):
        h = WebhookHandler()
        h.input_handler = MagicMock()
        h.input_handler.handle_button_press = AsyncMock()
        h._telegram_adapter = MagicMock()
        return h

    def _make_message_update(self, chat_id=123, message_id=999, text="/start"):
        update = MagicMock()
        update.callback_query = None
        update.message = MagicMock()
        update.message.chat.id = chat_id
        update.message.message_id = message_id
        update.message.text = text
        update.effective_chat = MagicMock()
        update.effective_chat.id = chat_id
        update.effective_user = MagicMock()
        update.effective_user.id = 1
        update.effective_user.first_name = "User"
        update.effective_user.username = "user"
        return update

    def _make_callback_update(self, chat_id=123, message_id=999):
        update = MagicMock()
        update.message = None
        update.callback_query = MagicMock()
        update.callback_query.data = "a"
        update.callback_query.message = MagicMock()
        update.callback_query.message.chat.id = chat_id
        update.callback_query.message.message_id = message_id
        update.callback_query.from_user = MagicMock()
        update.callback_query.from_user.id = 1
        update.callback_query.from_user.first_name = "User"
        update.callback_query.from_user.username = "user"
        return update

    @pytest.mark.asyncio
    async def test_handle_message_tracks_message_id(self, handler):
        """_handle_message calls update_latest_telegram_message_id."""
        update = self._make_message_update(chat_id=123, message_id=999, text="/unknown_cmd")
        with patch("src.handlers.webhook.state_manager") as mock_sm:
            mock_sm.get_or_create_chat_config = MagicMock(return_value=MagicMock(maintenance_mode=False))
            with patch("src.handlers.webhook.COMMAND_HANDLERS", {}):
                with patch("src.handlers.commands.unknown_command", new=AsyncMock()):
                    await handler._handle_message(update)
            mock_sm.update_latest_telegram_message_id.assert_called_once_with(123, 999)

    @pytest.mark.asyncio
    async def test_handle_callback_query_does_not_track_message_id(self, handler):
        """_handle_callback_query does NOT call update_latest_telegram_message_id."""
        update = self._make_callback_update(chat_id=123, message_id=999)
        with patch("src.handlers.webhook.state_manager") as mock_sm:
            mock_sm.get_or_create_chat_config = MagicMock(return_value=MagicMock(maintenance_mode=False))
            with patch("src.handlers.webhook.is_valid_button_callback", return_value=True):
                await handler._handle_callback_query(update)
            mock_sm.update_latest_telegram_message_id.assert_not_called()
