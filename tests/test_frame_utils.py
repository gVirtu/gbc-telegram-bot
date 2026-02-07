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
    get_frame_info,
    hash_frame,
    should_update_frame,
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
        assert image.size == (160, 144)
    
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

        assert image.size == (width, height)

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


class TestGetFrameInfo:
    """Test frame info extraction."""
    
    def test_basic_info(self):
        """Test basic frame info extraction."""
        frame = np.zeros((144, 160, 3), dtype=np.uint8)
        height, width, dtype = get_frame_info(frame)
        
        assert height == 144
        assert width == 160
        assert dtype == "uint8"
    
    def test_different_sizes(self):
        """Test info extraction for different sizes."""
        frame = np.zeros((200, 300, 3), dtype=np.uint16)
        height, width, dtype = get_frame_info(frame)
        
        assert height == 200
        assert width == 300
        assert dtype == "uint16"


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


class TestShouldUpdateFrame:
    """Test frame update decision logic."""
    
    def test_first_frame_always_updates(self):
        """Test that first frame (no last_hash) always updates."""
        frame = create_empty_frame()
        
        should_update, current_hash = should_update_frame(frame, None)
        
        assert should_update is True
        assert len(current_hash) == 64
    
    def test_same_frame_no_update(self):
        """Test that identical frame doesn't need update."""
        frame = create_empty_frame()
        
        # First call - should update
        should_update, last_hash = should_update_frame(frame, None)
        assert should_update is True
        
        # Second call with same frame - should not update
        should_update, current_hash = should_update_frame(frame, last_hash)
        assert should_update is False
        assert current_hash == last_hash
    
    def test_different_frame_needs_update(self):
        """Test that different frame needs update."""
        frame1 = create_empty_frame(color=(255, 0, 0))  # Red
        frame2 = create_empty_frame(color=(0, 255, 0))  # Green
        
        # First frame
        should_update, last_hash = should_update_frame(frame1, None)
        assert should_update is True
        
        # Different frame
        should_update, current_hash = should_update_frame(frame2, last_hash)
        assert should_update is True
        assert current_hash != last_hash
    
    def test_returns_current_hash(self):
        """Test that function returns hash for storage."""
        frame = create_empty_frame()
        
        _, current_hash = should_update_frame(frame, None)
        
        # Hash should match direct hashing
        assert current_hash == hash_frame(frame)


class TestIntegration:
    """Integration tests for frame processing pipeline."""
    
    def test_full_pipeline(self):
        """Test the complete frame processing pipeline."""
        # Create a frame
        frame = create_empty_frame(color=(100, 150, 200))
        
        # Check if we should update (first frame)
        should_update, frame_hash = should_update_frame(frame, None)
        assert should_update is True
        
        # Convert to PNG
        png_buffer = frame_to_png(frame)
        assert len(png_buffer.getvalue()) > 0
        
        # Verify PNG is valid
        png_buffer.seek(0)
        image = Image.open(png_buffer)
        assert image.size == (160, 144)
        
        # Same frame should not need update
        should_update, new_hash = should_update_frame(frame, frame_hash)
        assert should_update is False
        assert new_hash == frame_hash
    
    def test_optimization_saves_bandwidth(self):
        """Test that frame deduplication would save bandwidth."""
        # Simulate 10 identical frames
        frame = create_empty_frame()
        last_hash = None
        updates_needed = 0
        
        for _ in range(10):
            should_update, last_hash = should_update_frame(frame, last_hash)
            if should_update:
                updates_needed += 1
        
        # Only first frame should need update
        assert updates_needed == 1
    
    def test_changing_frames_need_updates(self):
        """Test that sequence of different frames all need updates."""
        last_hash = None
        updates_needed = 0
        
        for i in range(5):
            # Create slightly different frames
            frame = create_empty_frame(color=(i * 50, 0, 0))
            should_update, last_hash = should_update_frame(frame, last_hash)
            if should_update:
                updates_needed += 1
        
        # All 5 frames are different, all need updates
        assert updates_needed == 5
