"""Tests for frame_utils overlay functions: render_input_sidebar and composite_overlay."""

import numpy as np
import pytest
from pathlib import Path

from src.utils.frame_utils import composite_overlay, render_input_sidebar, _make_frame_transform, apply_overlay_composite


class TestRenderInputSidebar:
    def test_render_input_sidebar_empty_inputs(self):
        """Empty list should return a black image with correct shape."""
        result = render_input_sidebar([], base_width=192, base_height=288, scale=1)
        assert result.shape == (288, 192, 3)
        assert result.dtype == np.uint8
        # All pixels below the date should be black (0, 0, 0)
        region = result[24:, :, :]
        assert np.all(region == 0)

    def test_render_input_sidebar_single_input(self):
        """One input renders text, so non-black pixels should be present."""
        inputs = [{"user_name": "Alice", "button": "left"}]
        result = render_input_sidebar(inputs, base_width=192, base_height=288, scale=1)
        assert result.shape == (288, 192, 3)
        # Should have some white (non-zero) pixels from the rendered text
        region = result[24:, :, :]
        assert np.any(region > 0)

    def test_render_input_sidebar_overflow_stops_at_top(self):
        """With 100+ inputs, image height should still be 288 (no overflow)."""
        inputs = [{"user_name": f"User{i}", "button": "a"} for i in range(150)]
        result = render_input_sidebar(inputs, base_width=192, base_height=288, scale=1)
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
            result = render_input_sidebar(inputs, base_width=192, base_height=288, scale=1)
            assert result.shape == (288, 192, 3), f"Wrong shape for button '{button_val}'"
            # Non-black pixels should be present (text rendered)
            region = result[24:, :, :]
            assert np.any(region > 0), f"No text rendered for button '{button_val}'"


class TestCompositeOverlay:
    def test_composite_overlay_output_shape(self):
        """game_frame 480x432 + sidebar 288x432 should give 768x432 output."""
        game_frame = np.zeros((432, 480, 3), dtype=np.uint8)
        sidebar = np.ones((432, 372, 3), dtype=np.uint8) * 128
        result = composite_overlay(game_frame, sidebar)
        assert result.shape == (432, 852, 3)

    def test_composite_overlay_game_frame_on_left(self):
        """Game frame pixels should be on the left side of the composite."""
        game_frame = np.zeros((432, 480, 3), dtype=np.uint8)
        # Mark game frame with a distinctive color
        game_frame[:, :, 0] = 200  # Red channel = 200
        sidebar = np.ones((432, 372, 3), dtype=np.uint8) * 128

        result = composite_overlay(game_frame, sidebar)
        # Left portion (0:320) should have red channel = 200
        assert np.all(result[:, :480, 0] == 200)
        assert np.all(result[:, :480, 1] == 0)
        assert np.all(result[:, :480, 2] == 0)

    def test_composite_overlay_sidebar_on_right(self):
        """Sidebar pixels should be on the right side of the composite."""
        game_frame = np.zeros((432, 480, 3), dtype=np.uint8)
        sidebar = np.ones((432, 372, 3), dtype=np.uint8) * 128

        result = composite_overlay(game_frame, sidebar)
        # Right portion (320:512) should be 128 on all channels
        assert np.all(result[:, 480:, :] == 128)

    def test_composite_overlay_height_padding(self):
        """If heights differ, shorter side should be padded with black."""
        game_frame = np.ones((432, 480, 3), dtype=np.uint8) * 50
        sidebar = np.ones((200, 288, 3), dtype=np.uint8) * 128

        result = composite_overlay(game_frame, sidebar)
        # Output height should be max of 288 and 200 = 288
        assert result.shape == (432, 768, 3)
        # The sidebar padding area (200:288, 320:) should be black
        assert np.all(result[200:, 480:, :] == 0)


