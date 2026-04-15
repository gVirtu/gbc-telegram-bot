"""Tests for frame processing utilities.

This module tests frame hashing, PNG conversion, and optimization logic.
"""

import hashlib

import numpy as np
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image

from src.utils.frame_utils import (
    _make_reaction_frame_transform,
    create_empty_frame,
    frame_to_png,
    frames_equal,
    hash_frame,
    hex_to_rgb,
    render_input_sidebar,
    save_frames_as_mp4,
    save_frames_as_avif,
    save_frames_as_mp4_streaming,
)


class TestHashFrame:
    """Test frame hashing functionality."""
    
    def test_hash_consistency(self):
        """Test that same frame produces same hash."""
        frame = np.zeros((144, 160, 3), dtype=np.uint8)
        hash1 = hash_frame(frame)
        hash2 = hash_frame(frame)
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex is 64 chars
    
    def test_hash_different_frames(self):
        """Test that different frames produce different hashes."""
        frame1 = np.zeros((144, 160, 3), dtype=np.uint8)
        frame2 = np.ones((144, 160, 3), dtype=np.uint8)
        
        hash1 = hash_frame(frame1)
        hash2 = hash_frame(frame2)
        
        assert hash1 != hash2
    
    def test_hash_deterministic(self):
        """Test hash is deterministic across calls."""
        frame = np.random.randint(0, 256, (144, 160, 3), dtype=np.uint8)
        
        hashes = [hash_frame(frame) for _ in range(10)]
        
        assert all(h == hashes[0] for h in hashes)
    
    def test_hash_matches_sha256(self):
        """Test that our hash matches direct SHA256."""
        frame = np.zeros((144, 160, 3), dtype=np.uint8)
        expected = hashlib.sha256(frame.tobytes()).hexdigest()
        
        assert hash_frame(frame) == expected


class TestFrameToPng:
    """Test PNG conversion functionality."""
    
    def test_converts_to_bytes(self):
        """Test that frame is converted to PNG bytes."""
        frame = np.zeros((144, 160, 3), dtype=np.uint8)
        png_buffer = frame_to_png(frame)
        
        assert isinstance(png_buffer.read(), bytes)
        assert len(png_buffer.getvalue()) > 0
    
    def test_converts_rgb_frame(self):
        """Test conversion of RGB frame."""
        # Create a red frame
        frame = np.zeros((144, 160, 3), dtype=np.uint8)
        frame[:, :, 0] = 255  # Red channel
        
        png_buffer = frame_to_png(frame)
        
        # Verify it's a valid PNG by loading it
        png_buffer.seek(0)
        image = Image.open(png_buffer)
        
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.size == (320, 288)
    
    @pytest.mark.parametrize("width,height", [
        (160, 144),   # Standard GameBoy
        (320, 288),   # 2x scale
        (80, 72),     # 0.5x scale
        (640, 576),   # 4x scale
    ])
    def test_different_sizes(self, width, height):
        """Test conversion with different frame sizes."""
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        png_buffer = frame_to_png(frame)

        png_buffer.seek(0)
        image = Image.open(png_buffer)

        assert image.size == (width * 2, height * 2)

    @pytest.mark.parametrize("color,expected_rgb", [
        ((255, 0, 0), (255, 0, 0)),      # Red
        ((0, 255, 0), (0, 255, 0)),      # Green
        ((0, 0, 255), (0, 0, 255)),      # Blue
        ((255, 255, 255), (255, 255, 255)),  # White
        ((0, 0, 0), (0, 0, 0)),          # Black
    ])
    def test_frame_colors(self, color, expected_rgb):
        """Test frame conversion preserves colors."""
        frame = np.zeros((144, 160, 3), dtype=np.uint8)
        frame[:, :, 0] = color[0]
        frame[:, :, 1] = color[1]
        frame[:, :, 2] = color[2]

        png_buffer = frame_to_png(frame)
        png_buffer.seek(0)
        image = Image.open(png_buffer)

        # Check a pixel in the center
        pixel = image.getpixel((80, 72))
        assert pixel == expected_rgb

    def test_invalid_input_not_array(self):
        """Test error on non-array input."""
        with pytest.raises(ValueError, match="Expected numpy array"):
            frame_to_png("not an array")
    
    def test_invalid_input_wrong_shape(self):
        """Test error on wrong array shape."""
        # 2D array instead of 3D
        frame = np.zeros((144, 160), dtype=np.uint8)
        
        with pytest.raises(ValueError, match="Expected frame shape"):
            frame_to_png(frame)
    
    def test_invalid_input_wrong_channels(self):
        """Test error on wrong number of channels."""
        # 4 channels instead of 3
        frame = np.zeros((144, 160, 4), dtype=np.uint8)
        
        with pytest.raises(ValueError, match="Expected frame shape"):
            frame_to_png(frame)
    
    def test_optimization_flag(self):
        """Test that optimization flag is respected."""
        frame = np.random.randint(0, 256, (144, 160, 3), dtype=np.uint8)
        
        # Both should work, optimized might be smaller
        png_optimized = frame_to_png(frame, optimize=True)
        png_unoptimized = frame_to_png(frame, optimize=False)
        
        assert len(png_optimized.getvalue()) > 0
        assert len(png_unoptimized.getvalue()) > 0


