"""Main entry point for the Telegram GBC Bot.

This module initializes the application, sets up logging,
and provides the ASGI application for running with uvicorn.

Usage:
    Development:
        python -m src.main
    
    Production:
        uvicorn src.main:app --host 0.0.0.0 --port 8000
        
Environment Variables:
    TELEGRAM_BOT_TOKEN: Bot token from @BotFather (required)
    WEBHOOK_URL: Public URL for webhook (required)
    WEBHOOK_SECRET: Secret for webhook validation (required)
    PORT: Server port (default: 8000)
    LOG_LEVEL: Logging level (default: INFO)
"""

import logging
import sys
from contextlib import asynccontextmanager

from src.config import settings
from src.handlers.webhook import get_webhook_handler

# Configure logging
settings.setup_logging()
logger = logging.getLogger(__name__)

# Create the FastAPI application
handler = get_webhook_handler()
app = handler.create_app()


def setup_webhook() -> None:
    """Set up the Telegram webhook.
    
    This should be called once when deploying to production.
    In development, you may want to use polling instead.
    """
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
        finally:
            await bot.session.close()
    
    asyncio.run(_setup())


def delete_webhook() -> None:
    """Delete the Telegram webhook.
    
    Useful for switching to polling mode or cleaning up.
    """
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
        # This will trigger validation
        _ = settings.telegram_bot_token
        _ = settings.webhook_url
        _ = settings.webhook_secret
        logger.info("Configuration validated successfully")
    except Exception as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Please check your .env file and ensure all required variables are set:")
        logger.error("  - TELEGRAM_BOT_TOKEN")
        logger.error("  - WEBHOOK_URL")
        logger.error("  - WEBHOOK_SECRET")
        sys.exit(1)
    
    # Log startup info
    logger.info(f"Starting bot on port {settings.port}")
    logger.info(f"Webhook URL: {settings.webhook_url}{settings.get_webhook_path()}")
    logger.info(f"Log level: {settings.log_level}")
    
    # Run the server
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,  # Set to True for development
    )


if __name__ == "__main__":
    main()
