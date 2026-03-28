"""Utilities for sending recap videos to chats."""

import asyncio
import logging

from src.adapters.base import get_adapter
from src.config import settings
from src.utils.mirror_utils import is_media_only_mirror
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)


def get_input_handler():
    """Lazy import wrapper to avoid circular imports."""
    from src.handlers.input_handler import get_input_handler as _get
    return _get()


async def send_recap_to_chat(
    chat_id: int,
    leader_id: int,
    date_str: str,
    adapter,
    parts_to_send=None,
) -> bool:
    """Send recap video parts for a given date to a chat.

    Fetches all parts for the recap to determine file paths and captions. If
    ``parts_to_send`` is provided, only those parts are sent; otherwise all parts
    are sent in order with a delay between them.

    Args:
        chat_id: Target chat ID to send the recap to
        leader_id: Leader chat ID that owns the recap
        date_str: Date in YYYYMMDD format
        adapter: Platform adapter to use for sending
        parts_to_send: Optional pre-filtered list of RecapFileRecord to send.
            When None, all parts are sent (default).

    Returns:
        True if at least one part was sent, False otherwise
    """
    leader_config = state_manager.get_or_create_chat_config(leader_id)
    is_rt = leader_config.feature_flags.get("realtime_recaps", False)

    all_parts = await state_manager.get_recap_parts(leader_id, date_str, is_rt)

    if not all_parts:
        return False

    effective_parts = parts_to_send if parts_to_send is not None else all_parts

    if not effective_parts:
        return False

    max_part_number = max(p.part_number for p in all_parts)
    total_count = len(all_parts)

    sent_any = False
    for i, part in enumerate(effective_parts):
        is_last_in_batch = (i == len(effective_parts) - 1)
        is_last_overall = (part.part_number == max_part_number)
        suffix = "_rt" if is_rt else ""
        if is_last_overall:
            file_path = settings.data_dir / "recaps" / str(leader_id) / f"recap_{date_str}{suffix}.mp4"
        else:
            file_path = settings.data_dir / "recaps" / str(leader_id) / f"recap_{date_str}_part{part.part_number}{suffix}.mp4"

        if not file_path.exists():
            logger.warning(f"Recap part {part.part_number} missing on disk for chat {leader_id}, skipping")
            if not is_last_in_batch:
                await asyncio.sleep(settings.recap_part_send_delay_seconds)
            continue

        try:
            if part.file_id and adapter.platform == "telegram":
                try:
                    file_id = await adapter.send_video(
                        chat_id=chat_id,
                        video=part.file_id,
                        caption=f"📅 Recap of {date_str} ({part.part_number} of {total_count})",
                    )
                    if file_id:
                        sent_any = True
                        if not is_last_in_batch:
                            await asyncio.sleep(settings.recap_part_send_delay_seconds)
                        continue
                except Exception as e:
                    logger.warning(f"Failed to send cached file_id for part {part.part_number}, uploading from disk: {e}")

            with open(file_path, "rb") as f:
                new_file_id = await adapter.send_video(
                    chat_id=chat_id,
                    video=f,
                    caption=f"📅 Recap of {date_str} (part {part.part_number} of {total_count})",
                )
            if new_file_id:
                await state_manager.update_recap_file_id(
                    leader_id, date_str, part.part_number, is_rt, new_file_id
                )
            sent_any = True

        except Exception as e:
            logger.error(f"Error sending recap part {part.part_number} for chat {leader_id}: {e}")

        if not is_last_in_batch:
            await asyncio.sleep(settings.recap_part_send_delay_seconds)

    return sent_any


async def auto_send_split_recap_part(
    leader_id: int,
    date_str: str,
    part_number: int,
    is_rt: bool,
) -> None:
    """Auto-send a finalized split recap part to leader + non-media-only mirrors.

    Called when TimelapseEncoder finalizes a part during a split. Checks the
    auto_send_recaps feature flag, sends the specific finalized part to all
    recipients, resumes the game for successful sends, and marks auto_sent_at
    on the part record once at least one send succeeded.

    Args:
        leader_id: Leader chat ID that owns the recap files
        date_str: Date in YYYYMMDD format
        part_number: The part number that was just finalized (split out)
        is_rt: Whether this is a realtime recap
    """
    leader_config = state_manager.get_or_create_chat_config(leader_id)
    if not leader_config.feature_flags.get("auto_send_recaps", False):
        return

    all_parts = await state_manager.get_recap_parts(leader_id, date_str, is_rt)
    target_parts = [p for p in all_parts if p.part_number == part_number]

    if not target_parts:
        logger.warning(
            f"No DB record for part {part_number} of leader {leader_id} on {date_str}; skipping auto-send"
        )
        return

    mirror_ids = state_manager.get_mirror_chat_ids(leader_id)
    recipients = [leader_id] + [m for m in mirror_ids if not is_media_only_mirror(m)]

    any_sent = False
    for chat_id in recipients:
        config = state_manager.get_or_create_chat_config(chat_id)
        adapter = get_adapter(config.platform)
        if adapter is None:
            logger.warning(
                f"No adapter for platform '{config.platform}' (chat {chat_id}); skipping split auto-send"
            )
            continue

        success = await send_recap_to_chat(
            chat_id, leader_id, date_str, adapter, parts_to_send=target_parts
        )
        if success:
            any_sent = True
            try:
                await get_input_handler().resume_game(chat_id, adapter)
            except Exception:
                logger.exception(
                    f"Failed to resume game for chat {chat_id} after split recap auto-send"
                )
        else:
            logger.warning(
                f"Failed to auto-send split recap part {part_number} to chat {chat_id} (leader {leader_id})"
            )

    if any_sent:
        await state_manager.mark_recap_part_auto_sent(leader_id, date_str, part_number, is_rt)