class TestFramesEqual:
    """Test frame comparison functionality."""
    
    def test_identical_frames(self):
        """Test that identical frames are equal."""
        frame1 = np.zeros((144, 160, 3), dtype=np.uint8)
        frame2 = np.zeros((144, 160, 3), dtype=np.uint8)
        
        assert frames_equal(frame1, frame2) is True
    
    def test_different_frames(self):
        """Test that different frames are not equal."""
        frame1 = np.zeros((144, 160, 3), dtype=np.uint8)
        frame2 = np.ones((144, 160, 3), dtype=np.uint8)
        
        assert frames_equal(frame1, frame2) is False
    
    def test_same_object(self):
        """Test that same object is equal to itself."""
        frame = np.zeros((144, 160, 3), dtype=np.uint8)
        
        assert frames_equal(frame, frame) is True
    
    def test_different_shapes(self):
        """Test that different shapes are not equal."""
        frame1 = np.zeros((144, 160, 3), dtype=np.uint8)
        frame2 = np.zeros((288, 320, 3), dtype=np.uint8)
        
        assert frames_equal(frame1, frame2) is False
    
    def test_single_pixel_difference(self):
        """Test that single pixel difference makes frames unequal."""
        frame1 = np.zeros((144, 160, 3), dtype=np.uint8)
        frame2 = np.zeros((144, 160, 3), dtype=np.uint8)
        frame2[0, 0, 0] = 1  # Change one pixel
        
        assert frames_equal(frame1, frame2) is False


class TestCreateEmptyFrame:
    """Test empty frame creation."""
    
    def test_default_white_frame(self):
        """Test default white frame creation."""
        frame = create_empty_frame()
        
        assert frame.shape == (144, 160, 3)
        assert frame.dtype == np.uint8
        assert np.all(frame == 255)  # White
    
    def test_custom_color(self):
        """Test frame with custom color."""
        frame = create_empty_frame(color=(255, 0, 0))  # Red
        
        assert np.all(frame[:, :, 0] == 255)  # Red channel
        assert np.all(frame[:, :, 1] == 0)    # Green channel
        assert np.all(frame[:, :, 2] == 0)    # Blue channel
    
    def test_custom_size(self):
        """Test frame with custom size."""
        frame = create_empty_frame(width=100, height=80)
        
        assert frame.shape == (80, 100, 3)
    
    def test_gameboy_defaults(self):
        """Test that defaults match GameBoy resolution."""
        frame = create_empty_frame()
        
        # GameBoy Color resolution is 160x144
        assert frame.shape[1] == 160  # Width
        assert frame.shape[0] == 144  # Height


