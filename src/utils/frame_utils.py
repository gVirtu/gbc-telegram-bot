"""Frame processing utilities.

This module provides functions for processing GameBoy frame buffers,
including hashing for deduplication and conversion to PNG format.
"""

import hashlib
from io import BytesIO
from typing import Tuple

import numpy as np
from PIL import Image


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
    images = [Image.fromarray(frame, mode="RGB") for frame in frames]
    
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
