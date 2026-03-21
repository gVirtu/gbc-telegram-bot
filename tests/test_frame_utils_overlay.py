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


class TestApplyOverlayComposite:
    def test_output_length_matches_input(self):
        """Returns same number of frames as input."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(5)]
        result = apply_overlay_composite(frames, [], [])
        assert len(result) == 5

    def test_output_shape_is_composited(self):
        """Each output frame has sidebar width added (288×320 → 288×512)."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(3)]
        result = apply_overlay_composite(frames, [], [])
        for f in result:
            assert f.shape == (288, 512, 3)

    def test_sidebar_empty_before_offset(self):
        """Sidebar area is all-black on frames before an input's offset."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(3)]
        new_input = {
            "user_name": "Alice", "button": "a",
            "user_id": 1, "timestamp": "2026-01-01T00:00:00",
        }
        result = apply_overlay_composite(frames, [], [(new_input, 2)])

        # Before offset: sidebar (columns 320+) below date row should be black
        assert not np.any(result[0][24:, 320:, :] > 10)
        assert not np.any(result[1][24:, 320:, :] > 10)

    def test_sidebar_has_text_at_and_after_offset(self):
        """Sidebar area has white pixels on the frame where input arrives."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(3)]
        new_input = {
            "user_name": "Alice", "button": "a",
            "user_id": 1, "timestamp": "2026-01-01T00:00:00",
        }
        result = apply_overlay_composite(frames, [], [(new_input, 2)])
        assert np.any(result[2][24:, 320:, :] > 10)

    def test_pre_existing_inputs_visible_from_frame_0(self):
        """Pre-existing inputs appear in the sidebar from frame 0."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(2)]
        pre = [{"user_name": "Bob", "button": "b", "user_id": 2, "timestamp": "2026-01-01T00:00:00"}]
        result = apply_overlay_composite(frames, pre, [])
        # Frame 0 sidebar should already have text
        assert np.any(result[0][24:, 320:, :] > 10)

    def test_multiple_inputs_at_different_offsets(self):
        """Two inputs at offsets 1 and 3: frame 0 empty, frame 1 has one, frame 3 has both."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(4)]
        input_a = {"user_name": "A", "button": "a", "user_id": 1, "timestamp": "2026-01-01T00:00:00"}
        input_b = {"user_name": "B", "button": "b", "user_id": 2, "timestamp": "2026-01-01T00:00:01"}

        result = apply_overlay_composite(frames, [], [(input_a, 1), (input_b, 3)])

        def sidebar_white_pixel_count(f):
            return int(np.sum(f[24:, 320:, :] > 10))

        count_0 = sidebar_white_pixel_count(result[0])
        count_1 = sidebar_white_pixel_count(result[1])
        count_3 = sidebar_white_pixel_count(result[3])

        assert count_0 == 0, "Frame 0: no inputs yet, sidebar should be black"
        assert count_1 > 0, "Frame 1: input_a arrives, sidebar should have text"
        assert count_3 > count_1, "Frame 3: input_b arrives, sidebar should have more text"