class TestSaveFramesAsMp4:
    """Test MP4 encoding functionality."""

    def test_mp4_output_valid(self):
        """Test that MP4 output is valid."""
        # Pass pre-scaled 288×320 frames (callers are responsible for scaling)
        frames = [create_empty_frame(width=320, height=288, color=(i * 50, 0, 0)) for i in range(5)]

        mp4_buffer = save_frames_as_mp4(frames, fps=10)

        mp4_buffer.seek(0)
        header = mp4_buffer.read(12)
        assert header[4:8] == b'ftyp'

    def test_mp4_empty_frames_raises(self):
        """Test that empty frames raises ValueError."""
        with pytest.raises(ValueError, match="No frames provided"):
            save_frames_as_mp4([])

    def test_mp4_different_fps(self):
        """Test MP4 encoding with different frame rates."""
        frames = [create_empty_frame(width=320, height=288) for _ in range(3)]

        for fps in [5, 10, 15, 30]:
            mp4_buffer = save_frames_as_mp4(frames, fps=fps)
            assert len(mp4_buffer.getvalue()) > 0

    def test_mp4_encodes_at_received_dimensions(self):
        """Frames are encoded at their received size — no internal upscaling."""
        # Pass already-scaled 288×320 frames; function must NOT double them
        frames = [create_empty_frame(width=320, height=288) for _ in range(3)]

        mp4_buffer = save_frames_as_mp4(frames, fps=10)

        assert len(mp4_buffer.getvalue()) > 0
        mp4_buffer.seek(4)
        assert mp4_buffer.read(4) == b'ftyp'

    def test_mp4_crf_settings(self):
        """Test different CRF quality settings."""
        frames = [create_empty_frame(width=320, height=288) for _ in range(3)]

        for crf in [18, 23, 28, 35]:
            mp4_buffer = save_frames_as_mp4(frames, crf=crf)
            assert len(mp4_buffer.getvalue()) > 0

    def test_mp4_preset_settings(self):
        """Test different preset settings."""
        frames = [create_empty_frame(width=320, height=288) for _ in range(3)]

        for preset in ["ultrafast", "fast", "medium"]:
            mp4_buffer = save_frames_as_mp4(frames, preset=preset)
            assert len(mp4_buffer.getvalue()) > 0


class TestGenerateTbcFrames:
    """Test TBC frame generation functionality."""

    def test_generate_tbc_frames_returns_list(self):
        """Test that generate_tbc_frames returns a list of frames."""
        from src.utils.frame_utils import generate_tbc_frames
        from src.utils.frame_utils import create_empty_frame
        base_frame = create_empty_frame()
        result = generate_tbc_frames(base_frame)
        assert isinstance(result, list)
        assert len(result) == 40  # default duration x2 (due to end hold frames)

    def test_generate_tbc_frames_uses_custom_duration(self):
        """Test that generate_tbc_frames respects custom duration."""
        from src.utils.frame_utils import generate_tbc_frames
        from src.utils.frame_utils import create_empty_frame
        base_frame = create_empty_frame()
        result = generate_tbc_frames(base_frame, duration_frames=10, end_hold_frames=5)
        assert len(result) == 15

    def test_generate_tbc_frames_preserves_shape(self):
        """Test that generated frames have same shape as base frame."""
        from src.utils.frame_utils import generate_tbc_frames
        from src.utils.frame_utils import create_empty_frame
        base_frame = create_empty_frame(width=160, height=144)
        frames = generate_tbc_frames(base_frame, duration_frames=5, end_hold_frames=5)
        assert len(frames) == 10
        for f in frames:
            assert f.shape == base_frame.shape

    def test_generate_tbc_frames_returns_numpy_arrays(self):
        """Test that returned frames are numpy arrays."""
        from src.utils.frame_utils import generate_tbc_frames
        from src.utils.frame_utils import create_empty_frame
        from numpy import ndarray
        base_frame = create_empty_frame()
        frames = generate_tbc_frames(base_frame, duration_frames=5)
        for f in frames:
            assert isinstance(f, ndarray)

    def test_generate_tbc_frames_handles_missing_overlay(self, tmp_path, monkeypatch):
        """Test graceful handling when overlay file is missing."""
        from src.utils.frame_utils import generate_tbc_frames
        from src.utils.frame_utils import create_empty_frame
        from pathlib import Path
        base_frame = create_empty_frame()
        monkeypatch.setattr(Path, 'exists', lambda self: False)
        result = generate_tbc_frames(base_frame, overlay_path=Path("/nonexistent.png"))
        assert result == []  # Should gracefully return empty list


