"""Local media cache for animations."""

import logging
import wave
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np

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


def save_last_audio(chat_id: int, audio_chunks: list, sample_rate: int = 48000) -> None:
    """Save captured audio chunks as a 16-bit stereo WAV file.

    Args:
        chat_id: The chat ID
        audio_chunks: List of per-tick int8 numpy arrays of shape (N, 2)
        sample_rate: Audio sample rate in Hz (default: 48000)
    """
    if not audio_chunks:
        return
    cache_dir = get_media_cache_dir(chat_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_path = cache_dir / "last_audio.wav"

    # Concatenate all per-tick chunks: shape (total_samples, 2), dtype int8
    samples = np.concatenate(audio_chunks, axis=0)
    # Convert signed int8 (-128..127) to signed int16 (-32768..32512)
    samples_16 = samples.astype(np.int16) * 256
    # Flatten to interleaved [L, R, L, R, ...] bytes for WAV
    raw_bytes = samples_16.tobytes()

    with wave.open(str(file_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)        # 2 bytes = 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(raw_bytes)

    logger.debug(f"Saved last audio to {file_path}")


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
