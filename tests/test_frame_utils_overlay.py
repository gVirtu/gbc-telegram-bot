"""Tests for frame_utils overlay functions: render_input_sidebar and composite_overlay."""

import numpy as np
import pytest

from src.utils.frame_utils import composite_overlay, render_input_sidebar


class TestRenderInputSidebar:
    def test_render_input_sidebar_empty_inputs(self):
        """Empty list should return a black image with correct shape."""
        result = render_input_sidebar([], width=192, height=288)
        assert result.shape == (288, 192, 3)
        assert result.dtype == np.uint8
        # All pixels below the date should be black (0, 0, 0)
        region = result[24:, :, :]
        assert np.all(region == 0)

    def test_render_input_sidebar_single_input(self):
        """One input renders text, so non-black pixels should be present."""
        inputs = [{"user_name": "Alice", "button": "left"}]
        result = render_input_sidebar(inputs, width=192, height=288)
        assert result.shape == (288, 192, 3)
        # Should have some white (non-zero) pixels from the rendered text
        region = result[24:, :, :]
        assert np.any(region > 0)

    def test_render_input_sidebar_overflow_stops_at_top(self):
        """With 100+ inputs, image height should still be 288 (no overflow)."""
        inputs = [{"user_name": f"User{i}", "button": "a"} for i in range(150)]
        result = render_input_sidebar(inputs, width=192, height=288)
        assert result.shape == (288, 192, 3)

    def test_render_input_sidebar_button_chars(self):
        """Button values should map to correct characters."""
        # We test by checking the function accepts these button values and returns correct shape
        button_map = {
            "left": "←",
            "up": "↑",
            "right": "→",
            "down": "↓",
            "a": "A",
            "b": "B",
            "start": "START",
            "select": "SELECT",
            "wait": "…",
        }
        for button_val, expected_char in button_map.items():
            inputs = [{"user_name": "User", "button": button_val}]
            result = render_input_sidebar(inputs, width=192, height=288)
            assert result.shape == (288, 192, 3), f"Wrong shape for button '{button_val}'"
            # Non-black pixels should be present (text rendered)
            region = result[24:, :, :]
            assert np.any(region > 0), f"No text rendered for button '{button_val}'"


class TestCompositeOverlay:
    def test_composite_overlay_output_shape(self):
        """game_frame 320x288 + sidebar 192x288 should give 512x288 output."""
        game_frame = np.zeros((288, 320, 3), dtype=np.uint8)
        sidebar = np.ones((288, 192, 3), dtype=np.uint8) * 128
        result = composite_overlay(game_frame, sidebar)
        assert result.shape == (288, 512, 3)

    def test_composite_overlay_game_frame_on_left(self):
        """Game frame pixels should be on the left side of the composite."""
        game_frame = np.zeros((288, 320, 3), dtype=np.uint8)
        # Mark game frame with a distinctive color
        game_frame[:, :, 0] = 200  # Red channel = 200
        sidebar = np.ones((288, 192, 3), dtype=np.uint8) * 128

        result = composite_overlay(game_frame, sidebar)
        # Left portion (0:320) should have red channel = 200
        assert np.all(result[:, :320, 0] == 200)
        assert np.all(result[:, :320, 1] == 0)
        assert np.all(result[:, :320, 2] == 0)

    def test_composite_overlay_sidebar_on_right(self):
        """Sidebar pixels should be on the right side of the composite."""
        game_frame = np.zeros((288, 320, 3), dtype=np.uint8)
        sidebar = np.ones((288, 192, 3), dtype=np.uint8) * 128

        result = composite_overlay(game_frame, sidebar)
        # Right portion (320:512) should be 128 on all channels
        assert np.all(result[:, 320:, :] == 128)

    def test_composite_overlay_height_padding(self):
        """If heights differ, shorter side should be padded with black."""
        game_frame = np.ones((288, 320, 3), dtype=np.uint8) * 50
        sidebar = np.ones((200, 192, 3), dtype=np.uint8) * 128

        result = composite_overlay(game_frame, sidebar)
        # Output height should be max of 288 and 200 = 288
        assert result.shape == (288, 512, 3)
        # The sidebar padding area (200:288, 320:) should be black
        assert np.all(result[200:, 320:, :] == 0)
