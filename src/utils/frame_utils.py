"""Frame processing utilities.

This module provides functions for processing GameBoy frame buffers,
including hashing for deduplication and conversion to PNG format.
"""

import hashlib
import logging
import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Tuple

import ffmpeg
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def hash_frame(frame: np.ndarray) -> str:
    """Create a SHA256 hash of a frame buffer for deduplication.
    
    This function creates a deterministic hash of the frame data that can
    be used to quickly check if a frame has changed since the last update.
    
    Args:
        frame: NumPy array representing the frame (H x W x 3 for RGB)
        
    Returns:
        Hexadecimal string of the SHA256 hash (64 characters)
        
    Example:
        >>> frame = np.zeros((144, 160, 3), dtype=np.uint8)
        >>> hash_frame(frame)
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    """
    # Convert to bytes and hash
    return hashlib.sha256(frame.tobytes()).hexdigest()


def frame_to_png(frame: np.ndarray, optimize: bool = True) -> BytesIO:
    """Convert a numpy frame buffer to PNG bytes.
    
    Args:
        frame: NumPy array with shape (height, width, 3) in RGB format
        optimize: Whether to optimize PNG compression (default: True)
        
    Returns:
        BytesIO object containing PNG image data
        
    Raises:
        ValueError: If frame is not a valid numpy array or has wrong shape
        
    Example:
        >>> frame = np.random.randint(0, 256, (144, 160, 3), dtype=np.uint8)
        >>> png_buffer = frame_to_png(frame)
        >>> len(png_buffer.getvalue()) > 0
        True
    """
    if not isinstance(frame, np.ndarray):
        raise ValueError(f"Expected numpy array, got {type(frame)}")
    
    if len(frame.shape) != 3 or frame.shape[2] != 3:
        raise ValueError(
            f"Expected frame shape (H, W, 3), got {frame.shape}"
        )
    
    # Create PIL Image from numpy array
    image = Image.fromarray(frame, mode="RGB")
    
    # Save to bytes buffer
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=optimize)
    buffer.seek(0)
    
    return buffer


def frames_equal(frame1: np.ndarray, frame2: np.ndarray) -> bool:
    """Check if two frames are identical.
    
    This is faster than hashing for quick equality checks when you have
    both frames in memory.
    
    Args:
        frame1: First frame array
        frame2: Second frame array
        
    Returns:
        True if frames are identical, False otherwise
        
    Example:
        >>> frame1 = np.zeros((144, 160, 3), dtype=np.uint8)
        >>> frame2 = np.zeros((144, 160, 3), dtype=np.uint8)
        >>> frames_equal(frame1, frame2)
        True
    """
    if frame1.shape != frame2.shape:
        return False
    
    return np.array_equal(frame1, frame2)


def get_frame_info(frame: np.ndarray) -> Tuple[int, int, str]:
    """Get information about a frame.
    
    Args:
        frame: NumPy array representing the frame
        
    Returns:
        Tuple of (height, width, dtype)
        
    Example:
        >>> frame = np.zeros((144, 160, 3), dtype=np.uint8)
        >>> get_frame_info(frame)
        (144, 160, 'uint8')
    """
    return frame.shape[0], frame.shape[1], str(frame.dtype)


