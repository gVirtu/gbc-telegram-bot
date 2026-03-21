"""Async recap broadcast loop task.

Sends daily recap videos to all leader chats with auto_send_recaps enabled,
plus their non-media-only mirror chats.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from src.adapters.base import get_adapter
from src.config import settings
from src.handlers.input_handler import get_input_handler
from src.utils.mirror_utils import is_media_only_mirror
from src.utils.recap_utils import send_recap_to_chat
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)


async def run_recap_broadcast_loop() -> None:
    """Async loop: broadcast recaps at 00:00 UTC daily."""
    while True:
        try:
            now = datetime.utcnow()
            next_run = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            sleep_seconds = (next_run - now).total_seconds()
            logger.debug(f"Next recap broadcast in {sleep_seconds:.0f}s at {next_run.isoformat()}Z")
            await asyncio.sleep(sleep_seconds)
            await _run_broadcast_cycle()
        except asyncio.CancelledError:
            logger.info("Recap broadcast loop cancelled")
            raise
        except Exception:
            logger.exception("Error in recap broadcast loop; will retry in 60s")
            await asyncio.sleep(60)


async def _run_broadcast_cycle() -> None:
    """Run one broadcast cycle: send yesterday's recap to all opted-in chats."""
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")
    leader_ids = state_manager.get_leaders_with_flag("auto_send_recaps")
    logger.info(f"Recap broadcast cycle: {len(leader_ids)} opted-in leader(s) for date {yesterday}")

    for leader_id in leader_ids:
        video_path = settings.data_dir / "recaps" / str(leader_id) / f"recap_{yesterday}.mp4"
        rt_video_path = settings.data_dir / "recaps" / str(leader_id) / f"recap_{yesterday}_rt.mp4"

        if not video_path.exists() and not rt_video_path.exists():
            logger.debug(f"No recap file for leader {leader_id}, date {yesterday}; skipping")
            continue

        mirror_ids = state_manager.get_mirror_chat_ids(leader_id)
        recipients = [leader_id] + [m for m in mirror_ids if not is_media_only_mirror(m)]

        for chat_id in recipients:
            config = state_manager.get_or_create_chat_config(chat_id)
            adapter = get_adapter(config.platform)
            if adapter is None:
                logger.warning(f"No adapter for platform '{config.platform}' (chat {chat_id}); skipping")
                continue

            success = await send_recap_to_chat(chat_id, leader_id, yesterday, adapter)
            if success:
                try:
                    await get_input_handler().resume_game(chat_id, adapter)
                except Exception:
                    logger.exception(f"Failed to resume game for chat {chat_id} after recap broadcast")
            else:
                logger.warning(f"Failed to send recap to chat {chat_id} (leader {leader_id}), date {yesterday}")