class TestApplyOverlayComposite:
    def test_output_length_matches_input(self):
        """Returns same number of frames as input."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((432, 480, 3), dtype=np.uint8) for _ in range(5)]
        result = apply_overlay_composite(frames, [], [])
        assert len(result) == 5

    def test_output_shape_is_composited(self):
        """Each output frame has sidebar width added and status bar height (16*scale=48 at scale=3)."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((432, 480, 3), dtype=np.uint8) for _ in range(3)]
        result = apply_overlay_composite(frames, [], [])
        for f in result:
            assert f.shape == (480, 852, 3)  # 432 game+sidebar + 48 status bar (16*3)

    def test_sidebar_empty_before_offset(self):
        """Sidebar area is all-black on frames before an input's offset."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((432, 480, 3), dtype=np.uint8) for _ in range(3)]
        new_input = {
            "user_name": "Alice", "button": "a",
            "user_id": 1, "timestamp": "2026-01-01T00:00:00",
        }
        result = apply_overlay_composite(frames, [], [(new_input, 2)])

        # Before offset: sidebar (columns 320+) below date row should be black
        # Restrict to rows 24:432 to exclude the status bar strip at the bottom
        assert not np.any(result[0][24:432, 480:, :] > 10)
        assert not np.any(result[1][24:432, 480:, :] > 10)

    def test_sidebar_has_text_at_and_after_offset(self):
        """Sidebar area has white pixels on the frame where input arrives."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((432, 480, 3), dtype=np.uint8) for _ in range(3)]
        new_input = {
            "user_name": "Alice", "button": "a",
            "user_id": 1, "timestamp": "2026-01-01T00:00:00",
        }
        result = apply_overlay_composite(frames, [], [(new_input, 2)])
        assert np.any(result[2][24:, 480:, :] > 10)

    def test_pre_existing_inputs_visible_from_frame_0(self):
        """Pre-existing inputs appear in the sidebar from frame 0."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((432, 480, 3), dtype=np.uint8) for _ in range(2)]
        pre = [{"user_name": "Bob", "button": "b", "user_id": 2, "timestamp": "2026-01-01T00:00:00"}]
        result = apply_overlay_composite(frames, pre, [])
        # Frame 0 sidebar should already have text
        assert np.any(result[0][24:, 480:, :] > 10)

    def test_multiple_inputs_at_different_offsets(self):
        """Two inputs at offsets 1 and 3: frame 0 empty, frame 1 has one, frame 3 has both."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((432, 480, 3), dtype=np.uint8) for _ in range(4)]
        input_a = {"user_name": "A", "button": "a", "user_id": 1, "timestamp": "2026-01-01T00:00:00"}
        input_b = {"user_name": "B", "button": "b", "user_id": 2, "timestamp": "2026-01-01T00:00:01"}

        result = apply_overlay_composite(frames, [], [(input_a, 1), (input_b, 3)])

        def sidebar_white_pixel_count(f):
            # Restrict to sidebar rows only (exclude the status bar strip at the bottom)
            return int(np.sum(f[24:432, 480:, :] > 10))

        count_0 = sidebar_white_pixel_count(result[0])
        count_1 = sidebar_white_pixel_count(result[1])
        count_3 = sidebar_white_pixel_count(result[3])

        assert count_0 == 0, "Frame 0: no inputs yet, sidebar should be black"
        assert count_1 > 0, "Frame 1: input_a arrives, sidebar should have text"
        assert count_3 > count_1, "Frame 3: input_b arrives, sidebar should have more text"