class TestSaveFramesAsGif:
    """Test AVIF encoding functionality."""

    def test_gif_magic_bytes(self):
        frames = [create_empty_frame(width=320, height=288, color=(i * 80, 0, 0)) for i in range(3)]
        gif_buffer = save_frames_as_avif(frames, fps=10)
        gif_buffer.seek(4)
        header = gif_buffer.read(8)
        assert header == b"ftypavis"

    def test_gif_non_empty_output(self):
        frames = [create_empty_frame(width=320, height=288) for _ in range(3)]
        gif_buffer = save_frames_as_avif(frames, fps=10)
        assert len(gif_buffer.getvalue()) > 0

    def test_gif_empty_frames_raises(self):
        with pytest.raises(ValueError, match="No frames provided"):
            save_frames_as_avif([])

    def test_gif_buffer_seeked_to_zero(self):
        frames = [create_empty_frame(width=320, height=288) for _ in range(2)]
        gif_buffer = save_frames_as_avif(frames, fps=10)
        assert gif_buffer.tell() == 0

    def test_gif_black_pixels_not_transparent(self):
        """Regression: black pixels must not render as transparent in multi-frame AVIF."""
        black = create_empty_frame(width=320, height=288, color=(0, 0, 0))
        white = create_empty_frame(width=320, height=288, color=(255, 255, 255))
        frames = [black, white, black]

        gif_buffer = save_frames_as_avif(frames, fps=10)
        gif_buffer.seek(0)
        gif = Image.open(gif_buffer)

        for frame_idx in range(3):
            gif.seek(frame_idx)
            rgba = gif.convert("RGBA")
            pixels = np.array(rgba)
            if frame_idx % 2 == 0:
                assert np.all(pixels[:, :, 3] == 255), (
                    f"Frame {frame_idx}: black pixels have unexpected transparency"
                )


class TestHexToRgb:
    def test_white(self):
        assert hex_to_rgb("#FFFFFF") == (255, 255, 255)

    def test_red(self):
        assert hex_to_rgb("#FF0000") == (255, 0, 0)

    def test_green(self):
        assert hex_to_rgb("#00FF00") == (0, 255, 0)

    def test_blue(self):
        assert hex_to_rgb("#0000FF") == (0, 0, 255)

    def test_yellow(self):
        assert hex_to_rgb("#FFFF00") == (255, 255, 0)

    def test_magenta(self):
        assert hex_to_rgb("#FF00FF") == (255, 0, 255)

    def test_cyan(self):
        assert hex_to_rgb("#00FFFF") == (0, 255, 255)

    def test_no_hash(self):
        assert hex_to_rgb("FF0000") == (255, 0, 0)


class TestRenderInputSidebarUserColors:
    def _make_inputs(self):
        return [{"user_name": "Alice", "button": "a", "total_score": 10}]

    def test_defaults_to_white_when_no_user_colors(self):
        # Should not raise; white is used
        sidebar = render_input_sidebar(self._make_inputs(), user_colors=None)
        assert sidebar is not None

    def test_uses_provided_color(self):
        # Red Alice vs white Alice — sidebars should differ
        red = render_input_sidebar(
            self._make_inputs(), user_colors={"Alice": (255, 0, 0)}
        )
        white = render_input_sidebar(
            self._make_inputs(), user_colors={"Alice": (255, 255, 255)}
        )
        assert not (red == white).all()

    def test_falls_back_to_white_for_missing_key(self):
        # Should not raise when user_name not in dict
        sidebar = render_input_sidebar(
            self._make_inputs(), user_colors={"Bob": (255, 0, 0)}
        )
        assert sidebar is not None


