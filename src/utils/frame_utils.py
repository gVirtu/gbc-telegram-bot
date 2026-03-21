"""Frame processing utilities.

This module provides functions for processing GameBoy frame buffers,
including hashing for deduplication and conversion to PNG format.
"""

import hashlib
import logging
import os
import subprocess
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

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
    image = Image.fromarray(frame).resize(
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


def render_input_sidebar(
    inputs: list,
    width: int = 192,
    height: int = 288,
) -> np.ndarray:
    """Render a sidebar showing recent input entries as a numpy RGB array.

    Text is rendered white on black, right-aligned, bottom-up.
    Each entry shows: "{user_name}: {button_char}"
    Button chars: ← ↑ → ↓ A B START SELECT (WAIT shown as …)

    Args:
        inputs: List of dicts with keys: user_name, button (string value)
        width: Width of the sidebar in pixels
        height: Height of the sidebar in pixels

    Returns:
        np.ndarray of shape (height, width, 3), uint8, black background
    """
    BUTTON_CHARS = {
        "left": "⬅",
        "up": "⬆",
        "right": "⮕",
        "down": "⬇",
        "a": "Ⓐ",
        "b": "Ⓑ",
        "start": "START",
        "select": "SELECT",
        "wait": "…",
    }

    img = Image.new("RGB", (width, height), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Try to load bundled font; fall back to default
    font = None
    font_path = Path(__file__).parent.parent.parent / "assets" / "fonts" / "unifont-17.0.04.otf"
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(font_path), size=18)
    except Exception:
        from PIL import ImageFont
        font = ImageFont.load_default()

    line_height = 20
    padding = 4
    y = height - line_height - padding  # start from bottom

    # Render inputs bottom-up (most recent at bottom)
    for entry in reversed(inputs):
        if y < line_height:
            break  # Stop when we reach the top boundary

        button_val = entry.get("button", "")
        button_char = BUTTON_CHARS.get(button_val, button_val)
        user_name = entry.get("user_name", "?")
        text = f"{user_name}: {button_char}"

        # Right-align: measure text width
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
        except Exception:
            text_w = len(text) * 6

        x = width - text_w - padding
        draw.text((x, y), text, fill=(255, 255, 255), font=font, fontmode="1")
        y -= line_height

    date_str = datetime.utcnow().strftime("%d/%m/%Y")
    draw.text((padding, 0), date_str, fill=(255, 255, 255), font=font, fontmode="1")

    return np.array(img, dtype=np.uint8)


def composite_overlay(
    game_frame: np.ndarray,
    sidebar: np.ndarray,
) -> np.ndarray:
    """Composite game frame and sidebar into a single wide frame.

    Horizontally stacks game_frame (left) and sidebar (right).
    If heights differ, pads shorter side with black.

    Args:
        game_frame: np.ndarray of shape (H, W, 3)
        sidebar: np.ndarray of shape (H, W2, 3)

    Returns:
        np.ndarray of shape (H, W+W2, 3)
    """
    h1, w1 = game_frame.shape[:2]
    h2, w2 = sidebar.shape[:2]

    if h1 == h2:
        return np.concatenate([game_frame, sidebar], axis=1)

    # Pad to same height
    max_h = max(h1, h2)
    if h1 < max_h:
        pad = np.zeros((max_h - h1, w1, 3), dtype=np.uint8)
        game_frame = np.concatenate([game_frame, pad], axis=0)
    if h2 < max_h:
        pad = np.zeros((max_h - h2, w2, 3), dtype=np.uint8)
        sidebar = np.concatenate([sidebar, pad], axis=0)

    return np.concatenate([game_frame, sidebar], axis=1)


def _make_frame_transform(
    pre_existing: list,
    new_inputs_with_offsets: list,
) -> Callable[[np.ndarray], np.ndarray]:
    """Build a stateful per-frame transform that composites the input sidebar.

    Returns a callable that, when called once per frame in sequence, composites
    an input sidebar reflecting accumulated inputs up to that frame.

    Args:
        pre_existing: Input dicts already visible at frame 0.
        new_inputs_with_offsets: List of (input_dict, frame_offset) pairs.

    Returns:
        A callable ``transform(frame) -> composited_frame``.
    """
    state: dict = {"frame_index": 0, "current_inputs": list(pre_existing)}
    sorted_new = sorted(new_inputs_with_offsets, key=lambda x: x[1])
    sorted_new_iter = iter(sorted_new)
    next_item = next(sorted_new_iter, None)

    def transform(frame: np.ndarray) -> np.ndarray:
        nonlocal next_item
        fi = state["frame_index"]
        state["frame_index"] += 1

        while next_item is not None and next_item[1] <= fi:
            state["current_inputs"].append(next_item[0])
            next_item = next(sorted_new_iter, None)

        sidebar = render_input_sidebar(state["current_inputs"])
        return composite_overlay(frame, sidebar)

    return transform


def apply_overlay_composite(
    frames: list[np.ndarray],
    pre_existing_inputs: list,
    new_inputs_with_offsets: list,
) -> list[np.ndarray]:
    """Composite the input sidebar onto a sequence of already-2x-scaled frames.

    Applies a stateful per-frame transform that adds new inputs to the sidebar
    at the specified frame offsets.

    Args:
        frames: List of 2x-scaled numpy arrays (H, W, 3). Must be pre-scaled;
            no internal scaling is applied.
        pre_existing_inputs: Input dicts visible from frame 0.
        new_inputs_with_offsets: List of (input_dict, frame_offset) pairs.

    Returns:
        List of composited frames, each wider by the sidebar width (H, W+192, 3).
    """
    transform = _make_frame_transform(pre_existing_inputs, new_inputs_with_offsets)
    return [transform(f) for f in frames]


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
            '-an',
            '-f', 'rawvideo',
            '-pix_fmt', 'rgb24',
            '-s', f'{w_scaled}x{h_scaled}',
            '-framerate', str(fps),
            '-i', 'pipe:0',
            '-vcodec', 'libx264',
            '-profile:v', 'baseline',
            '-pix_fmt', 'yuv420p',
            '-crf', str(crf),
            '-preset', preset,
            '-movflags', '+faststart+frag_keyframe+empty_moov',
            output_path,
        ]
        
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        for frame in frames:
            img = Image.fromarray(frame).resize(
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


def save_frames_as_avif(
    frames: list[np.ndarray],
    fps: int = 10,
) -> BytesIO:
    """Save frames as an animated AVIF using Pillow.

    Scales 2x (same as save_frames_as_mp4) using nearest-neighbor resampling.

    Args:
        frames: List of NumPy arrays (H, W, 3) in RGB format
        fps: Frames per second (converted to ms duration per frame)

    Returns:
        BytesIO object containing AVIF data, seeked to 0

    Raises:
        ValueError: If no frames provided
    """
    if not frames:
        raise ValueError("No frames provided")

    h, w = frames[0].shape[:2]
    h_scaled, w_scaled = h * 2, w * 2
    duration_ms = int(1000 / fps)

    pil_frames = [
        Image.fromarray(frame)
        .resize((w_scaled, h_scaled), Image.Resampling.NEAREST)
        for frame in frames
    ]

    buffer = BytesIO()
    pil_frames[0].save(
        buffer,
        format="AVIF",
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )
    buffer.seek(0)
    return buffer


async def save_frames_as_mp4_optimized(
    frames: list[np.ndarray],
    output_path: str,
    fps: int = 10,
    crf: int = 28,
    preset: str = "medium",
    frame_transform: Optional[Callable[[np.ndarray], np.ndarray]] = None,
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
        frame_transform: Optional callable to transform each frame before encoding.
            Applied before 2x scaling; changes pixel content but not the scaling step.

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

    # Apply transform to get actual frame dimensions
    if frame_transform:
        first_frame = frame_transform(frames[0])
    else:
        first_frame = frames[0]
    h, w = first_frame.shape[:2]

    cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo',
        '-pix_fmt', 'rgb24',
        '-s', f'{w}x{h}',
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

    # Write frames to stdin; reuse already-transformed first_frame to avoid
    # calling frame_transform twice on frames[0] (important for stateful transforms)
    frames_to_encode = [first_frame] + [
        frame_transform(f) if frame_transform else f for f in frames[1:]
    ]
    for actual_frame in frames_to_encode:
        img = Image.fromarray(actual_frame)
        process.stdin.write(np.array(img).tobytes())

    process.stdin.close()

    # Wait for process to complete
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        logger.error(f"FFmpeg encoding failed: {stderr.decode()}")
        raise RuntimeError(f"FFmpeg encoding failed with return code {process.returncode}")

    logger.debug(f"Encoded {len(frames)} frames to {output_path}")


async def save_frames_as_mp4_with_audio(
    frames: list[np.ndarray],
    audio_chunks: list[np.ndarray],
    output_path: str,
    fps: int = 15,
    crf: int = 28,
    preset: str = "medium",
    sample_rate: int = 48000,
    frame_transform: Optional[Callable[[np.ndarray], np.ndarray]] = None,
) -> None:
    """Save frames as MP4 with audio using FFmpeg.

    Encodes video frames (via stdin pipe) and audio (from PCM file) into
    a single MP4 with AAC audio track. Designed for realtime recap videos.

    Args:
        frames: List of NumPy arrays (H, W, 3) in RGB format
        audio_chunks: List of int8 ndarrays with shape (N, 2) - stereo audio
        output_path: Path where to save the MP4 file
        fps: Frames per second for the output video
        crf: Constant Rate Factor (quality, lower=better, 0-51)
        preset: Encoding speed preset
        sample_rate: Audio sample rate in Hz
        frame_transform: Optional callable to transform each frame before encoding.
            Applied before 2x scaling; changes pixel content but not the scaling step.

    Raises:
        ValueError: If no frames provided
        RuntimeError: If FFmpeg encoding fails
    """
    import asyncio

    if not frames:
        raise ValueError("No frames provided")

    # Apply transform to get actual frame dimensions
    if frame_transform:
        first_frame = frame_transform(frames[0])
    else:
        first_frame = frames[0]
    h, w = first_frame.shape[:2]

    # Convert int8 stereo chunks to int16 PCM and write to temp file
    tmp_pcm = None
    try:
        if audio_chunks:
            # Concatenate all audio chunks and convert int8 -> int16
            combined = np.concatenate(audio_chunks, axis=0)  # shape (N, 2)
            # Scale to int16 range and add triangular PDF dither to reduce
            # quantization noise from the 8-bit source (lower 8 bits are
            # otherwise always zero, causing audible stepping artifacts).
            pcm_int16 = combined.astype(np.int16) << 8

            dither = (
                np.random.randint(-128, 129, pcm_int16.shape, dtype=np.int16)
                + np.random.randint(-128, 129, pcm_int16.shape, dtype=np.int16)
            ) // 2

            pcm_int16 = np.clip(pcm_int16 + dither, -32768, 32767)

            with tempfile.NamedTemporaryFile(suffix='.pcm', delete=False) as f:
                tmp_pcm = f.name
                f.write(pcm_int16.tobytes())

        if tmp_pcm:
            cmd = [
                'ffmpeg', '-y',
                '-f', 'rawvideo',
                '-pix_fmt', 'rgb24',
                '-s', f'{w}x{h}',
                '-framerate', str(fps),
                '-i', 'pipe:0',
                '-f', 's16le',
                '-ar', str(sample_rate),
                '-ac', '2',
                '-i', tmp_pcm,
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-crf', str(crf),
                '-af', 'highpass=f=40,lowpass=f=6500,aresample=32000',
                '-preset', preset,
                '-c:a', 'aac',
                output_path,
            ]
        else:
            cmd = [
                'ffmpeg', '-y',
                '-f', 'rawvideo',
                '-pix_fmt', 'rgb24',
                '-s', f'{w}x{h}',
                '-framerate', str(fps),
                '-i', 'pipe:0',
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-crf', str(crf),
                '-preset', preset,
                '-an',
                output_path,
            ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Write frames to stdin; reuse already-transformed first_frame to avoid
        # calling frame_transform twice on frames[0] (important for stateful transforms)
        frames_to_encode = [first_frame] + [
            frame_transform(f) if frame_transform else f for f in frames[1:]
        ]
        for actual_frame in frames_to_encode:
            img = Image.fromarray(actual_frame)
            process.stdin.write(np.array(img).tobytes())

        process.stdin.close()
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"FFmpeg encoding failed: {stderr.decode()}")
            raise RuntimeError(f"FFmpeg encoding failed with return code {process.returncode}")

        logger.debug(f"Encoded {len(frames)} frames with audio to {output_path}")

    finally:
        if tmp_pcm and os.path.exists(tmp_pcm):
            os.remove(tmp_pcm)


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

            frame_image = Image.fromarray(base_frame)
            frame_image.paste(overlay, (x, y), overlay)

            frame = np.array(frame_image)
            frames.append(frame)

    except Exception as e:
        logger.error(f"Error generating TBC frames: {e}")
        return []

    return frames