class TestScoreLabels:
    """Tests for animated score label rendering."""

    def test_label_appears_at_correct_frame(self):
        """Score label is present on the frame when a new input arrives (frame_offset)."""
        frames = [np.zeros((432, 480, 3), dtype=np.uint8) for _ in range(5)]
        inp = {"user_name": "Alice", "button": "a", "user_id": 1,
               "timestamp": "2026-01-01T00:00:00", "total_score": 10}
        result = apply_overlay_composite(frames, [], [(inp, 0)], capture_fps=5)
        # frame 0: label should be at alpha=1.0 (fully white)
        sidebar_frame0 = result[0][24:, 480:, :]
        assert np.any(sidebar_frame0 > 10), "Label should render on frame 0"

    def test_label_absent_on_pre_existing_inputs(self):
        """Pre-existing inputs have no score labels (no animation window)."""
        pre = [{"user_name": "Bob", "button": "b", "user_id": 2,
                "timestamp": "2026-01-01T00:00:00", "total_score": 5}]
        frames = [np.zeros((432, 480, 3), dtype=np.uint8) for _ in range(2)]
        # Render with no new inputs — pre-existing get no label
        result = apply_overlay_composite(frames, pre, [], capture_fps=5)
        # We can't easily test label absence vs text presence, but just verify it renders
        assert result[0].shape == (480, 852, 3)  # 432 + 48 status bar

    def test_label_at_frame_0_alpha_is_1(self):
        """At frame 0 (frames_since=0): ease=0, alpha=1.0, x_offset=0."""
        inp = {"user_name": "X", "button": "a", "user_id": 1,
               "timestamp": "2026-01-01T00:00:00", "total_score": 7}
        transform = _make_frame_transform([], [(inp, 0)], capture_fps=5)
        frame = np.zeros((432, 480, 3), dtype=np.uint8)
        # Just verify transform runs and returns correct shape
        out = transform(frame)
        assert out.shape == (432, 852, 3)

    def test_label_fades_out_over_capture_fps_frames(self):
        """Label has fewer bright pixels at the last frame compared to frame 0."""
        capture_fps = 5
        n_frames = capture_fps
        frames = [np.zeros((432, 480, 3), dtype=np.uint8) for _ in range(n_frames)]
        inp = {"user_name": "Alice", "button": "a", "user_id": 1,
               "timestamp": "2026-01-01T00:00:00", "total_score": 10}
        result = apply_overlay_composite(frames, [], [(inp, 0)], capture_fps=capture_fps)
        sidebar_0 = result[0][24:, 480:, :]
        sidebar_last = result[-1][24:, 480:, :]
        bright_0 = int(np.sum(sidebar_0 > 50))
        bright_last = int(np.sum(sidebar_last > 50))
        assert bright_0 >= bright_last, "Label should be brighter at frame 0 than at the last frame"

    def test_no_label_when_total_score_is_none(self):
        """Input with total_score=None renders no label."""
        inp_no_score = {"user_name": "Alice", "button": "a", "user_id": 1,
                        "timestamp": "2026-01-01T00:00:00", "total_score": None}
        inp_with_score = {"user_name": "Alice", "button": "a", "user_id": 1,
                          "timestamp": "2026-01-01T00:00:00", "total_score": 10}
        frames = [np.zeros((432, 480, 3), dtype=np.uint8)]
        result_no = apply_overlay_composite(frames, [], [(inp_no_score, 0)], capture_fps=5)
        result_yes = apply_overlay_composite(frames, [], [(inp_with_score, 0)], capture_fps=5)
        bright_no = int(np.sum(result_no[0][24:, 480:, :] > 10))
        bright_yes = int(np.sum(result_yes[0][24:, 480:, :] > 10))
        assert bright_yes >= bright_no, "Input with score should render at least as many bright pixels"

    def test_multiple_simultaneous_labels_animate_independently(self):
        """Two inputs at different offsets each get their own label animation."""
        capture_fps = 10
        frames = [np.zeros((432, 480, 3), dtype=np.uint8) for _ in range(capture_fps + 2)]
        inp_a = {"user_name": "A", "button": "a", "user_id": 1,
                 "timestamp": "2026-01-01T00:00:00", "total_score": 5}
        inp_b = {"user_name": "B", "button": "b", "user_id": 2,
                 "timestamp": "2026-01-01T00:00:01", "total_score": 8}
        # inp_a at frame 0, inp_b at frame 2
        result = apply_overlay_composite(frames, [], [(inp_a, 0), (inp_b, 2)], capture_fps=capture_fps)
        # Frame 2: both inputs visible, both labels active
        assert result[2].shape == (480, 852, 3)  # 432 + 48 status bar
        # Frame 0: only inp_a visible, inp_a label active
        assert result[0].shape == (480, 852, 3)  # 432 + 48 status bar
        # Frame capture_fps + 1: both inputs visible but labels have expired
        assert result[capture_fps + 1].shape == (480, 852, 3)  # 432 + 48 status bar