class TestRenderInputSidebarStreak:
    """Tests for streak badge rendering in render_input_sidebar."""

    def test_no_streak_field_no_crash(self):
        """Entry without current_streak key renders without error."""
        result = render_input_sidebar([{"user_name": "Foo", "button": "a"}])
        assert result.shape == (432, 372, 3)
        assert result.dtype.name == "uint8"

    def test_streak_zero_no_badge(self):
        """current_streak=0 renders like no streak (no badge)."""
        result = render_input_sidebar([{"user_name": "Foo", "button": "a", "current_streak": 0}])
        assert result.shape == (432, 372, 3)

    def test_streak_one_no_badge(self):
        """current_streak=1 renders without badge."""
        result = render_input_sidebar([{"user_name": "Foo", "button": "a", "current_streak": 1}])
        assert result.shape == (432, 372, 3)

    def test_streak_greater_than_one_no_crash(self):
        """current_streak=3 renders without crash and produces correct shape."""
        result = render_input_sidebar([{"user_name": "John Doe", "button": "start", "current_streak": 3}])
        assert result.shape == (432, 372, 3)
        assert result.dtype.name == "uint8"

    def test_streak_icon_missing_still_renders(self, tmp_path, monkeypatch):
        """If streak_icon.png is absent, rendering still succeeds."""
        import src.utils.frame_utils as fu
        # Clear the cache so the monkeypatched path is evaluated
        fu._streak_icon_cache.clear()
        # Point assets dir to tmp_path (no streak_icon.png there)
        monkeypatch.setattr(
            fu,
            "_load_streak_icon",
            lambda h: None,
        )
        result = render_input_sidebar([{"user_name": "Bar", "button": "b", "current_streak": 5}])
        assert result.shape == (432, 372, 3)

    def test_multiple_entries_mixed_streaks(self):
        """Multiple entries with mixed streak values render without crash."""
        inputs = [
            {"user_name": "Alice", "button": "a", "current_streak": 0},
            {"user_name": "Bob", "button": "b", "current_streak": 7},
            {"user_name": "Charlie", "button": "start"},
        ]
        result = render_input_sidebar(inputs)
        assert result.shape == (432, 372, 3)


