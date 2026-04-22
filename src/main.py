"""Main entry point for the GBC Bot.

This module initializes the application, sets up logging,
and provides the ASGI application for running with uvicorn.

Both Telegram and Discord are supported simultaneously.
At least one of TELEGRAM_BOT_TOKEN or DISCORD_BOT_TOKEN must be set.

Usage:
    Development:
        python -m src.main

    Production:
        uvicorn src.main:app --host 0.0.0.0 --port 8000

Environment Variables:
    TELEGRAM_BOT_TOKEN: Bot token from @BotFather (required for Telegram)
    DISCORD_BOT_TOKEN: Bot token from Discord Developer Portal (required for Discord)
    WEBHOOK_URL: Public URL for Telegram webhook (required when Telegram is enabled)
    WEBHOOK_SECRET: Secret for webhook validation (required when Telegram is enabled)
    PORT: Server port (default: 8000)
    LOG_LEVEL: Logging level (default: INFO)
"""

import logging
import sys

from src.config import settings
from src.handlers.webhook import get_webhook_handler

# Configure logging
settings.setup_logging()
logger = logging.getLogger(__name__)

# Create the FastAPI application
handler = get_webhook_handler()
app = handler.create_app()

import src.game_shops

def setup_webhook() -> None:
    """Set up the Telegram webhook.

    This should be called once when deploying to production.
    Only applicable when TELEGRAM_BOT_TOKEN is configured.
    """
    if not settings.telegram_bot_token:
        logger.info("Telegram not configured, skipping webhook setup")
        return

    import asyncio
    from telegram import Bot

    async def _setup():
        bot = Bot(token=settings.telegram_bot_token.get_secret_value())
        webhook_url = f"{settings.webhook_url}{settings.get_webhook_path()}"

        try:
            await bot.set_webhook(
                url=webhook_url,
                secret_token=settings.webhook_secret,
            )
            logger.info(f"Webhook set successfully: {webhook_url}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")

    asyncio.run(_setup())


def delete_webhook() -> None:
    """Delete the Telegram webhook.

    Useful for switching to polling mode or cleaning up.
    Only applicable when TELEGRAM_BOT_TOKEN is configured.
    """
    if not settings.telegram_bot_token:
        logger.info("Telegram not configured, skipping webhook deletion")
        return

    import asyncio
    from telegram import Bot

    async def _delete():
        bot = Bot(token=settings.telegram_bot_token.get_secret_value())

        try:
            await bot.delete_webhook()
            logger.info("Webhook deleted successfully")
        except Exception as e:
            logger.error(f"Failed to delete webhook: {e}")
        finally:
            await bot.session.close()

    asyncio.run(_delete())


def main():
    """Main entry point for running the bot."""
    import uvicorn

    # Validate configuration
    try:
        has_telegram = bool(settings.telegram_bot_token)
        has_discord = bool(settings.discord_bot_token)

        if not has_telegram and not has_discord:
            logger.error("Configuration error: At least one of TELEGRAM_BOT_TOKEN or DISCORD_BOT_TOKEN must be set")
            sys.exit(1)

        if has_telegram:
            logger.info("Telegram platform: enabled")
            logger.info(f"Webhook URL: {settings.webhook_url}{settings.get_webhook_path()}")
        if has_discord:
            logger.info("Discord platform: enabled")

        logger.info("Configuration validated successfully")
    except Exception as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    logger.info(f"Starting bot on port {settings.port}")
    logger.info(f"Log level: {settings.log_level}")

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