def create_empty_frame(
    width: int = 160,
    height: int = 144,
    color: Tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    """Create an empty frame filled with a solid color.
    
    Useful for testing and creating placeholder frames.
    
    Args:
        width: Frame width in pixels (default: 160 for GameBoy)
        height: Frame height in pixels (default: 144 for GameBoy)
        color: RGB color tuple (default: white)
        
    Returns:
        NumPy array filled with the specified color
        
    Example:
        >>> frame = create_empty_frame(color=(255, 0, 0))  # Red frame
        >>> frame.shape
        (144, 160, 3)
        >>> frame[0, 0]
        array([255,   0,   0], dtype=uint8)
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = color
    return frame


def should_update_frame(
    current_frame: np.ndarray,
    last_hash: str | None,
) -> Tuple[bool, str]:
    """Determine if a frame should be sent based on hash comparison.
    
    This is the main optimization function to avoid sending duplicate frames.
    
    Args:
        current_frame: The current frame buffer
        last_hash: The hash of the last sent frame (None if no previous frame)
        
    Returns:
        Tuple of (should_update, current_hash)
        - should_update: True if frame has changed and should be sent
        - current_hash: Hash of current frame (save this for next comparison)
        
    Example:
        >>> frame1 = create_empty_frame(color=(255, 0, 0))
        >>> should_update, hash1 = should_update_frame(frame1, None)
        >>> should_update
        True
        >>> frame2 = create_empty_frame(color=(255, 0, 0))
        >>> should_update, hash2 = should_update_frame(frame2, hash1)
        >>> should_update
        False
        >>> hash1 == hash2
        True
    """
    current_hash = hash_frame(current_frame)
    
    if last_hash is None:
        # No previous frame, should update
        return True, current_hash
    
    if current_hash == last_hash:
        # Frame unchanged, skip update
        return False, current_hash
    
    # Frame changed, should update
    return True, current_hash


def save_frames_as_gif(
    frames: list[np.ndarray],
    duration: int = 100,
    last_frame_duration: int = 2000,
    optimize: bool = True,
) -> BytesIO:
    """Save a sequence of frames as an animated GIF.
    
    DEPRECATED: Use save_frames_as_mp4 instead for better compression.
    
    Args:
        frames: List of NumPy arrays (H, W, 3)
        duration: Duration of each frame in milliseconds
        last_frame_duration: Duration of the last frame in milliseconds
        optimize: Whether to optimize GIF size
        
    Returns:
        BytesIO object containing GIF data
        
    Example:
        >>> frames = [create_empty_frame() for _ in range(5)]
        >>> gif_buffer = save_frames_as_gif(frames)
        >>> len(gif_buffer.getvalue()) > 0
        True
    """
    if not frames:
        raise ValueError("No frames provided")
        
    # Convert numpy frames to PIL Images
    images = [
        Image.fromarray(frame, mode="RGB").resize(
            (frame.shape[1] * 2, frame.shape[0] * 2), Image.Resampling.NEAREST
        )
        for frame in frames
    ]
    
    # Calculate durations
    durations = [duration] * len(frames)
    if frames:
        durations[-1] = last_frame_duration
        
    buffer = BytesIO()
    # Save as GIF
    images[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=optimize,
    )
    buffer.seek(0)
    
    return buffer


def save_frames_as_mp4(
    frames: list[np.ndarray],
    fps: int = 10,
    crf: int = 28,
    preset: str = "ultrafast",
) -> BytesIO:
    """Save a sequence of frames as an MP4 video using FFmpeg.
    
    Args:
        frames: List of NumPy arrays (H, W, 3) in RGB format
        fps: Frames per second for the output video
        crf: Constant Rate Factor (quality, lower=better, 0-51)
        preset: Encoding speed preset (ultrafast to veryslow)
        
    Returns:
        BytesIO object containing MP4 data
        
    Raises:
        ValueError: If no frames provided
        RuntimeError: If FFmpeg encoding fails
        
    Example:
        >>> frames = [create_empty_frame() for _ in range(5)]
        >>> mp4_buffer = save_frames_as_mp4(frames)
        >>> len(mp4_buffer.getvalue()) > 0
        True
    """
    if not frames:
        raise ValueError("No frames provided")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save frames as PNG files
        for i, frame in enumerate(frames):
            # Upscale 2x for better quality (matches GIF behavior)
            image = Image.fromarray(frame, mode="RGB").resize(
                (frame.shape[1] * 2, frame.shape[0] * 2), Image.Resampling.NEAREST
            )
            frame_path = os.path.join(temp_dir, f"frame_{i:04d}.png")
            image.save(frame_path, format="PNG")
        
        # Output MP4 path
        output_path = os.path.join(temp_dir, "output.mp4")
        
        try:
            # Run FFmpeg to create MP4
            (
                ffmpeg
                .input(os.path.join(temp_dir, "frame_%04d.png"), framerate=fps)
                .output(
                    output_path,
                    vcodec="libx264",
                    pix_fmt="yuv420p",
                    crf=crf,
                    preset=preset,
                    movflags="faststart",
                )
                .overwrite_output()
                .run(quiet=True)
            )
            
            # Read the output file into BytesIO
            with open(output_path, "rb") as f:
                buffer = BytesIO(f.read())
            
            buffer.seek(0)
            return buffer
            
        except ffmpeg.Error as e:
            logger.error(f"FFmpeg encoding failed: {e}")
            raise RuntimeError(f"Failed to encode MP4: {e}")


def generate_tbc_frames(
    base_frame: np.ndarray,
    duration_frames: int = 20,
    overlay_path: Path = Path("./assets/to_be_continued.png"),
    max_width_percent: float = 0.7,
) -> list[np.ndarray]:
    """Generate "To Be Continued" padding frames.

    Creates a sequence where the overlay slides in from the right side
    of the screen, ending at the bottom-right corner.

    Args:
        base_frame: The final game frame to use as background
        duration_frames: Number of frames to generate
        overlay_path: Path to the "to_be_continued.png" asset
        max_width_percent: Maximum width of overlay as percentage of frame width

    Returns:
        List of numpy arrays representing the animation frames
    """
    frames = []

    if not overlay_path.exists():
        logger.warning(f"TBC overlay not found at {overlay_path}")
        return frames

    try:
        overlay = Image.open(overlay_path).convert("RGBA")
        frame_width = base_frame.shape[1]
        frame_height = base_frame.shape[0]

        target_width = int(frame_width * max_width_percent)
        aspect_ratio = overlay.height / overlay.width
        target_height = int(target_width * aspect_ratio)

        overlay = overlay.resize((target_width, target_height), Image.Resampling.NEAREST)

        start_x = frame_width
        end_x = frame_width - target_width
        end_y = frame_height - target_height

        for i in range(duration_frames):
            t = i / (duration_frames - 1) if duration_frames > 1 else 1.0
            progress = 1 - (1 - t) ** 2
            
            x = int(start_x + (end_x - start_x) * progress)
            y = end_y

            frame_image = Image.fromarray(base_frame, mode="RGB")
            frame_image.paste(overlay, (x, y), overlay)

            frame = np.array(frame_image)
            frames.append(frame)

    except Exception as e:
        logger.error(f"Error generating TBC frames: {e}")
        return []

    return frames