class TestMakeReactionFrameTransform:
    """Tests for _make_reaction_frame_transform."""

    def _frame(self, h=432, w=480):
        return np.zeros((h, w, 3), dtype=np.uint8)

    def test_no_reactions_returns_identity(self):
        """Empty reaction list returns a transform that passes the frame through unchanged."""
        fn = _make_reaction_frame_transform([], capture_fps=15, frame_skip=1)
        frame = self._frame()
        result = fn(frame, 0)
        assert result is frame

    def test_returns_callable(self):
        """With reactions, a callable is returned."""
        reactions = [{"reaction_type": "heart", "user_name": "Alice"}]
        fn = _make_reaction_frame_transform(reactions, capture_fps=15, frame_skip=1)
        assert callable(fn)

    def test_frame_outside_animation_window_unchanged(self):
        """A frame whose index falls outside all reaction animation windows is returned as-is."""
        reactions = [{"reaction_type": "heart", "user_name": "Alice"}]
        fn = _make_reaction_frame_transform(reactions, capture_fps=15, frame_skip=1)
        frame = self._frame()
        # start_frame is 0; anim_total is 25 — frame 100 is outside the window
        result = fn(frame, 100)
        # No copy should have been made (identity or equal)
        assert np.array_equal(result, frame)

    def test_frame_inside_animation_window_is_copied(self, tmp_path):
        """A frame index inside the reaction window produces a copy (original untouched)."""
        # Write a tiny fake reaction asset so the asset load succeeds
        asset_path = tmp_path / "reaction_heart.png"
        Image.fromarray(np.full((32, 32, 4), 200, dtype=np.uint8)).save(str(asset_path))

        reactions = [{"reaction_type": "heart", "user_name": "Alice"}]
        fn = _make_reaction_frame_transform(
            reactions, capture_fps=15, frame_skip=1, asset_dir=tmp_path
        )
        frame = self._frame()
        original = frame.copy()
        result = fn(frame, 10)  # inside the 0..24 window
        # Original frame should not be mutated
        assert np.array_equal(frame, original)
        # Result is a separate array
        assert result is not frame

    def test_frame_skip_delays_start(self):
        """With frame_skip=2, reaction start frame is halved so the window shifts."""
        reactions = [{"reaction_type": "heart", "user_name": "Alice"}]
        fn_skip1 = _make_reaction_frame_transform(reactions, capture_fps=30, frame_skip=1)
        fn_skip2 = _make_reaction_frame_transform(reactions, capture_fps=30, frame_skip=2)
        frame = self._frame()

        # At logical index 0 both should be in-window (start_frame <= 0 for first reaction)
        # The schedule start_raw for first reaction is 0 in both cases; start_logical = 0 // skip
        result_skip1 = fn_skip1(frame, 0)
        result_skip2 = fn_skip2(frame, 0)
        # Both operate on index 0, within window — both return the frame (asset may be None)
        assert result_skip1 is not None
        assert result_skip2 is not None

    def test_multiple_reactions_all_processed(self, tmp_path):
        """Multiple reactions each get their own schedule entry."""
        for rtype in ("heart", "star"):
            asset_path = tmp_path / f"reaction_{rtype}.png"
            Image.fromarray(np.full((32, 32, 4), 150, dtype=np.uint8)).save(str(asset_path))

        reactions = [
            {"reaction_type": "heart", "user_name": "Alice"},
            {"reaction_type": "star", "user_name": "Bob"},
        ]
        fn = _make_reaction_frame_transform(
            reactions, capture_fps=15, frame_skip=1, asset_dir=tmp_path
        )
        # Should return a callable without error
        frame = self._frame()
        result = fn(frame, 5)
        assert result is not None

    def test_missing_asset_does_not_crash(self, tmp_path):
        """If the reaction asset file is missing, the frame is returned without modification."""
        reactions = [{"reaction_type": "nonexistent_type", "user_name": "X"}]
        fn = _make_reaction_frame_transform(
            reactions, capture_fps=15, frame_skip=1, asset_dir=tmp_path
        )
        frame = self._frame()
        result = fn(frame, 5)
        # No crash, frame returned
        assert np.array_equal(result, frame)