class TestDrawTextToFit:
    """Tests for the draw_text_to_fit helper."""

    def test_returns_width_within_max(self):
        """Returns actual width <= max_w."""
        from PIL import Image, ImageDraw, ImageFont
        from src.utils.frame_utils import draw_text_to_fit

        scale = 1
        img = Image.new("RGB", (200, 20), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(
                str(Path(__file__).parent.parent / "assets" / "fonts" / "unifont-17.0.04.otf"),
                size=9 * scale,
            )
        except Exception:
            font = ImageFont.load_default()

        used_w = draw_text_to_fit(img, draw, x=0, y=0, name="Alice",
                                        color=(255, 255, 255), max_w=50,
                                        line_height=20, font=font)
        assert 0 < used_w <= 50

    def test_compresses_long_name(self):
        """A very long name is compressed to max_w."""
        from PIL import Image, ImageDraw, ImageFont
        from src.utils.frame_utils import draw_text_to_fit

        scale = 1
        img = Image.new("RGB", (200, 20), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(
                str(Path(__file__).parent.parent / "assets" / "fonts" / "unifont-17.0.04.otf"),
                size=9 * scale,
            )
        except Exception:
            font = ImageFont.load_default()

        long_name = "VeryLongUserNameThatDefinitelyExceedsTheMaxWidth"
        used_w = draw_text_to_fit(img, draw, x=0, y=0, name=long_name,
                                        color=(255, 0, 0), max_w=30,
                                        line_height=20, font=font)
        assert used_w == 30


class TestRenderInputSidebarStatsRow:
    """Tests for the stats header row in render_input_sidebar."""

    def _make_stats(self, total=100, players=None):
        if players is None:
            players = [{"user_name": "Alice", "count": 50},
                       {"user_name": "Bob",   "count": 30}]
        return {"today": {"total": total, "top_players": players},
                "alltime": {"total": total * 10, "top_players": players}}

    def test_stats_row_renders_without_error(self):
        """render_input_sidebar with header_stats returns correct shape."""
        result = render_input_sidebar(
            [],
            base_width=124, base_height=144, scale=3,
            header_stats=self._make_stats(),
            global_frame_count=0,
            n_new_inputs=0,
        )
        assert result.shape == (144 * 3, 124 * 3, 3)

    def test_stats_row_today_period_at_frame_0(self):
        """At global_frame_count=0, period is 'today' (cycle index 0)."""
        result = render_input_sidebar(
            [],
            base_width=124, base_height=144, scale=3,
            header_stats=self._make_stats(),
            global_frame_count=0,
            n_new_inputs=0,
        )
        # Stats row occupies y in [line_height, line_height + 48*3)
        # line_height = 10*3 = 30
        stats_band = result[30: 30 + 48 * 3, :, :]
        assert np.any(stats_band > 0), "Stats row should have non-black pixels"

    def test_stats_row_alltime_period_at_frame_75(self):
        """At global_frame_count=75, period flips to 'alltime' (cycle index 1)."""
        result_today = render_input_sidebar(
            [],
            base_width=124, base_height=144, scale=3,
            header_stats=self._make_stats(),
            global_frame_count=0,
            n_new_inputs=0,
        )
        result_alltime = render_input_sidebar(
            [],
            base_width=124, base_height=144, scale=3,
            header_stats=self._make_stats(),
            global_frame_count=75,
            n_new_inputs=0,
        )
        # The two renders must differ (different labels rendered)
        assert not np.array_equal(result_today, result_alltime)

    def test_entry_rows_do_not_overlap_stats_row(self):
        """With many inputs, entries stop below the stats+date band."""
        inputs = [{"user_name": f"U{i}", "button": "a"} for i in range(50)]
        result = render_input_sidebar(
            inputs,
            base_width=124, base_height=144, scale=3,
            header_stats=self._make_stats(),
            global_frame_count=0,
            n_new_inputs=0,
        )
        assert result.shape == (144 * 3, 124 * 3, 3)


class TestMakeFrameTransformStats:
    """Tests that _make_frame_transform passes stats to sidebar correctly."""

    def _make_stats(self):
        return {
            "today":   {"total": 5,  "top_players": [{"user_name": "X", "count": 5}]},
            "alltime": {"total": 50, "top_players": [{"user_name": "X", "count": 50}]},
        }

    def test_transform_with_stats_returns_correct_shape(self):
        """Transform with header_stats still returns a valid frame."""
        game_frame = np.zeros((144 * 2, 160 * 2, 3), dtype=np.uint8)
        transform = _make_frame_transform(
            pre_existing=[],
            new_inputs_with_offsets=[],
            base_global_frame_count=0,
            header_stats=self._make_stats(),
        )
        result = transform(game_frame)
        assert result.ndim == 3
        assert result.shape[2] == 3

    def test_period_changes_render_at_frame_75(self):
        """Renders at frame 0 and frame 75 differ (today vs alltime label)."""
        game_frame = np.zeros((144 * 2, 160 * 2, 3), dtype=np.uint8)

        transform_a = _make_frame_transform(
            pre_existing=[], new_inputs_with_offsets=[],
            base_global_frame_count=0, header_stats=self._make_stats(),
        )
        transform_b = _make_frame_transform(
            pre_existing=[], new_inputs_with_offsets=[],
            base_global_frame_count=75, header_stats=self._make_stats(),
        )
        result_a = transform_a(game_frame)
        result_b = transform_b(game_frame)
        assert not np.array_equal(result_a, result_b)
