"""Async cleanup loop for recent_inputs table.

Runs daily at startup and then every 24 hours to purge rows
older than recent_inputs_max_retention_days. Skips purge when
the setting is 0 (retention disabled).
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_recent_inputs_cleanup_loop(db_manager, settings) -> None:
    """Async loop: purge old recent_inputs rows daily.

    Runs purge immediately on startup, then repeats every 24 hours.
    Skips purge when recent_inputs_max_retention_days is 0.

    Args:
        db_manager: DatabaseManager instance with purge_old_recent_inputs()
        settings: Settings proxy with recent_inputs_max_retention_days
    """
    # Run immediately on startup
    await _run_cleanup_cycle(db_manager, settings)

    while True:
        try:
            await asyncio.sleep(86400)  # 24 hours
            await _run_cleanup_cycle(db_manager, settings)
        except asyncio.CancelledError:
            logger.info("Recent inputs cleanup loop cancelled")
            raise
        except Exception:
            logger.exception("Error in recent inputs cleanup loop; will retry in 60s")
            await asyncio.sleep(60)


async def _run_cleanup_cycle(db_manager, settings) -> None:
    """Run one cleanup cycle: purge old recent_inputs rows."""
    retention_days = settings.recent_inputs_max_retention_days
    if retention_days == 0:
        logger.debug("Recent inputs cleanup skipped (retention_days=0)")
        return

    try:
        deleted = db_manager.purge_old_recent_inputs(retention_days)
        if deleted > 0:
            logger.info(f"Purged {deleted} old recent_inputs row(s) (older than {retention_days} days)")
        else:
            logger.debug(f"Recent inputs cleanup: no rows older than {retention_days} days")
    except Exception:
        logger.exception("Failed to purge old recent_inputs rows")