class TestSaveFramesAsMp4Streaming:
    """Tests for save_frames_as_mp4_streaming."""

    def _frames(self, count=3, h=144, w=160):
        return [np.full((h, w, 3), i * 40, dtype=np.uint8) for i in range(count)]

    def _identity_transform(self, frame, index):
        return frame

    @pytest.mark.asyncio
    async def test_raises_on_empty_frames(self, tmp_path):
        """ValueError is raised when frames iterable is empty."""
        with pytest.raises(ValueError, match="No frames"):
            await save_frames_as_mp4_streaming(
                iter([]), self._identity_transform, str(tmp_path / "out.mp4"), fps=10
            )

    @pytest.mark.asyncio
    async def test_transform_called_once_per_frame(self, tmp_path):
        """Transform is called exactly once per frame."""
        frames = self._frames(4)
        call_indices = []

        def counting_transform(frame, index):
            call_indices.append(index)
            return frame

        async def fake_subprocess(*cmd, **kwargs):
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess):
            await save_frames_as_mp4_streaming(
                iter(frames), counting_transform, str(tmp_path / "out.mp4"), fps=10
            )

        assert call_indices == list(range(4))

    @pytest.mark.asyncio
    async def test_ffmpeg_command_includes_an_without_audio(self, tmp_path):
        """Without audio_chunks, FFmpeg command includes -an."""
        captured_cmd = []

        async def fake_subprocess(*cmd, **kwargs):
            captured_cmd.extend(cmd)
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess):
            await save_frames_as_mp4_streaming(
                iter(self._frames()), self._identity_transform,
                str(tmp_path / "out.mp4"), fps=10
            )

        assert "-an" in captured_cmd
        assert "-c:a" not in captured_cmd

    @pytest.mark.asyncio
    async def test_ffmpeg_command_includes_audio_flags_with_audio(self, tmp_path):
        """With audio_chunks, FFmpeg command includes PCM input and -c:a aac."""
        captured_cmd = []

        async def fake_subprocess(*cmd, **kwargs):
            captured_cmd.extend(cmd)
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        audio_chunks = [np.zeros((100, 2), dtype=np.int8) for _ in range(3)]

        with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess):
            await save_frames_as_mp4_streaming(
                iter(self._frames()), self._identity_transform,
                str(tmp_path / "out.mp4"), fps=10,
                audio_chunks=audio_chunks,
            )

        assert "-f" in captured_cmd
        f_indices = [i for i, v in enumerate(captured_cmd) if v == "-f"]
        assert any(captured_cmd[i + 1] == "s16le" for i in f_indices)
        assert "-c:a" in captured_cmd
        aac_idx = captured_cmd.index("-c:a")
        assert captured_cmd[aac_idx + 1] == "aac"
        assert "-an" not in captured_cmd

    @pytest.mark.asyncio
    async def test_audio_pcm_temp_file_cleaned_up(self, tmp_path):
        """Temporary PCM file is deleted after encoding, even on success."""
        created_pcm = []

        original_NamedTemporaryFile = __import__('tempfile').NamedTemporaryFile

        def tracking_ntf(**kwargs):
            f = original_NamedTemporaryFile(**kwargs)
            if kwargs.get('suffix') == '.pcm':
                created_pcm.append(f.name)
            return f

        async def fake_subprocess(*cmd, **kwargs):
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        audio_chunks = [np.zeros((50, 2), dtype=np.int8)]

        with patch("tempfile.NamedTemporaryFile", side_effect=tracking_ntf):
            with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess):
                await save_frames_as_mp4_streaming(
                    iter(self._frames()), self._identity_transform,
                    str(tmp_path / "out.mp4"), fps=10,
                    audio_chunks=audio_chunks,
                )

        # All created PCM temp files should have been deleted
        import os
        for pcm_path in created_pcm:
            assert not os.path.exists(pcm_path)

    @pytest.mark.asyncio
    async def test_raises_on_ffmpeg_nonzero_return(self, tmp_path):
        """RuntimeError is raised when FFmpeg returns non-zero exit code."""
        async def fake_subprocess(*cmd, **kwargs):
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.returncode = 1
            proc.communicate = AsyncMock(return_value=(b"", b"encode error"))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess):
            with pytest.raises(RuntimeError, match="FFmpeg streaming encode failed"):
                await save_frames_as_mp4_streaming(
                    iter(self._frames()), self._identity_transform,
                    str(tmp_path / "out.mp4"), fps=10
                )

    @pytest.mark.asyncio
    async def test_low_priority_sets_preexec_fn(self, tmp_path):
        """low_priority=True passes preexec_fn to subprocess."""
        captured_kwargs = {}

        async def fake_subprocess(*cmd, **kwargs):
            captured_kwargs.update(kwargs)
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess):
            await save_frames_as_mp4_streaming(
                iter(self._frames()), self._identity_transform,
                str(tmp_path / "out.mp4"), fps=10, low_priority=True
            )

        assert "preexec_fn" in captured_kwargs

    @pytest.mark.asyncio
    async def test_output_dimensions_derived_from_transform(self, tmp_path):
        """FFmpeg -s argument reflects the output shape from the transform."""
        captured_cmd = []

        async def fake_subprocess(*cmd, **kwargs):
            captured_cmd.extend(cmd)
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        # Transform doubles the width
        def doubling_transform(frame, index):
            from PIL import Image
            h, w = frame.shape[:2]
            return np.array(Image.fromarray(frame).resize((w * 2, h)))

        frames = [np.zeros((144, 160, 3), dtype=np.uint8)]

        with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess):
            await save_frames_as_mp4_streaming(
                iter(frames), doubling_transform,
                str(tmp_path / "out.mp4"), fps=10
            )

        s_idx = captured_cmd.index("-s")
        assert captured_cmd[s_idx + 1] == "320x144"  # 160*2 x 144


