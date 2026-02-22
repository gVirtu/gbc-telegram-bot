"""Frame processing utilities.

This module provides functions for processing GameBoy frame buffers,
including hashing for deduplication and conversion to PNG format.
"""

import hashlib
import logging
import os
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Tuple

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
    image = Image.fromarray(frame, mode="RGB").resize(
            (frame.shape[1] * 2, frame.shape[0] * 2), Image.Resampling.NEAREST
        )
    
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


def save_frames_as_mp4(
    frames: list[np.ndarray],
    fps: int = 10,
    crf: int = 28,
    preset: str = "ultrafast",
) -> BytesIO:
    """Save a sequence of frames as an MP4 video using FFmpeg rawvideo piping.
    
    Uses stdin to pipe frames directly to ffmpeg (no intermediate PNG files),
    then writes output to a temp file and reads into BytesIO.
    
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
    
    h, w = frames[0].shape[:2]
    h_scaled, w_scaled = h * 2, w * 2
    
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_out:
        output_path = tmp_out.name
    
    try:
        cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo',
            '-pix_fmt', 'rgb24',
            '-s', f'{w_scaled}x{h_scaled}',
            '-framerate', str(fps),
            '-i', 'pipe:0',
            '-vcodec', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-crf', str(crf),
            '-preset', preset,
            '-movflags', 'faststart',
            output_path,
        ]
        
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        for frame in frames:
            img = Image.fromarray(frame, mode='RGB').resize(
                (w_scaled, h_scaled), Image.Resampling.NEAREST
            )
            process.stdin.write(np.array(img).tobytes())
        
        process.stdin.close()
        
        process.wait()
        return_code = process.returncode
        
        if return_code != 0:
            stderr = process.stderr.read().decode() if process.stderr else ""
            logger.error(f"FFmpeg encoding failed: {stderr}")
            raise RuntimeError(f"FFmpeg encoding failed with return code {return_code}")
        
        with open(output_path, 'rb') as f:
            buffer = BytesIO(f.read())
        
        buffer.seek(0)
        return buffer
        
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


async def save_frames_as_mp4_optimized(
    frames: list[np.ndarray],
    output_path: str,
    fps: int = 10,
    crf: int = 28,
    preset: str = "medium",
) -> None:
    """Save a sequence of frames as an MP4 video with optimized compression.

    This function is designed for timelapse storage where better compression
    is preferred over encoding speed. Uses medium preset and CRF 28 for
    smaller file sizes compared to save_frames_as_mp4.

    Args:
        frames: List of NumPy arrays (H, W, 3) in RGB format
        output_path: Path where to save the MP4 file
        fps: Frames per second for the output video
        crf: Constant Rate Factor (quality, lower=better, 0-51)
        preset: Encoding speed preset (medium for balanced compression)

    Raises:
        ValueError: If no frames provided
        RuntimeError: If FFmpeg encoding fails

    Example:
        >>> frames = [create_empty_frame() for _ in range(5)]
        >>> await save_frames_as_mp4_optimized(frames, "/tmp/output.mp4")
    """
    import asyncio

    if not frames:
        raise ValueError("No frames provided")

    h, w = frames[0].shape[:2]
    h_scaled, w_scaled = h * 2, w * 2

    cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo',
        '-pix_fmt', 'rgb24',
        '-s', f'{w_scaled}x{h_scaled}',
        '-framerate', str(fps),
        '-i', 'pipe:0',
        '-vcodec', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-crf', str(crf),
        '-preset', preset,
        output_path,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Write frames to stdin
    for frame in frames:
        img = Image.fromarray(frame, mode='RGB').resize(
            (w_scaled, h_scaled), Image.Resampling.NEAREST
        )
        process.stdin.write(np.array(img).tobytes())

    process.stdin.close()

    # Wait for process to complete
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        logger.error(f"FFmpeg encoding failed: {stderr.decode()}")
        raise RuntimeError(f"FFmpeg encoding failed with return code {process.returncode}")

    logger.debug(f"Encoded {len(frames)} frames to {output_path}")


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
