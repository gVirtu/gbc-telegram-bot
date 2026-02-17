"""Webhook handler for Telegram bot.

This module implements FastAPI routes for receiving and processing
Telegram webhook updates, including callback queries and commands.
"""

import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from telegram import Update
from telegram.ext import Application

from src.config import settings
from src.handlers.commands import COMMAND_HANDLERS
from src.handlers.input_handler import get_input_handler
from src.keyboard import is_valid_button_callback

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Handles Telegram webhook updates via FastAPI.
    
    This class sets up FastAPI routes for:
    - Receiving webhook updates from Telegram
    - Validating webhook requests
    - Routing callbacks to input handler
    - Routing commands to command handlers
    
    Example:
        >>> handler = WebhookHandler()
        >>> app = handler.create_app()
        >>> # Run with uvicorn: uvicorn main:app --host 0.0.0.0 --port 8000
    """
    
    def __init__(self):
        """Initialize the webhook handler."""
        self.telegram_app: Optional[Application] = None
        self.input_handler = None
    
    def _validate_webhook_path(self, path: str) -> bool:
        """Validate that the webhook path matches our secret hash.
        
        Args:
            path: The URL path from the request
            
        Returns:
            True if valid, False otherwise
        """
        expected_path = settings.get_webhook_path()
        return path == expected_path
    
    def _validate_webhook_hash(self, hash: str) -> bool:
        """Validate webhook hash.
        
        Args:
            hash: The hash to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            expected_hash = settings.get_webhook_hash()
            # Use constant-time comparison to prevent timing attacks
            return hashlib.sha256(str(hash).encode()).hexdigest() == \
                   hashlib.sha256(str(expected_hash).encode()).hexdigest()
        except Exception:
            return False
    
    def _validate_telegram_secret(self, token: str) -> bool:
        """Validate Telegram bot token.
        
        Args:
            token: The token to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            expected_secret = settings.webhook_secret
            # Use constant-time comparison to prevent timing attacks
            return hashlib.sha256(str(token).encode()).hexdigest() == \
                   hashlib.sha256(str(expected_secret).encode()).hexdigest()
        except Exception:
            return False
    
    async def _handle_callback_query(self, update: Update) -> None:
        """Handle callback query (button press).
        
        Args:
            update: Telegram Update object
        """
        callback_query = update.callback_query
        
        if not callback_query:
            return
        
        callback_data = callback_query.data
        
        # Check if it's a game button
        if is_valid_button_callback(callback_data):
            await self.input_handler.handle_button_press(callback_query)
        elif callback_data == "refresh":
            # Handle refresh request
            from src.handlers.commands import resume_command
            await resume_command(update, callback_query)
        elif callback_data == "help":
            # Handle help request
            from src.handlers.commands import help_command
            await help_command(update, callback_query)
        elif callback_data.startswith("load_slot_"):
            # Handle slot selection for loading
            try:
                slot = int(callback_data.split("_")[-1])
                from src.handlers.commands import load_command
                # Mock context with slot argument
                class MockContext:
                    args = [str(slot)]
                    bot = callback_query.bot
                await load_command(update, MockContext())
            except (ValueError, IndexError):
                logger.warning(f"Invalid load_slot callback: {callback_data}")
        elif callback_data == "cancel_load":
            # Handle cancel load
            await callback_query.message.edit_text("Load cancelled.")
        else:
            logger.debug(f"Unhandled callback: {callback_data}")
    
    async def _handle_message(self, update: Update) -> None:
        """Handle incoming message (commands).
        
        Args:
            update: Telegram Update object
        """
        message = update.message
        
        if not message or not message.text:
            return
        
        text = message.text
        
        # Check if it's a command
        if text.startswith("/"):
            # Extract command name
            command = text[1:].split()[0].split("@")[0]  # Remove @botname if present
            
            if command in COMMAND_HANDLERS:
                handler = COMMAND_HANDLERS[command]
                
                # Extract arguments
                args = text.split()[1:] if len(text.split()) > 1 else []
                
                # Create context with args - use the bot from telegram_app
                class Context:
                    def __init__(self, bot, args):
                        self.bot = bot
                        self.args = args
                
                context = Context(self.telegram_app.bot, args)
                await handler(update, context)
            else:
                # Unknown command
                from src.handlers.commands import unknown_command
                await unknown_command(update, None)
    
    def _get_chat_id(self, update: Update) -> int | None:
        """Extract chat ID from an update.
        
        Args:
            update: Telegram Update object
            
        Returns:
            Chat ID or None if not found
        """
        if update.callback_query and update.callback_query.message:
            return update.callback_query.message.chat.id
        elif update.message:
            return update.message.chat.id
        return None
    
    def _is_chat_allowed(self, chat_id: int) -> bool:
        """Check if a chat is allowed to interact with the bot.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            True if allowed, False otherwise
        """
        if not settings.allowed_chat_ids:
            return True
        return chat_id in settings.allowed_chat_ids
    
    async def process_update(self, update_data: dict) -> None:
        """Process a Telegram update.
        
        Args:
            update_data: Raw update data from Telegram
        """
        try:
            update = Update.de_json(update_data, self.telegram_app.bot)
            
            chat_id = self._get_chat_id(update)
            if chat_id is None:
                logger.warning("Could not extract chat ID from update")
                return
            
            if not self._is_chat_allowed(chat_id):
                logger.debug(f"Ignored update from unauthorized chat {chat_id}")
                return
            
            if update.callback_query:
                await self._handle_callback_query(update)
            elif update.message:
                await self._handle_message(update)
            else:
                logger.debug(f"Unhandled update type: {update.to_dict()}")
        
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            raise
    
    def create_app(self) -> FastAPI:
        """Create and configure FastAPI application.
        
        Returns:
            Configured FastAPI app
        """
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            """Manage application lifespan."""
            # Startup
            logger.info("Starting up webhook handler...")
            
            # Initialize database (runs migrations)
            from src.db.migrations.runner import MigrationError
            try:
                from src.db.manager import DatabaseManager
                db_manager = DatabaseManager()
                db_manager.initialize()
                logger.info("Database initialized with migrations")
            except MigrationError as e:
                logger.error(f"Failed to run database migrations: {e}")
                raise
            
            # Initialize rate limiter
            from src.utils.rate_limiter import init_rate_limiter
            init_rate_limiter(
                max_per_chat=settings.rate_limit_per_chat,
                per_chat_window=settings.rate_limit_per_chat_window,
                max_global=settings.rate_limit_global,
                global_window=settings.rate_limit_global_window,
            )
            
            # Initialize Telegram application
            from telegram.ext import ApplicationBuilder
            
            self.telegram_app = (
                ApplicationBuilder()
                .token(settings.telegram_bot_token.get_secret_value())
                .build()
            )
            
            # Initialize rate-limited bot wrapper
            from src.utils.telegram_client import RateLimitedBot
            rate_limited_bot = RateLimitedBot(self.telegram_app.bot)
            
            # Initialize input handler with rate-limited bot
            self.input_handler = get_input_handler(rate_limited_bot)

            # Start daily backup task
            from src.tasks.backup_task import run_backup_loop
            from src.utils.backup_manager import BackupManager
            from src.utils.state_manager import state_manager
            from src.game import game_controller_manager

            backup_manager = BackupManager(state_manager, game_controller_manager, settings)
            backup_task = asyncio.create_task(run_backup_loop(backup_manager, settings))

            logger.info("Webhook handler started successfully")

            yield

            # Shutdown
            logger.info("Shutting down webhook handler...")

            backup_task.cancel()
            try:
                await backup_task
            except asyncio.CancelledError:
                pass

            if self.telegram_app:
                await self.telegram_app.shutdown()

            logger.info("Webhook handler shut down")
        
        app = FastAPI(
            title="GBC Bot",
            description="Telegram bot for collaborative GBC gameplay",
            version="1.0.0",
            lifespan=lifespan,
        )
        
        @app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "service": "gbc-telegram-bot",
            }
        
        @app.post(settings.get_webhook_path())
        async def webhook(request: Request):
            """Handle incoming webhook updates."""
            try:
                # Parse update data
                update_data = await request.json()
                logger.debug(f"Received update: {update_data}")
                
                # Process the update
                await self.process_update(update_data)
                
                return JSONResponse(
                    content={"status": "ok"},
                    status_code=status.HTTP_200_OK,
                )
            
            except Exception as e:
                logger.error(f"Error in webhook: {e}")
                return JSONResponse(
                    content={"status": "error", "message": str(e)},
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        
        @app.post("/webhook/{hash}")
        async def webhook_with_token(hash: str, request: Request):
            """Handle webhook with token in path (alternative endpoint)."""
            if not self._validate_webhook_hash(hash) or not self._validate_telegram_secret(request.headers.get("X-Telegram-Bot-Api-Secret-Token")):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token",
                )
            
            try:
                update_data = await request.json()
                await self.process_update(update_data)
                
                return JSONResponse(
                    content={"status": "ok"},
                    status_code=status.HTTP_200_OK,
                )
            
            except Exception as e:
                logger.error(f"Error in webhook: {e}")
                return JSONResponse(
                    content={"status": "error", "message": str(e)},
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        
        return app


# Singleton instance
_webhook_handler: Optional[WebhookHandler] = None


def get_webhook_handler() -> WebhookHandler:
    """Get or create the singleton WebhookHandler instance.
    
    Returns:
        WebhookHandler instance
    """
    global _webhook_handler
    if _webhook_handler is None:
        _webhook_handler = WebhookHandler()
    return _webhook_handler