class TestRenderStatusBar:
    """Tests for render_status_bar()."""

    def test_shape_with_none_data_scale3(self):
        """Returns correct shape (48, 768, 3) when data is None at scale=3."""
        import numpy as np
        from src.utils.frame_utils import render_status_bar

        result = render_status_bar(None, width=768, scale=3)

        assert result.shape == (48, 768, 3)
        assert result.dtype == np.uint8

    def test_shape_with_none_data_scale2(self):
        """Returns correct shape (32, 512, 3) when data is None at scale=2."""
        import numpy as np
        from src.utils.frame_utils import render_status_bar

        result = render_status_bar(None, width=512, scale=2)

        assert result.shape == (32, 512, 3)

    def test_blank_strip_when_data_none(self):
        """Returns a dark strip when data is None (no text rendered)."""
        import numpy as np
        from src.utils.frame_utils import render_status_bar

        result = render_status_bar(None, width=768, scale=3)

        # Should be a uniform dark color — no bright pixels
        assert result.max() < 50

    def test_shape_with_data(self):
        """Returns correct shape when given valid data dict."""
        import numpy as np
        from src.utils.frame_utils import render_status_bar

        data = {
            "foo": "bar",
        }
        result = render_status_bar(data, width=768, scale=3)

        assert result.shape == (48, 768, 3)
        assert result.dtype == np.uint8

    def test_render_fn(self):
        """Status bar with valid data and a render_fn contains white text pixels."""
        import numpy as np
        from src.utils.frame_utils import render_status_bar
        
        render_fn = MagicMock()

        data = {
            "foo": "bar"
        }
        result = render_status_bar(data, width=768, scale=3, render_fn=render_fn)

        # Should have called render_fn
        render_fn.assert_called_once()
        call_args = render_fn.call_args
        assert call_args[0][1] == data
        assert call_args[0][2] == 3


class TestRenderInputSidebarModifier:
    def test_modifier_changes_rendered_output(self):
        """render_input_sidebar produces different pixels when modifier is present vs absent."""
        base = render_input_sidebar(
            inputs=[{"user_name": "Alice", "button": "up", "modifier": None, "current_streak": 0}],
            scale=1,
        )
        with_mod = render_input_sidebar(
            inputs=[{"user_name": "Alice", "button": "up", "modifier": "b", "current_streak": 0}],
            scale=1,
        )
        assert not np.array_equal(base, with_mod)

    def test_no_modifier_unchanged(self):
        """render_input_sidebar with modifier=None produces the same output as no modifier key."""
        without_key = render_input_sidebar(
            inputs=[{"user_name": "Bob", "button": "up", "current_streak": 0}],
            scale=1,
        )
        with_none = render_input_sidebar(
            inputs=[{"user_name": "Bob", "button": "up", "modifier": None, "current_streak": 0}],
            scale=1,
        )
        assert np.array_equal(without_key, with_none)

    def test_render_input_sidebar_with_modifier_renders(self):
        """render_input_sidebar accepts modifier in entries and returns an array."""
        result = render_input_sidebar(
            inputs=[{"user_name": "Alice", "button": "up", "modifier": "b", "current_streak": 0}],
            scale=1,
        )
        assert isinstance(result, np.ndarray)
        assert result.shape[2] == 3
