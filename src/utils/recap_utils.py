"""Utilities for sending recap videos to chats."""

import logging

logger = logging.getLogger(__name__)


async def send_recap_to_chat(
    chat_id: int,
    leader_id: int,
    date_str: str,
    adapter,
) -> bool:
    """Send a recap video for a given date to a chat.

    If the realtime_recaps feature flag is set and an rt video exists, sends
    that. Otherwise looks up the recap record, tries cached file_id first
    (Telegram only), falls back to disk upload, and updates cached file_id on
    successful upload.

    Args:
        chat_id: Target chat ID to send the recap to
        leader_id: Leader chat ID that owns the recap
        date_str: Date in YYYYMMDD format
        adapter: Platform adapter to use for sending

    Returns:
        True on success, False if no record/file or on any exception
    """
    from src.config import settings
    from src.utils.state_manager import state_manager

    video_path = settings.data_dir / "recaps" / str(leader_id) / f"recap_{date_str}.mp4"
    rt_video_path = settings.data_dir / "recaps" / str(leader_id) / f"recap_{date_str}_rt.mp4"

    leader_config = state_manager.get_or_create_chat_config(leader_id)
    use_rt = leader_config.feature_flags.get("realtime_recaps") and rt_video_path.exists()

    if use_rt:
        try:
            with open(rt_video_path, "rb") as video_file:
                await adapter.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=f"📅 Recap: {date_str}",
                )
            logger.info(f"Sent realtime recap for chat {chat_id} (leader {leader_id}), date {date_str}")
            return True
        except Exception as e:
            logger.error(f"Error sending realtime recap for chat {chat_id}, date {date_str}: {e}")
            return False

    recap_record = await state_manager.get_recap_file(leader_id, date_str)

    if recap_record is None:
        return False

    if not video_path.exists():
        return False

    try:
        # Try sending with cached file_id first (Telegram only)
        if recap_record.file_id and adapter.platform == "telegram":
            try:
                file_id = await adapter.send_video(
                    chat_id=chat_id,
                    video=recap_record.file_id,
                    caption=f"📅 Recap: {date_str}",
                )
                if file_id:
                    logger.info(f"Sent cached recap for chat {chat_id}, date {date_str}")
                    return True
            except Exception as e:
                logger.warning(f"Failed to send cached file_id, uploading from disk: {e}")

        # Upload from disk
        with open(video_path, "rb") as video_file:
            new_file_id = await adapter.send_video(
                chat_id=chat_id,
                video=video_file,
                caption=f"📅 Recap: {date_str}",
            )

        if new_file_id:
            await state_manager.update_recap_file_id(leader_id, date_str, new_file_id)
            logger.info(f"Uploaded and cached recap for chat {chat_id} (leader {leader_id}), date {date_str}")

        return True

    except Exception as e:
        logger.error(f"Error sending recap for chat {chat_id}, date {date_str}: {e}")
        return False
