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
from typing import Callable, Iterable, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

_streak_icon_cache: dict[int, Optional[Image.Image]] = {}


def _load_streak_icon(height_px: int) -> Optional[Image.Image]:
    if height_px not in _streak_icon_cache:
        path = Path(__file__).parent.parent.parent / "assets" / "streak_icon.png"
        if not path.exists():
            _streak_icon_cache[height_px] = None
        else:
            icon = Image.open(path).convert("RGBA")
            aspect = icon.width / icon.height
            new_w = max(1, int(height_px * aspect))
            _streak_icon_cache[height_px] = icon.resize((new_w, height_px), Image.Resampling.LANCZOS)
    return _streak_icon_cache[height_px]


def _paste_streak_icon(img: Image.Image, x: int, y: int, icon: Optional[Image.Image]) -> None:
    if icon is None:
        return
    bg = Image.new("RGBA", icon.size, (0, 0, 0, 255))
    composited = Image.alpha_composite(bg, icon).convert("RGB")
    img.paste(composited, (x, y))


def _draw_streak_badge(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    cx: int,
    y: int,
    streak_pre: str,
    streak_pre_w: int,
    streak_icon: Optional[Image.Image],
    streak_icon_y_offset: int,
    streak_icon_w: int,
    streak_post: str,
    streak_post_w: int,
    font,
) -> int:
    """Draw the streak badge (pre-text, icon, post-text) starting at cx. Returns new cx."""
    draw.text((cx, y), streak_pre, fill=(236, 138, 140), font=font, fontmode="1")
    cx += streak_pre_w
    _paste_streak_icon(img, cx, y + streak_icon_y_offset, streak_icon)
    cx += streak_icon_w
    draw.text((cx, y), streak_post, fill=(236, 138, 140), font=font, fontmode="1")
    cx += streak_post_w
    return cx


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a hex color string to an RGB tuple.

    Args:
        hex_color: Hex color string, with or without leading '#'.

    Returns:
        (r, g, b) tuple with values 0-255.
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r, g, b


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


def _draw_colored_username(
    img: "Image.Image",
    draw: "ImageDraw.ImageDraw",
    x: int,
    y: int,
    name: str,
    color: tuple,
    max_w: int,
    line_height: int,
    font,
) -> int:
    """Draw a username with color, compressing horizontally if too wide.

    Returns the actual pixel width used (≤ max_w).
    """
    try:
        bbox = draw.textbbox((0, 0), name, font=font)
        natural_w = bbox[2] - bbox[0]
    except Exception:
        natural_w = len(name) * 6

    if natural_w > max_w and natural_w > 0:
        tmp = Image.new("RGB", (natural_w, line_height), (0, 0, 0))
        ImageDraw.Draw(tmp).text((0, 0), name, fill=color, font=font, fontmode="1")
        tmp = tmp.resize((max_w, line_height), Image.Resampling.LANCZOS)
        img.paste(tmp, (x, y))
        return max_w
    else:
        draw.text((x, y), name, fill=color, font=font, fontmode="1")
        return natural_w


