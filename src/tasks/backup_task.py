"""Async backup loop task.

Runs hourly backups at the top of each hour. On startup, sleeps until the next
top-of-hour before beginning the regular loop. create_backup() handles per-chat
noop logic internally (skips if no activity in the past 60 minutes).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from src.utils.backup_manager import BackupManager

logger = logging.getLogger(__name__)


async def run_backup_loop(backup_manager: BackupManager, settings) -> None:
    """Async loop: run backups at the top of each hour.

    On startup, sleeps until the next top-of-hour, then loops every 3600s.
    """
    # Startup: sleep until next top-of-hour
    now = datetime.now(timezone.utc)
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    sleep_seconds = (next_hour - now).total_seconds()
    logger.debug(f"First backup cycle in {sleep_seconds:.0f}s at {next_hour.isoformat()}Z")

    try:
        await asyncio.sleep(sleep_seconds)
    except asyncio.CancelledError:
        logger.info("Backup loop cancelled during startup sleep")
        raise

    while True:
        try:
            await _run_backup_cycle(backup_manager)
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            logger.info("Backup loop cancelled")
            raise
        except Exception:
            logger.exception("Error in backup loop; will retry in 60s")
            await asyncio.sleep(60)


async def _run_backup_cycle(backup_manager: BackupManager) -> None:
    """Run one backup cycle: find active chats, create backups, purge old ones."""
    chat_ids = await backup_manager.get_active_chat_ids()
    logger.info(f"Backup cycle: {len(chat_ids)} active chat(s)")
    for chat_id in chat_ids:
        try:
            success = await backup_manager.create_backup(chat_id)
            if success:
                deleted = backup_manager.purge_old_backups(chat_id)
                if deleted:
                    logger.info(f"Purged {deleted} old backup(s) for chat {chat_id}")
        except Exception:
            logger.exception(f"Backup failed for chat {chat_id}; skipping")
