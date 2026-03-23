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

from src.adapters.base import CommandContext, register_adapter
from src.config import settings
from src.game import game_controller_manager
from src.handlers.commands import COMMAND_HANDLERS, check_admin_permission
from src.handlers.input_handler import get_input_handler
from src.keyboard import is_valid_button_callback
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)


def _build_telegram_command_context(
    update: Update,
    args: list[str],
    telegram_adapter,
) -> CommandContext:
    """Build a CommandContext from a Telegram Update.

    Args:
        update: Telegram Update object
        args: Parsed command arguments
        telegram_adapter: TelegramAdapter instance

    Returns:
        CommandContext for the command handler
    """
    chat_id = (
        update.effective_chat.id
        if update.effective_chat
        else (update.callback_query.message.chat.id if update.callback_query else 0)
    )
    user = update.effective_user
    user_id = user.id if user else 0
    user_name = (
        user.first_name or
        (f"@{user.username}" if user and user.username else "User")
    ) if user else "User"

    return CommandContext(
        chat_id=chat_id,
        user_id=user_id,
        user_name=user_name,
        args=args,
        adapter=telegram_adapter,
        raw=update,
    )


class WebhookHandler:
    """Handles Telegram webhook updates via FastAPI."""

    def __init__(self):
        """Initialize the webhook handler."""
        self.telegram_app: Optional[Application] = None
        self.input_handler = None
        self._telegram_adapter = None

    def _validate_webhook_hash(self, hash: str) -> bool:
        """Validate webhook hash."""
        try:
            expected_hash = settings.get_webhook_hash()
            # Use constant-time comparison to prevent timing attacks
            return hashlib.sha256(str(hash).encode()).hexdigest() == \
                   hashlib.sha256(str(expected_hash).encode()).hexdigest()
        except Exception:
            return False

    def _validate_telegram_secret(self, token: str) -> bool:
        """Validate Telegram bot token."""
        try:
            expected_secret = settings.webhook_secret
            # Use constant-time comparison to prevent timing attacks
            return hashlib.sha256(str(token).encode()).hexdigest() == \
                   hashlib.sha256(str(expected_secret).encode()).hexdigest()
        except Exception:
            return False

    def _validate_webhook_path(self, path: str) -> bool:
        """Validate that the webhook path matches our secret hash."""
        try:
            expected_path = settings.get_webhook_path()
            return path == expected_path
        except Exception:
            return False

    async def _handle_callback_query(self, update: Update) -> None:
        """Handle callback query (button press)."""
        callback_query = update.callback_query

        if not callback_query:
            return

        callback_data = callback_query.data
        chat_id = self._get_chat_id(update)
        message_id = callback_query.message.message_id if callback_query.message else None

        if callback_data.startswith("modifier_") or is_valid_button_callback(callback_data):
            user_id = callback_query.from_user.id
            user_name = (
                callback_query.from_user.first_name or
                (f"@{callback_query.from_user.username}" if callback_query.from_user.username else "User")
            )

            config = state_manager.get_or_create_chat_config(chat_id)

            if config.maintenance_mode and is_valid_button_callback(callback_data):
                # Check if user is admin
                ctx = _build_telegram_command_context(update, [], self._telegram_adapter)
                is_allowed, _ = await check_admin_permission(ctx)
                if not is_allowed:
                    await callback_query.answer(
                        "No momento estamos em manutenção, apenas admins podem enviar comandos."
                    )
                    return

            await self.input_handler.handle_button_press(
                callback_data=callback_data,
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_name=user_name,
                adapter=self._telegram_adapter,
                raw=callback_query,
            )
        elif callback_data == "refresh":
            ctx = _build_telegram_command_context(update, [], self._telegram_adapter)
            from src.handlers.commands import resume_command
            await resume_command(ctx)
        elif callback_data == "help":
            ctx = _build_telegram_command_context(update, [], self._telegram_adapter)
            from src.handlers.commands import help_command
            await help_command(ctx)
        elif callback_data.startswith("load_slot_"):
            try:
                slot = int(callback_data.split("_")[-1])
                ctx = _build_telegram_command_context(update, [str(slot)], self._telegram_adapter)
                from src.handlers.commands import load_command
                await load_command(ctx)
            except (ValueError, IndexError):
                logger.warning(f"Invalid load_slot callback: {callback_data}")
        elif callback_data == "cancel_load":
            await callback_query.message.edit_text("Load cancelled.")
        elif (
            callback_data.startswith("shop_page_")
            or callback_data.startswith("shop_buy_")
            or callback_data.startswith("shop_cat_")
            or callback_data.startswith("shop_back_")
        ):
            await self._handle_shop_callback(update, callback_data)
        else:
            logger.debug(f"Unhandled callback: {callback_data}")

    async def _handle_shop_callback(self, update: "Update", callback_data: str) -> None:
        """Handle shop navigation, category, and purchase callbacks."""
        from src.handlers.commands import _build_shop_keyboard
        from src.shop.shop_manager import shop_manager as _sm, build_shop_text
        from src.i18n import translation_manager

        callback_query = update.callback_query
        user_id = callback_query.from_user.id
        user_name = (
            callback_query.from_user.first_name or
            (f"@{callback_query.from_user.username}" if callback_query.from_user.username else "User")
        )
        platform = "telegram"

        if callback_data.startswith("shop_page_"):
            # Outer category listing navigation: shop_page_{source_chat_id}_{page}
            rest = callback_data.removeprefix("shop_page_")
            source_chat_id_str, page_str = rest.split("_", 1)
            try:
                source_chat_id = int(source_chat_id_str)
                page = int(page_str)
            except ValueError:
                return
            balance = _sm.get_balance(platform, user_id)
            total_pages = 1
            text = build_shop_text(balance, None, page, total_pages, source_chat_id)
            keyboard = _build_shop_keyboard(source_chat_id, source_chat_id, page, total_pages, [], category=None)
            await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
            await callback_query.answer()

        elif callback_data.startswith("shop_cat_"):
            # Enter/navigate within a category: shop_cat_{source_chat_id}_{cat_id}_{page}
            rest = callback_data.removeprefix("shop_cat_")
            # source_chat_id is first numeric segment; cat_id may contain underscores; page is last
            parts = rest.split("_")
            if len(parts) < 3:
                return
            try:
                source_chat_id = int(parts[0])
                page = int(parts[-1])
            except ValueError:
                return
            cat_id = "_".join(parts[1:-1])
            category = _sm.get_category(cat_id)
            if category is None:
                return
            items, total_pages = _sm.get_category_page(cat_id, page)
            balance = _sm.get_balance(platform, user_id)
            text = build_shop_text(balance, category, page, total_pages, source_chat_id)
            keyboard = _build_shop_keyboard(source_chat_id, source_chat_id, page, total_pages, items, category=category)
            await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
            await callback_query.answer()

        elif callback_data.startswith("shop_back_"):
            # Return to category listing: shop_back_{source_chat_id}
            source_chat_id_str = callback_data.removeprefix("shop_back_")
            try:
                source_chat_id = int(source_chat_id_str)
            except ValueError:
                return
            balance = _sm.get_balance(platform, user_id)
            total_pages = 1
            text = build_shop_text(balance, None, 0, total_pages, source_chat_id)
            keyboard = _build_shop_keyboard(source_chat_id, source_chat_id, 0, total_pages, [], category=None)
            await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
            await callback_query.answer()

        elif callback_data.startswith("shop_buy_"):
            # Purchase: shop_buy_{source_chat_id}_{item_id}
            rest = callback_data.removeprefix("shop_buy_")
            source_chat_id_str, item_id = rest.split("_", 1)
            try:
                source_chat_id = int(source_chat_id_str)
            except ValueError:
                return
            result = _sm.purchase(platform, user_id, item_id, chat_id=source_chat_id, user_name=user_name)
            balance = _sm.get_balance(platform, user_id)
            total_pages = 1
            if result.success:
                item_name = translation_manager.get(result.item.name_i18n_key, source_chat_id)
                status = translation_manager.get(
                    "shop.purchase_success", source_chat_id, item_name=item_name
                )
            else:
                if result.item:
                    status = translation_manager.get(
                        "shop.insufficient_funds", source_chat_id,
                        cost=f"{result.item.cost:,}", balance=f"{balance:,}"
                    )
                else:
                    status = translation_manager.get(
                        "shop.insufficient_funds", source_chat_id,
                        cost="?", balance=f"{balance:,}"
                    )
            # Return to outer category listing after purchase
            text = build_shop_text(balance, None, 0, total_pages, source_chat_id, status_message=status)
            keyboard = _build_shop_keyboard(source_chat_id, source_chat_id, 0, total_pages, [], category=None)
            await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
            await callback_query.answer()

    async def _handle_message(self, update: Update) -> None:
        """Handle incoming message (commands)."""
        message = update.message

        if not message or not message.text:
            return

        text = message.text

        if text.startswith("/"):
            # Extract command name
            command = text[1:].split()[0].split("@")[0]  # Remove @botname if present
            
            if command in COMMAND_HANDLERS:
                handler = COMMAND_HANDLERS[command]
                
                # Extract arguments
                args = text.split()[1:] if len(text.split()) > 1 else []
                ctx = _build_telegram_command_context(update, args, self._telegram_adapter)
                await handler(ctx)
            else:
                ctx = _build_telegram_command_context(update, [], self._telegram_adapter)
                from src.handlers.commands import unknown_command
                await unknown_command(ctx)

    def _get_chat_id(self, update: Update) -> int | None:
        """Extract chat ID from an update."""
        if update.callback_query and update.callback_query.message:
            return update.callback_query.message.chat.id
        elif update.message:
            return update.message.chat.id
        return None

    def _is_chat_allowed(self, chat_id: int) -> bool:
        """Check if a chat is allowed to interact with the bot."""
        if not settings.allowed_chat_ids:
            return True
        return chat_id in settings.allowed_chat_ids

    def _is_shop_related_update(self, update: Update) -> bool:
        """Return True only for shop-related messages/callbacks (exempt from allowlist in private chats)."""
        if update.message and update.message.text:
            text = update.message.text.strip()
            if text.startswith("/start shop_"):
                return True
            command = text[1:].split()[0].split("@")[0] if text.startswith("/") else ""
            if command == "shop":
                return True
        if update.callback_query and update.callback_query.data:
            data = update.callback_query.data
            if any(data.startswith(p) for p in ("shop_page_", "shop_buy_", "shop_cat_", "shop_back_")):
                return True
        return False

    async def process_update(self, update_data: dict) -> None:
        """Process a Telegram update."""
        try:
            update = Update.de_json(update_data, self.telegram_app.bot)

            chat_id = self._get_chat_id(update)
            if chat_id is None:
                logger.warning("Could not extract chat ID from update")
                return

            is_private = (
                (update.message and update.message.chat.type == "private")
                or (
                    update.callback_query
                    and update.callback_query.message
                    and update.callback_query.message.chat.type == "private"
                )
            )
            # Shop deep-links/callbacks in private chats bypass the allowlist
            if not (is_private and self._is_shop_related_update(update)):
                if not self._is_chat_allowed(chat_id):
                    logger.warning(f"Ignored update from unauthorized chat {chat_id}")
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
        """Create and configure FastAPI application."""
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            """Manage application lifespan."""
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

            discord_task = None

            # Initialize Telegram if configured
            if settings.telegram_bot_token:
                from telegram.ext import ApplicationBuilder
                from src.utils.telegram_client import RateLimitedBot
                from src.adapters.telegram import TelegramAdapter

                self.telegram_app = (
                    ApplicationBuilder()
                    .token(settings.telegram_bot_token.get_secret_value())
                    .build()
                )

                rate_limited_bot = RateLimitedBot(self.telegram_app.bot)
                self._telegram_adapter = TelegramAdapter(rate_limited_bot)
                register_adapter("telegram", self._telegram_adapter)

                bot_info = await self.telegram_app.bot.get_me()
                import src.config as _cfg
                _cfg.telegram_bot_username = bot_info.username
                logger.info(f"Telegram bot username: {bot_info.username}")

                logger.info("Telegram adapter initialized")

            # Initialize Discord if configured
            if settings.discord_bot_token:
                from src.handlers.discord_handler import create_discord_bot
                discord_bot = create_discord_bot()
                discord_task = asyncio.create_task(
                    discord_bot.start(settings.discord_bot_token.get_secret_value())
                )
                logger.info("Discord bot task started")

            # Initialize input handler (platform-agnostic)
            self.input_handler = get_input_handler()

            # Initialize timelapse encoding queue
            from src.tasks import timelapse_encoder

            timelapse_encoder.timelapse_queue = timelapse_encoder.TimelapseEncodingQueue(state_manager)
            logger.info("Timelapse encoding queue initialized")

            # Start daily backup task
            from src.tasks.backup_task import run_backup_loop
            from src.utils.backup_manager import BackupManager

            backup_manager = BackupManager(state_manager, game_controller_manager, settings)
            backup_task = asyncio.create_task(run_backup_loop(backup_manager, settings))

            from src.tasks.recap_broadcaster import run_recap_broadcast_loop
            recap_task = asyncio.create_task(run_recap_broadcast_loop())

            from src.tasks.recent_inputs_cleanup_task import run_recent_inputs_cleanup_loop
            recent_inputs_cleanup_task = asyncio.create_task(
                run_recent_inputs_cleanup_loop(state_manager, settings)
            )

            logger.info("Webhook handler started successfully")

            yield

            # Shutdown
            logger.info("Shutting down webhook handler...")

            if timelapse_encoder.timelapse_queue:
                await timelapse_encoder.timelapse_queue.shutdown()

            backup_task.cancel()
            try:
                await backup_task
            except asyncio.CancelledError:
                pass

            recap_task.cancel()
            try:
                await recap_task
            except asyncio.CancelledError:
                pass

            recent_inputs_cleanup_task.cancel()
            try:
                await recent_inputs_cleanup_task
            except asyncio.CancelledError:
                pass

            if discord_task and not discord_task.done():
                discord_task.cancel()
                try:
                    await discord_task
                except (asyncio.CancelledError, Exception):
                    pass

            if self.telegram_app:
                await self.telegram_app.shutdown()

            game_controller_manager.stop_all()

            logger.info("Webhook handler shut down")

        app = FastAPI(
            title="GBC Bot",
            description="Telegram/Discord bot for collaborative GBC gameplay",
            version="1.0.0",
            lifespan=lifespan,
        )

        @app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "service": "gbc-bot",
            }

        # Only register Telegram webhook endpoints if telegram is configured
        if settings.telegram_bot_token:
            try:
                webhook_path = settings.get_webhook_path()

                @app.post(f"/{webhook_path}")
                async def webhook(request: Request):
                    """Handle incoming webhook updates."""
                    try:
                        update_data = await request.json()
                        logger.debug(f"Received update: {update_data}")
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

            except Exception:
                pass  # webhook_secret may not be set (Discord-only mode)

        @app.post("/webhook/{hash}")
        async def webhook_with_token(hash: str, request: Request):
            """Handle webhook with token in path (alternative endpoint)."""
            if not settings.telegram_bot_token:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Telegram webhook not configured",
                )
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
    """Get or create the singleton WebhookHandler instance."""
    global _webhook_handler
    if _webhook_handler is None:
        _webhook_handler = WebhookHandler()
    return _webhook_handler