def _render_stats_row(
    img: "Image.Image",
    draw: "ImageDraw.ImageDraw",
    scale: int,
    header_stats: dict,
    global_frame_count: int,
    n_new_inputs: int,
    row_y: int,
    row_height: int,
    sidebar_width: int,
    font_path: "Path",
    small_font,
    user_colors: Optional[dict] = None,
) -> None:
    """Draw the stats header row onto img at the given y offset.

    Left half: total input counter + "TOTAL INPUTS" label.
    Right half: "TOP PLAYERS" + period label + top-3 player rows.
    """
    from PIL import ImageFont

    period_key = "today" if (global_frame_count // 75) % 2 == 0 else "alltime"
    period_label = "TODAY" if period_key == "today" else "ALL TIME"
    stats = header_stats[period_key]

    padding = 2 * scale
    col_w = sidebar_width // 2  # 62*scale each
    line_h = 10 * scale
    label_y_offset = 14 * scale  # y offset for "TOTAL INPUTS" label below the number

    # --- Load fonts ---
    def _load_font(size):
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except Exception:
            return ImageFont.load_default()

    # ---- Left column: total counter ----
    display_total = stats["total"] + n_new_inputs
    total_str = f"{display_total:,}"

    # Try progressively smaller font sizes until it fits
    num_font = None
    for font_size in range(12 * scale, 5 * scale, -scale):
        candidate = _load_font(font_size)
        try:
            bbox = draw.textbbox((0, 0), total_str, font=candidate)
            text_w = bbox[2] - bbox[0]
        except Exception:
            text_w = len(total_str) * font_size // 2
        if text_w <= col_w - 2 * padding:
            num_font = candidate
            break
    if num_font is None:
        num_font = _load_font(6 * scale)

    draw.text((padding, row_y + padding), total_str,
              fill=(255, 255, 255), font=num_font, fontmode="1")
    draw.text((padding, row_y + label_y_offset + padding), "TOTAL INPUTS",
              fill=(255, 255, 255), font=small_font, fontmode="1")

    # ---- Right column: leaderboard ----
    rx = col_w  # right column x start
    ordinals = ["1st", "2nd", "3rd"]

    # Header row: "TOP PLAYERS" left, period label right
    draw.text((rx + padding, row_y + padding), "TOP PLAYERS",
              fill=(255, 255, 255), font=small_font, fontmode="1")
    try:
        pl_bbox = draw.textbbox((0, 0), period_label, font=small_font)
        pl_w = pl_bbox[2] - pl_bbox[0]
    except Exception:
        pl_w = len(period_label) * 6
    draw.text((sidebar_width - pl_w - padding, row_y + padding), period_label,
              fill=(255, 255, 255), font=small_font, fontmode="1")

    # Player rows
    for rank_idx, ordinal in enumerate(ordinals):
        py = row_y + line_h + padding + rank_idx * line_h
        if py + line_h > row_y + row_height:
            break
        if rank_idx >= len(stats["top_players"]):
            continue
        player = stats["top_players"][rank_idx]
        pname = player["user_name"]
        pcount = str(player["count"])
        color = (user_colors or {}).get(pname, (255, 255, 255))

        # Prefix "1st: "
        prefix = f"{ordinal}: "
        try:
            pre_bbox = draw.textbbox((0, 0), prefix, font=small_font)
            pre_w = pre_bbox[2] - pre_bbox[0]
        except Exception:
            pre_w = len(prefix) * 6
        draw.text((rx + padding, py), prefix,
                  fill=(255, 255, 255), font=small_font, fontmode="1")

        # Suffix " - N"
        suffix = f" - {pcount}"
        try:
            suf_bbox = draw.textbbox((0, 0), suffix, font=small_font)
            suf_w = suf_bbox[2] - suf_bbox[0]
        except Exception:
            suf_w = len(suffix) * 6

        name_x = rx + padding + pre_w
        max_name_w = max(1, sidebar_width - name_x - suf_w - padding)
        actual_w = _draw_colored_username(
            img, draw, x=name_x, y=py,
            name=pname, color=color,
            max_w=max_name_w, line_height=line_h,
            font=small_font,
        )
        draw.text((name_x + actual_w, py), suffix,
                  fill=(255, 255, 255), font=small_font, fontmode="1")


def render_input_sidebar(
    inputs: list,
    base_width: int = 124,
    base_height: int = 144,
    scale: int = 3,
    active_labels: Optional[dict] = None,
    user_colors: Optional[dict] = None,
    header_stats: Optional[dict] = None,
    global_frame_count: int = 0,
    n_new_inputs: int = 0,
) -> np.ndarray:
    """Render a sidebar showing recent input entries as a numpy RGB array.

    Text is rendered white on black, right-aligned, bottom-up.
    Each entry shows: "{user_name}: {button_char}"
    Button chars: ← ↑ → ↓ A B START SELECT (WAIT shown as …)

    Args:
        inputs: List of dicts with keys: user_name, button (string value)
        width: Width of the sidebar in pixels
        height: Height of the sidebar in pixels
        scale: Multiplier for sidebar elements
        active_labels: Optional dict mapping input index → (x_offset_px, alpha_0_to_1)
            for animated "+score" labels. None means no labels.

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

    width=base_width*scale
    height=base_height*scale
    img = Image.new("RGB", (width, height), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Try to load bundled font; fall back to default
    font = None
    font_path = Path(__file__).parent.parent.parent / "assets" / "fonts" / "unifont-17.0.04.otf"
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(font_path), size=9*scale)
        label_font = ImageFont.truetype(str(font_path), size=6*scale)
    except Exception:
        from PIL import ImageFont
        font = ImageFont.load_default()
        label_font = ImageFont.load_default()

    line_height = 10*scale
    padding = 2*scale
    y = height - line_height - padding  # start from bottom

    stats_row_height = 48 * scale  # height reserved for the stats row
    date_row_height = line_height   # one text line for the date
    top_reserved = date_row_height + (stats_row_height if header_stats is not None else 0)

    # Render inputs bottom-up (most recent at bottom)
    for idx, entry in enumerate(reversed(inputs)):
        original_index = len(inputs) - 1 - idx

        if y < top_reserved:
            break  # Stop when we reach the top boundary

        button_val = entry.get("button", "")
        button_char = BUTTON_CHARS.get(button_val, button_val)
        user_name = entry.get("user_name", "?")
        suffix = f": {button_char}"
        streak = entry.get("current_streak", 0)
        color = user_colors.get(user_name, (255, 255, 255)) if user_colors else (255, 255, 255)

        # Measure username and suffix widths independently
        try:
            name_bbox = draw.textbbox((0, 0), user_name, font=font)
            name_natural_w = name_bbox[2] - name_bbox[0]
        except Exception:
            name_natural_w = len(user_name) * 6

        try:
            suf_bbox = draw.textbbox((0, 0), suffix, font=font)
            suffix_w = suf_bbox[2] - suf_bbox[0]
        except Exception:
            suffix_w = len(suffix) * 6

        # Compute streak badge dimensions (shown when streak > 1)
        streak_pre = ""
        streak_post = ""
        streak_icon = None
        streak_pre_w = 0
        streak_icon_w = 0
        streak_icon_y_offset = 0
        streak_post_w = 0
        streak_total_w = 0

        if streak > 1:
            streak_pre = " "
            streak_post = f"{streak}"
            streak_icon = _load_streak_icon(5*scale)
            streak_icon_y_offset = 2*scale
            streak_icon_w = streak_icon.width if streak_icon is not None else 0
            try:
                streak_pre_w = draw.textbbox((0, 0), streak_pre, font=font)[2]
                streak_post_w = draw.textbbox((0, 0), streak_post, font=font)[2]
            except Exception:
                streak_pre_w = len(streak_pre) * 6
                streak_post_w = len(streak_post) * 6
            streak_total_w = streak_pre_w + streak_icon_w + streak_post_w

        max_name_w = max(int(width * 0.8) - streak_total_w - suffix_w, 1)

        if name_natural_w > max_name_w and name_natural_w > 0:
            name_x = width - max_name_w - streak_total_w - suffix_w - padding
            _draw_colored_username(img, draw, name_x, y, user_name, color, max_name_w, line_height, font)
            cx = name_x + max_name_w
        else:
            name_x = width - name_natural_w - streak_total_w - suffix_w - padding
            used_w = _draw_colored_username(img, draw, name_x, y, user_name, color, max_name_w, line_height, font)
            cx = name_x + used_w

        if streak > 1:
            cx = _draw_streak_badge(
                draw, img, cx, y,
                streak_pre, streak_pre_w,
                streak_icon, streak_icon_y_offset, 
                streak_icon_w, streak_post, streak_post_w,
                font,
            )
        draw.text((cx, y), suffix, fill=(255, 255, 255), font=font, fontmode="1")

        # Score label animation
        label_info = (active_labels or {}).get(original_index)
        score = entry.get("total_score")
        if label_info is not None and score is not None:
            x_off, alpha = label_info
            v = max(0, min(255, int(255 * alpha)))
            label_text = f"+{score}"
            try:
                lbbox = draw.textbbox((0, 0), label_text, font=label_font)
                lw = lbbox[2] - lbbox[0]
            except Exception:
                lw = len(label_text) * 5
            gap_x = 2*scale
            gap_y = 2*scale

            lx = cx + x_off - lw - gap_x
            ly = y + gap_y
            
            # Fill with yellow tint
            draw.text((lx, ly), label_text, fill=(v, v, 0), font=label_font, fontmode="1")

        y -= line_height

    date_str = datetime.utcnow().strftime("%d/%m/%Y")
    draw.text((padding, 0), date_str, fill=(255, 255, 255), font=font, fontmode="1")

    if header_stats is not None:
        _render_stats_row(
            img=img,
            draw=draw,
            scale=scale,
            header_stats=header_stats,
            global_frame_count=global_frame_count,
            n_new_inputs=n_new_inputs,
            row_y=date_row_height,
            row_height=stats_row_height,
            sidebar_width=width,
            font_path=font_path,
            small_font=font,
            user_colors=user_colors,
        )

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
    capture_fps: int = 15,
    scale: int = 3,
    user_colors: Optional[dict] = None,
) -> Callable[[np.ndarray], np.ndarray]:
    """Build a stateful per-frame transform that composites the input sidebar.

    Returns a callable that, when called once per frame in sequence, composites
    an input sidebar reflecting accumulated inputs up to that frame.

    Args:
        pre_existing: Input dicts already visible at frame 0.
        new_inputs_with_offsets: List of (input_dict, frame_offset) pairs.
        capture_fps: Capture frames per second (used for label animation duration).
        scale: Scale factor for the sidebar.
        

    Returns:
        A callable ``transform(frame) -> composited_frame``.
    """
    state: dict = {"frame_index": 0, "current_inputs": list(pre_existing)}
    sorted_new = sorted(new_inputs_with_offsets, key=lambda x: x[1])
    sorted_new_iter = iter(sorted_new)
    next_item = next(sorted_new_iter, None)
    pending = list(sorted_new)
    score_label_animation_duration = 2 * capture_fps

    def transform(frame: np.ndarray) -> np.ndarray:
        nonlocal next_item
        fi = state["frame_index"]
        state["frame_index"] += 1

        while next_item is not None and next_item[1] <= fi:
            state["current_inputs"].append(next_item[0])
            next_item = next(sorted_new_iter, None)

        # Build active score labels for inputs within their N-second animation window
        active_labels: dict = {}
        n = len(state["current_inputs"])

        for inp_dict, frame_offset in pending:
            frames_since = fi - frame_offset
            if 0 <= frames_since < score_label_animation_duration:
                for ci in range(n - 1, -1, -1):
                    if state["current_inputs"][ci] is inp_dict:
                        translation_t = frames_since / max((score_label_animation_duration//2) - 1, 1)
                        translation_ease = 1.0 - (1.0 - translation_t) ** 2  # quadratic ease-out
                        x_offset = -4.0 * scale * translation_ease

                        alpha_t = frames_since / max(score_label_animation_duration - 1, 1)
                        alpha_ease = 1.0 - (1.0 - alpha_t) ** 2  # quadratic ease-out
                        alpha = 1.0 - alpha_ease

                        active_labels[ci] = (x_offset, alpha)
                        break

        sidebar = render_input_sidebar(state["current_inputs"], active_labels=active_labels, user_colors=user_colors, scale=scale)
        return composite_overlay(frame, sidebar)

    return transform


def render_status_bar(data: Optional[dict], width: int, scale: int, render_fn: Optional[Callable] = None) -> np.ndarray:
    """Render a status bar strip for the given game data.

    Args:
        data: Status bar data dict, or None.
        width: Total pixel width of the output strip (should match composite width).
        scale: Rendering scale factor (e.g. 2 for animation, 3 for timelapse).
        render_fn: Optional callable ``(img, data, scale) -> None`` that draws
            game-specific content on the PIL Image in-place.

    Returns:
        NumPy array of shape (16*scale, width, 3) uint8.
    """
    height = 16 * scale
    bg_color = (30, 30, 30)
    img = Image.new("RGB", (width, height), bg_color)

    if render_fn is not None and data is not None:
        render_fn(img, data, scale)

    return np.array(img, dtype=np.uint8)


def apply_overlay_composite(
    frames: list[np.ndarray],
    pre_existing_inputs: list,
    new_inputs_with_offsets: list,
    capture_fps: int = 15,
    user_colors: Optional[dict] = None,
    status_bar_data: Optional[dict] = None,
    scale: int = 3,
    status_bar_render_fn: Optional[Callable] = None,
) -> list[np.ndarray]:
    """Composite the input sidebar onto a sequence of already-scaled frames.

    Applies a stateful per-frame transform that adds new inputs to the sidebar
    at the specified frame offsets. If status_bar_data is provided, a status
    bar strip is stacked below each composited frame.

    Args:
        frames: List of scaled numpy arrays (H, W, 3). Must be pre-scaled;
            no internal scaling is applied.
        pre_existing_inputs: Input dicts visible from frame 0.
        new_inputs_with_offsets: List of (input_dict, frame_offset) pairs.
        capture_fps: Capture frames per second (used for score label animation duration).
        status_bar_data: Optional game-state dict for status bar rendering.
        scale: Rendering scale factor (used for status bar height).
        status_bar_render_fn: Optional game-specific render callable passed to render_status_bar.

    Returns:
        List of composited frames, each wider by the sidebar width (H, W+sidebar, 3),
        and taller by 16*scale if status_bar_data is not None.
    """
    transform = _make_frame_transform(pre_existing_inputs, new_inputs_with_offsets, capture_fps, user_colors=user_colors)

    # Transform in-place: as each slot is overwritten CPython immediately frees
    # the old frame (refcount → 0), so we never hold both the raw and composited
    # generations simultaneously.
    _status_bar: np.ndarray | None = None
    for i in range(len(frames)):
        composited = transform(frames[i])
        if _status_bar is None:
            _status_bar = render_status_bar(status_bar_data, composited.shape[1], scale, render_fn=status_bar_render_fn)
        frames[i] = np.vstack([composited, _status_bar])
    return frames


def save_frames_as_mp4(
    frames: list[np.ndarray],
    fps: int = 10,
    crf: int = 28,
    preset: str = "ultrafast",
) -> BytesIO:
    """Save a sequence of frames as an MP4 video using FFmpeg rawvideo piping.

    Uses stdin to pipe frames directly to ffmpeg (no intermediate PNG files),
    then writes output to a temp file and reads into BytesIO.
    Frames are encoded at their received dimensions — no internal scaling is applied.

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

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_out:
        output_path = tmp_out.name

    try:
        cmd = [
            'ffmpeg', '-y',
            '-an',
            '-f', 'rawvideo',
            '-pix_fmt', 'rgb24',
            '-s', f'{w}x{h}',
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
            process.stdin.write(np.array(frame).tobytes())
        
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

    Frames are encoded at their received dimensions — no internal scaling is applied.

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

    duration_ms = int(1000 / fps)

    first = Image.fromarray(frames[0])

    buffer = BytesIO()
    first.save(
        buffer,
        format="AVIF",
        save_all=True,
        append_images=(Image.fromarray(f) for f in frames[1:]),
        duration=duration_ms,
        loop=0,
        optimize=False,
    )
    buffer.seek(0)
    return buffer


def generate_tbc_frames(
    base_frame: np.ndarray,
    duration_frames: int = 20,
    end_hold_frames: int = 20,
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

        last_frame = frames[-1]
        for _ in range(end_hold_frames):
            frames.append(last_frame)

    except Exception as e:
        logger.error(f"Error generating TBC frames: {e}")
        return []

    return frames


# Module-level asset cache keyed by (reaction_type, asset_dir_str)
# Keying on asset_dir prevents test isolation issues when different dirs
# are used across tests in the same session.
_reaction_asset_cache: dict[tuple[str, str], Optional["Image.Image"]] = {}


def _load_reaction_asset(reaction_type: str, asset_dir: Path) -> Optional["Image.Image"]:
    """Load and cache reaction emoji PNG (RGBA). Returns None if missing."""
    cache_key = (reaction_type, str(asset_dir))
    if cache_key in _reaction_asset_cache:
        return _reaction_asset_cache[cache_key]
    asset_path = asset_dir / f"reaction_{reaction_type}.png"
    if not asset_path.exists():
        logger.warning(f"Reaction asset not found: {asset_path}")
        _reaction_asset_cache[cache_key] = None
        return None
    img = Image.open(asset_path).convert("RGBA")
    _reaction_asset_cache[cache_key] = img
    return img


def apply_reaction_overlay(
    frames: list[np.ndarray],
    reactions: list[dict],
    capture_fps: int = 15,
    asset_dir: Path = Path("./assets"),
) -> list[np.ndarray]:
    """Composite reaction emoji animations onto game frames.

    Reactions are grouped into 2-second windows of up to 3. Each window
    starts at frame ``w * 2 * capture_fps``. Within a window, each slot
    staggers by ~100ms (``round(0.1 * capture_fps)`` frames).

    Each reaction animates: scale-up (5 frames), hold (15 frames),
    scale-down (5 frames) = 25 frames total.

    Layout: 3 side-by-side slots at x=[0, 64, 128], each 64px wide.
    Username rendered above emoji in white using the existing unifont.

    Args:
        frames: 3x-scaled game frames (H, W, 3), before sidebar compositing.
        reactions: List of dicts with keys ``user_name`` and ``reaction_type``,
            in queue order (oldest first).
        capture_fps: Capture frames per second (default 15).
        asset_dir: Directory containing ``reaction_<type>.png`` assets.

    Returns:
        Frames with reaction overlays composited in-place.
    """
    if not reactions:
        return frames

    num_frames = len(frames)
    
    if num_frames == 0:
        return frames

    frame_w = frames[0].shape[1]
    
    window_size = 2 * capture_fps        # 30 frames per window
    window_reaction_capacity = 5

    anim_total = 25                       # frames per reaction animation
    scale_up_frames = 5
    hold_frames = 15
    stagger_frames = 1
    slot_width = round(0.2 * frame_w)
    slot_x_positions = [slot_width * 4, slot_width * 3, slot_width * 2, slot_width, 0]

    # Load font (different from sidebar for legibility)
    font = None
    font_path = Path(__file__).parent.parent.parent / "assets" / "fonts" / "OpenSans-Bold.ttf"
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(font_path), size=16)
    except Exception:
        from PIL import ImageFont
        font = ImageFont.load_default()

    # Group reactions into windows of 5
    windows: list[list[dict]] = []
    for i in range(0, len(reactions), window_reaction_capacity):
        windows.append(reactions[i : i + window_reaction_capacity])

    result = [f.copy() for f in frames]

    for w_idx, window_reactions in enumerate(windows):
        window_start = w_idx * window_size
        if window_start >= num_frames:
            break  # no room for this window

        for slot_idx, reaction in enumerate(window_reactions):
            reaction_type = reaction["reaction_type"]
            user_name = reaction["user_name"]
            slot_x = slot_x_positions[slot_idx]

            asset = _load_reaction_asset(reaction_type, asset_dir)
            start_frame = window_start + slot_idx * stagger_frames

            for fi in range(num_frames):
                frames_into = fi - start_frame
                if frames_into < 0 or frames_into >= anim_total:
                    continue

                # Compute scale
                if frames_into < scale_up_frames:
                    phase_frame = frames_into
                    scale = phase_frame / 4
                elif frames_into < scale_up_frames + hold_frames:
                    scale = 1.0
                else:
                    phase_frame = frames_into - (scale_up_frames + hold_frames)
                    scale = 1.0 - phase_frame / 4

                if scale <= 0:
                    continue

                if asset is not None:
                    pil_frame = Image.fromarray(result[fi])
                    draw = ImageDraw.Draw(pil_frame)

                    # Measure username text
                    try:
                        bbox = draw.textbbox((0, 0), user_name, font=font)
                        text_w = bbox[2] - bbox[0]
                        text_h = bbox[3] - bbox[1]
                        text_top = bbox[1]  # bearing: visual top is this far below draw origin
                    except Exception:
                        text_w = len(user_name) * 7
                        text_h = 14
                        text_top = 0

                    max_text_w = slot_width - 4
                    pad_x, pad_y = 3, 2
                    text_y = 2

                    if text_w > max_text_w and text_w > 0:
                        # Render to temp image and scale down to fit slot width
                        tmp_img = Image.new("RGBA", (text_w, text_h + 2), (0, 0, 0, 0))
                        ImageDraw.Draw(tmp_img).text((0, -text_top), user_name, fill=(255, 255, 255, 255), font=font, fontmode="1")
                        tmp_img = tmp_img.resize((max_text_w, text_h + 2), Image.Resampling.LANCZOS)
                        actual_text_w = max_text_w
                        use_tmp = True
                    else:
                        actual_text_w = text_w
                        use_tmp = False

                    text_x = slot_x + (slot_width - actual_text_w) // 2

                    # Draw 80%-opacity rounded rect background behind username
                    overlay = Image.new("RGBA", pil_frame.size, (0, 0, 0, 0))
                    ImageDraw.Draw(overlay).rounded_rectangle(
                        [text_x - pad_x, text_y - pad_y,
                         text_x + actual_text_w + pad_x, text_y + text_h + pad_y],
                        radius=3,
                        fill=(0, 0, 0, 204),
                    )
                    pil_frame = Image.alpha_composite(pil_frame.convert("RGBA"), overlay).convert("RGB")

                    # Draw username text (offset by top bearing so visual top aligns with rect)
                    if use_tmp:
                        pil_frame.paste(tmp_img, (text_x, text_y), tmp_img)
                    else:
                        ImageDraw.Draw(pil_frame).text((text_x, text_y - text_top), user_name, fill=(255, 255, 255), font=font, fontmode="1")

                    # Resize emoji to scaled size, centered in slot
                    emoji_size = max(1, int(slot_width * scale))
                    resized = asset.resize((emoji_size, emoji_size), Image.Resampling.NEAREST)
                    emoji_x = slot_x + (slot_width - emoji_size) // 2
                    emoji_y = 20 + (slot_width - emoji_size) // 2  # below username
                    pil_frame.paste(resized, (emoji_x, emoji_y), resized)

                    result[fi] = np.array(pil_frame, dtype=np.uint8)

    return result


def _make_reaction_frame_transform(
    reactions: list,
    capture_fps: int = 15,
    scale: int = 3,
    frame_skip: int = 1,
    asset_dir: Path = Path("./assets"),
) -> Callable[[np.ndarray, int], np.ndarray]:
    """Build a per-frame reaction overlay transform (streaming-friendly).

    Equivalent to ``apply_reaction_overlay`` but returns a stateless callable
    that composites reactions onto a single frame at a given logical frame index
    instead of operating on a list. The ``frame_skip`` parameter divides all
    timing so timelapse subsampling is handled correctly.

    Args:
        reactions: List of reaction dicts with ``reaction_type`` and ``user_name``.
        capture_fps: Capture frames per second.
        frame_skip: Subsampling factor (1 = no skip).
        asset_dir: Directory containing ``reaction_<type>.png`` assets.

    Returns:
        Callable ``(frame, logical_index) -> composited_frame``.
    """
    if not reactions:
        return lambda frame, index: frame

    window_size_raw = 2 * capture_fps
    window_reaction_capacity = 5
    anim_total = 25
    scale_up_frames = 5
    hold_frames = 15
    stagger_frames = 1

    # Preload assets
    assets: dict = {}
    for r in reactions:
        rt = r["reaction_type"]
        if rt not in assets:
            assets[rt] = _load_reaction_asset(rt, asset_dir)

    # Precompute per-reaction animation schedule (in logical/output frame indices)
    schedule = []
    for i, reaction in enumerate(reactions):
        w_idx = i // window_reaction_capacity
        slot_idx = i % window_reaction_capacity
        start_raw = w_idx * window_size_raw + slot_idx * stagger_frames
        start_logical = start_raw // frame_skip
        schedule.append({
            "asset": assets.get(reaction["reaction_type"]),
            "user_name": reaction.get("user_name", ""),
            "start_frame": start_logical,
            "slot_idx": slot_idx,
        })

    # Load font once
    font = None
    font_path = Path(__file__).parent.parent.parent / "assets" / "fonts" / "OpenSans-Bold.ttf"
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(font_path), size=5 * scale)
    except Exception:
        from PIL import ImageFont
        font = ImageFont.load_default()

    def transform(frame: np.ndarray, index: int) -> np.ndarray:
        frame_w = frame.shape[1]
        slot_width = round(0.2 * frame_w)
        slot_x_positions = [slot_width * 4, slot_width * 3, slot_width * 2, slot_width, 0]

        result = frame
        copied = False

        for entry in schedule:
            frames_into = index - entry["start_frame"]
            if frames_into < 0 or frames_into >= anim_total:
                continue

            asset = entry["asset"]
            if asset is None:
                continue

            slot_x = slot_x_positions[entry["slot_idx"] % len(slot_x_positions)]
            user_name = entry["user_name"]

            # Compute scale
            if frames_into < scale_up_frames:
                scale = frames_into / 4
            elif frames_into < scale_up_frames + hold_frames:
                scale = 1.0
            else:
                scale = 1.0 - (frames_into - scale_up_frames - hold_frames) / 4

            if scale <= 0:
                continue

            if not copied:
                result = frame.copy()
                copied = True

            pil_frame = Image.fromarray(result)
            draw = ImageDraw.Draw(pil_frame)

            try:
                bbox = draw.textbbox((0, 0), user_name, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                text_top = bbox[1]
            except Exception:
                text_w = len(user_name) * 7
                text_h = 14
                text_top = 0

            max_text_w = slot_width - 4
            pad_x, pad_y = 3, 2
            text_y = 2

            if text_w > max_text_w and text_w > 0:
                tmp_img = Image.new("RGBA", (text_w, text_h + 2), (0, 0, 0, 0))
                ImageDraw.Draw(tmp_img).text((0, -text_top), user_name, fill=(255, 255, 255, 255), font=font, fontmode="1")
                tmp_img = tmp_img.resize((max_text_w, text_h + 2), Image.Resampling.LANCZOS)
                actual_text_w = max_text_w
                use_tmp = True
            else:
                actual_text_w = text_w
                use_tmp = False

            text_x = slot_x + (slot_width - actual_text_w) // 2

            overlay = Image.new("RGBA", pil_frame.size, (0, 0, 0, 0))
            ImageDraw.Draw(overlay).rounded_rectangle(
                [text_x - pad_x, text_y - pad_y,
                 text_x + actual_text_w + pad_x, text_y + text_h + pad_y],
                radius=3,
                fill=(0, 0, 0, 204),
            )
            pil_frame = Image.alpha_composite(pil_frame.convert("RGBA"), overlay).convert("RGB")

            if use_tmp:
                pil_frame.paste(tmp_img, (text_x, text_y), tmp_img)
            else:
                ImageDraw.Draw(pil_frame).text((text_x, text_y - text_top), user_name, fill=(255, 255, 255), font=font, fontmode="1")

            emoji_size = max(1, int(slot_width * scale))
            resized = asset.resize((emoji_size, emoji_size), Image.Resampling.NEAREST)
            emoji_x = slot_x + (slot_width - emoji_size) // 2
            emoji_y = 20 + (slot_width - emoji_size) // 2
            pil_frame.paste(resized, (emoji_x, emoji_y), resized)

            result = np.array(pil_frame, dtype=np.uint8)

        return result

    return transform


def build_timelapse_transform(
    compositing_context: dict,
) -> Callable[[np.ndarray, int], np.ndarray]:
    """Build a per-frame transform for timelapse encoding from a compositing_context dict.

    The returned transform scales each raw frame 3x, applies reactions and the
    input sidebar, mirroring what the animation pass does but without TBC frames.
    Frame offsets from ``new_inputs_with_offsets`` are divided by ``frame_skip``
    so timing is correct after subsampling.

    Args:
        compositing_context: Dict as stored in ``timelapse_jobs.compositing_context``.

    Returns:
        Callable ``(raw_frame, logical_index) -> composited_frame``.
    """
    pre_existing = compositing_context.get("pre_existing_inputs", [])
    raw_inputs = compositing_context.get("new_inputs_with_offsets", [])
    frame_skip = compositing_context.get("frame_skip", 1)
    capture_fps = compositing_context.get("capture_fps", 15)
    reactions = compositing_context.get("reactions", [])
    raw_user_colors = compositing_context.get("user_colors", {})

    user_colors = {k: tuple(v) for k, v in raw_user_colors.items()}

    # Adjust input frame offsets for subsampling
    new_inputs_with_offsets = [(inp, off // max(frame_skip, 1)) for inp, off in raw_inputs]

    sidebar_transform = _make_frame_transform(
        pre_existing, new_inputs_with_offsets, capture_fps, user_colors=user_colors
    )
    reaction_transform = (
        _make_reaction_frame_transform(reactions, capture_fps, frame_skip)
        if reactions else None
    )

    status_bar_data = compositing_context.get("status_bar_data")

    cartridge_title = compositing_context.get("cartridge_title")
    status_bar_render_fn = None
    if cartridge_title:
        try:
            import importlib
            m = importlib.import_module(f"src.game_status_bars.{cartridge_title.lower()}")
            status_bar_render_fn = getattr(m, "render_status_bar", None)
        except ImportError:
            pass
        
    def transform(raw_frame: np.ndarray, index: int) -> np.ndarray:
        h, w = raw_frame.shape[:2]
        scaled = np.array(Image.fromarray(raw_frame).resize(
            (w * 3, h * 3), Image.Resampling.NEAREST
        ))
        if reaction_transform is not None:
            scaled = reaction_transform(scaled, index)
        composited = sidebar_transform(scaled)
        status_bar = render_status_bar(status_bar_data, composited.shape[1], scale=3, render_fn=status_bar_render_fn)
        return np.vstack([composited, status_bar])

    return transform


async def save_frames_as_mp4_streaming(
    frames: Iterable[np.ndarray],
    transform: Callable[[np.ndarray, int], np.ndarray],
    output_path: str,
    fps: int,
    crf: int = 28,
    preset: str = "medium",
    audio_chunks: Optional[List[np.ndarray]] = None,
    sample_rate: int = 48000,
    low_priority: bool = False,
) -> None:
    """Encode a stream of raw frames into an MP4 file via FFmpeg rawvideo piping.

    Each frame is passed through ``transform(frame, index)`` before being piped
    to FFmpeg stdin. No intermediate list of composited frames is ever held in
    memory; only one frame at a time is in flight.

    Args:
        frames: Iterable of raw numpy arrays (H, W, 3) in RGB format.
        transform: Callable ``(frame, index) -> composited_frame``.  The
            composited frame must have consistent shape across all frames.
        output_path: Destination MP4 file path.
        fps: Output frames per second.
        crf: Constant Rate Factor (quality).
        preset: FFmpeg encoding speed preset.
        audio_chunks: Optional list of int8 stereo ``(N, 2)`` ndarrays for audio.
        sample_rate: Audio sample rate in Hz (used when ``audio_chunks`` provided).
        low_priority: If True, run FFmpeg with ``nice 19``.

    Raises:
        ValueError: If the frames iterable is empty.
        RuntimeError: If FFmpeg encoding fails.
    """
    import asyncio

    it = iter(frames)
    try:
        first_raw = next(it)
    except StopIteration:
        raise ValueError("No frames provided")

    first = transform(first_raw, 0)
    h, w = first.shape[:2]

    tmp_pcm = None
    try:
        if audio_chunks:
            combined = np.concatenate(audio_chunks, axis=0)
            pcm_int16 = combined.astype(np.int16) << 8
            dither = (
                np.random.randint(-128, 129, pcm_int16.shape, dtype=np.int16)
                + np.random.randint(-128, 129, pcm_int16.shape, dtype=np.int16)
            ) // 2
            pcm_int16 = np.clip(pcm_int16 + dither, -32768, 32767)
            with tempfile.NamedTemporaryFile(suffix='.pcm', delete=False) as f:
                tmp_pcm = f.name
                f.write(pcm_int16.tobytes())

        video_args = [
            'ffmpeg', '-y',
            '-f', 'rawvideo',
            '-pix_fmt', 'rgb24',
            '-s', f'{w}x{h}',
            '-framerate', str(fps),
            '-i', 'pipe:0',
        ]

        if tmp_pcm:
            video_args += [
                '-f', 's16le',
                '-ar', str(sample_rate),
                '-ac', '2',
                '-i', tmp_pcm,
            ]

        encode_args = [
            '-vcodec', 'libx264',
            '-profile:v', 'baseline',
            '-pix_fmt', 'yuv420p',
            '-crf', str(crf),
            '-preset', preset,
        ]

        if tmp_pcm:
            encode_args += ['-c:a', 'aac', '-af', 'highpass=f=40,lowpass=f=6500,aresample=32000']
        else:
            encode_args += ['-an', '-movflags', '+faststart', '-metadata:s:v:0', 'loop=0']

        cmd = video_args + encode_args + [output_path]

        kwargs: dict = {}
        if low_priority:
            kwargs['preexec_fn'] = lambda: os.nice(19)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )

        # Pipe first transformed frame
        process.stdin.write(first.tobytes())

        # Pipe remaining frames one at a time
        for i, raw in enumerate(it, start=1):
            transformed = transform(raw, i)
            process.stdin.write(transformed.tobytes())

        process.stdin.close()
        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg streaming encode failed: {stderr.decode()}")

        logger.debug(f"save_frames_as_mp4_streaming: wrote {output_path}")

    finally:
        if tmp_pcm and os.path.exists(tmp_pcm):
            os.remove(tmp_pcm)


async def save_frames_as_avif_streaming(
    frames: Iterable[np.ndarray],
    transform: Callable[[np.ndarray, int], np.ndarray],
    output_path: str,
    fps: int,
    crf: int = 45,
    low_priority: bool = False,
) -> None:
    """Encode a stream of raw frames into an animated AVIF file via FFmpeg.

    Each frame is passed through ``transform(frame, index)`` before being piped
    to FFmpeg stdin. No intermediate list of composited frames is ever held in
    memory; only one frame at a time is in flight.

    Args:
        frames: Iterable of raw numpy arrays (H, W, 3) in RGB format.
        transform: Callable ``(frame, index) -> composited_frame``.
        output_path: Destination AVIF file path.
        fps: Output frames per second.
        crf: Constant Rate Factor (quality, lower = better).
        low_priority: If True, run FFmpeg with ``nice 19``.

    Raises:
        ValueError: If the frames iterable is empty.
        RuntimeError: If FFmpeg encoding fails.
    """
    import asyncio

    it = iter(frames)
    try:
        first_raw = next(it)
    except StopIteration:
        raise ValueError("No frames provided")

    first = transform(first_raw, 0)
    h, w = first.shape[:2]

    cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo',
        '-pix_fmt', 'rgb24',
        '-s', f'{w}x{h}',
        '-framerate', str(fps),
        '-i', 'pipe:0',
        '-an',
        '-vf', 'format=yuv420p',
        '-c:v', 'libsvtav1',
        '-preset', '13',
        '-crf', str(crf),
        '-svtav1-params',
        'rtc=1:tune=1:pred-struct=1:hierarchical-levels=2:lookahead=0:scd=0:enable-overlays=0:fast-decode=1:film-grain=0:enable-tpl-la=0:enable-dlf=0:enable-cdef=0:enable-restoration=0:tile-columns=0:tile-rows=0',
        '-threads', '1',
        '-loop', '0',
        output_path,
    ]
    
    # cmd = [
    #     'ffmpeg', '-y',
    #     '-f', 'rawvideo',
    #     '-pix_fmt', 'rgb24',
    #     '-s', f'{w}x{h}',
    #     '-framerate', str(fps),
    #     '-i', 'pipe:0',
    #     '-an',
    #     '-vf', 'format=yuv420p',
    #     '-c:v', 'libaom-av1',
    #     '-usage', 'realtime',
    #     '-deadline', 'realtime',
    #     '-cpu-used', '8',
    #     '-lag-in-frames', '0',
    #     '-threads', '1',
    #     '-row-mt', '0',
    #     '-tile-columns', '0',
    #     '-tile-rows', '0',
    #     '-crf', str(crf),
    #     '-b:v', '0',
    #     '-loop', '0',
    #     output_path,
    # ]

    kwargs: dict = {}
    if low_priority:
        kwargs['preexec_fn'] = lambda: os.nice(19)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )

    process.stdin.write(first.tobytes())

    for i, raw in enumerate(it, start=1):
        transformed = transform(raw, i)
        process.stdin.write(transformed.tobytes())

    process.stdin.close()
    _, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg AVIF encode failed: {stderr.decode()}")

    logger.debug(f"save_frames_as_avif_streaming: wrote {output_path}")
