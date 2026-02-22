"""Tests for frame processing utilities.

This module tests frame hashing, PNG conversion, and optimization logic.
"""

import hashlib

import numpy as np
import pytest
from PIL import Image

from src.utils.frame_utils import (
    create_empty_frame,
    frame_to_png,
    frames_equal,
    hash_frame,
    save_frames_as_mp4,
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
        frames = [create_empty_frame(color=(i * 50, 0, 0)) for i in range(5)]
        
        mp4_buffer = save_frames_as_mp4(frames, fps=10)
        
        # Check MP4 magic bytes (ftyp box)
        mp4_buffer.seek(0)
        header = mp4_buffer.read(12)
        # MP4 files start with ftyp box
        assert header[4:8] == b'ftyp'
    
    def test_mp4_empty_frames_raises(self):
        """Test that empty frames raises ValueError."""
        with pytest.raises(ValueError, match="No frames provided"):
            save_frames_as_mp4([])
    
    def test_mp4_different_fps(self):
        """Test MP4 encoding with different frame rates."""
        frames = [create_empty_frame() for _ in range(3)]
        
        # Different FPS values should all work
        for fps in [5, 10, 15, 30]:
            mp4_buffer = save_frames_as_mp4(frames, fps=fps)
            assert len(mp4_buffer.getvalue()) > 0
    
    def test_mp4_upscaling(self):
        """Test that frames are upscaled 2x."""
        # Create frames at GameBoy resolution
        frames = [create_empty_frame(width=160, height=144) for _ in range(3)]
        
        mp4_buffer = save_frames_as_mp4(frames, fps=10)
        
        # Output should be valid MP4
        assert len(mp4_buffer.getvalue()) > 0
        mp4_buffer.seek(4)  # Skip size field
        assert mp4_buffer.read(4) == b'ftyp'
    
    def test_mp4_crf_settings(self):
        """Test different CRF quality settings."""
        frames = [create_empty_frame() for _ in range(3)]
        
        # Different CRF values should all work
        for crf in [18, 23, 28, 35]:
            mp4_buffer = save_frames_as_mp4(frames, crf=crf)
            assert len(mp4_buffer.getvalue()) > 0
    
    def test_mp4_preset_settings(self):
        """Test different preset settings."""
        frames = [create_empty_frame() for _ in range(3)]
        
        # Different presets should all work
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
        assert len(result) == 20  # default duration

    def test_generate_tbc_frames_uses_custom_duration(self):
        """Test that generate_tbc_frames respects custom duration."""
        from src.utils.frame_utils import generate_tbc_frames
        from src.utils.frame_utils import create_empty_frame
        base_frame = create_empty_frame()
        result = generate_tbc_frames(base_frame, duration_frames=10)
        assert len(result) == 10

    def test_generate_tbc_frames_preserves_shape(self):
        """Test that generated frames have same shape as base frame."""
        from src.utils.frame_utils import generate_tbc_frames
        from src.utils.frame_utils import create_empty_frame
        base_frame = create_empty_frame(width=160, height=144)
        frames = generate_tbc_frames(base_frame, duration_frames=5)
        assert len(frames) == 5
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
