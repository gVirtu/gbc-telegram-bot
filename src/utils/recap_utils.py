"""Utilities for sending recap videos to chats."""

import asyncio
import logging

from src.config import settings
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)


async def send_recap_to_chat(
    chat_id: int,
    leader_id: int,
    date_str: str,
    adapter,
) -> bool:
    """Send a recap video for a given date to a chat.

    Fetches all parts for the recap (RT or regular based on feature flag),
    sends them in order with a delay between parts, and caches file_ids on
    successful upload (Telegram only).

    Args:
        chat_id: Target chat ID to send the recap to
        leader_id: Leader chat ID that owns the recap
        date_str: Date in YYYYMMDD format
        adapter: Platform adapter to use for sending

    Returns:
        True if at least one part was sent, False otherwise
    """
    leader_config = state_manager.get_or_create_chat_config(leader_id)
    is_rt = leader_config.feature_flags.get("realtime_recaps", False)

    parts = await state_manager.get_recap_parts(leader_id, date_str, is_rt)

    if not parts:
        return False

    sent_any = False
    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        suffix = "_rt" if is_rt else ""
        if is_last:
            file_path = settings.data_dir / "recaps" / str(leader_id) / f"recap_{date_str}{suffix}.mp4"
        else:
            file_path = settings.data_dir / "recaps" / str(leader_id) / f"recap_{date_str}_part{part.part_number}{suffix}.mp4"

        if not file_path.exists():
            logger.warning(f"Recap part {part.part_number} missing on disk for chat {leader_id}, skipping")
            if not is_last:
                await asyncio.sleep(settings.recap_part_send_delay_seconds)
            continue

        try:
            if part.file_id and adapter.platform == "telegram":
                try:
                    file_id = await adapter.send_video(
                        chat_id=chat_id,
                        video=part.file_id,
                        caption=f"📅 Recap of {date_str} ({part.part_number} of {len(parts)})",
                    )
                    if file_id:
                        sent_any = True
                        if not is_last:
                            await asyncio.sleep(settings.recap_part_send_delay_seconds)
                        continue
                except Exception as e:
                    logger.warning(f"Failed to send cached file_id for part {part.part_number}, uploading from disk: {e}")

            with open(file_path, "rb") as f:
                new_file_id = await adapter.send_video(
                    chat_id=chat_id,
                    video=f,
                    caption=f"📅 Recap of {date_str} (part {part.part_number} of {len(parts)})",
                )
            if new_file_id:
                await state_manager.update_recap_file_id(
                    leader_id, date_str, part.part_number, is_rt, new_file_id
                )
            sent_any = True

        except Exception as e:
            logger.error(f"Error sending recap part {part.part_number} for chat {leader_id}: {e}")

        if not is_last:
            await asyncio.sleep(settings.recap_part_send_delay_seconds)

    return sent_any
