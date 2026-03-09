"""Local media cache for animations."""

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

from src.config import settings

logger = logging.getLogger(__name__)


def get_media_cache_dir(chat_id: int) -> Path:
    """Get the media cache directory for a chat."""
    return settings.data_dir / "media" / str(chat_id)


def save_last_animation(chat_id: int, media_buffer: BytesIO, media_type: str = "animation") -> None:
    """Save the last animation to local cache.
    
    Args:
        chat_id: The chat ID
        media_buffer: The media bytes buffer
        media_type: "animation" for mp4, "avif" for avif
    """
    cache_dir = get_media_cache_dir(chat_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    ext = "avif" if media_type == "avif" else "mp4"
    file_path = cache_dir / f"last_animation.{ext}"
    
    media_buffer.seek(0)
    file_path.write_bytes(media_buffer.read())
    
    logger.debug(f"Saved last animation to {file_path}")


def load_last_animation(chat_id: int, media_type: str = "animation") -> Optional[BytesIO]:
    """Load the last animation from local cache.
    
    Args:
        chat_id: The chat ID
        media_type: "animation" for mp4, "avif" for avif
        
    Returns:
        BytesIO with the media content, or None if not found
    """
    ext = "avif" if media_type == "avif" else "mp4"
    file_path = get_media_cache_dir(chat_id) / f"last_animation.{ext}"
    
    if not file_path.exists():
        return None
    
    return BytesIO(file_path.read_bytes())
