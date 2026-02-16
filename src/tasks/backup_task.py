"""Async backup loop task.

Runs daily backups at the configured UTC time. On startup, runs a cycle
immediately so any chat that missed today's backup gets one right away.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from src.utils.backup_manager import BackupManager

logger = logging.getLogger(__name__)


async def run_backup_loop(backup_manager: BackupManager, settings) -> None:
    """Async loop: run backups at configured UTC time, then once per day.

    On startup runs a cycle immediately, then sleeps until the next
    configured time before repeating.
    """
    # Startup cycle: back up any active chats that lack today's backup
    await _run_backup_cycle(backup_manager)

    while True:
        try:
            now = datetime.utcnow()
            next_run = now.replace(
                hour=settings.backup_hour,
                minute=settings.backup_minute,
                second=0,
                microsecond=0,
            )
            if next_run <= now:
                next_run += timedelta(days=1)
            sleep_seconds = (next_run - now).total_seconds()
            logger.debug(f"Next backup cycle in {sleep_seconds:.0f}s at {next_run.isoformat()}Z")
            await asyncio.sleep(sleep_seconds)
            await _run_backup_cycle(backup_manager)
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
