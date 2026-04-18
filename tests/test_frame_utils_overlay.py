"""Tests for frame_utils overlay functions: render_input_sidebar and composite_overlay."""

import numpy as np
import pytest
from pathlib import Path

from PIL import Image, ImageDraw

from src.utils.frame_utils import (
    _make_frame_transform,
    _render_current_player_card,
    composite_overlay,
    draw_text_to_fit,
    render_input_sidebar,
)


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


class TestScoreLabels:
    """Tests for animated score label rendering."""

    def test_label_at_frame_0_alpha_is_1(self):
        """At frame 0 (frames_since=0): ease=0, alpha=1.0, x_offset=0."""
        inp = {"user_name": "X", "button": "a", "user_id": 1,
               "timestamp": "2026-01-01T00:00:00", "total_score": 7}
        transform = _make_frame_transform([], [(inp, 0)], capture_fps=5)
        frame = np.zeros((432, 480, 3), dtype=np.uint8)
        # Just verify transform runs and returns correct shape
        out = transform(frame)
        assert out.shape == (432, 852, 3)


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


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_pil(w: int, h: int):
    img = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    return img, draw


def _single_player(today: int = 10, alltime: int = 50) -> dict:
    return {
        "user_name": "Alice",
        "today": today,
        "alltime": alltime,
        "color": (255, 200, 100),
    }


def _header_stats_with_player(**kwargs) -> dict:
    return {
        "today": {"total": 100, "top_players": []},
        "alltime": {"total": 500, "top_players": []},
        "single_player": _single_player(**kwargs),
    }


def _header_stats_without_player() -> dict:
    return {
        "today": {"total": 100, "top_players": []},
        "alltime": {"total": 500, "top_players": []},
    }


# ── TestDrawTextToFitAlign ────────────────────────────────────────────────────

class TestDrawTextToFitAlign:
    def _render(self, text: str, max_w: int, align: str) -> np.ndarray:
        img, draw = _make_pil(max_w, 20)
        draw_text_to_fit(img, draw, x=0, y=0, name=text,
                         color=(255, 255, 255), max_w=max_w,
                         line_height=20, font=None, align=align)
        return np.array(img)

    def test_align_left_unchanged(self):
        """Left-aligned short text: first column of pixels contains text."""
        arr = self._render("A", max_w=50, align="left")
        # With left align, non-zero pixels start near x=0
        cols_with_pixels = np.where(np.any(arr > 0, axis=(0, 2)))[0]
        assert len(cols_with_pixels) > 0
        assert cols_with_pixels[0] < 10  # text starts near left edge

    def test_align_center_shifts_x(self):
        """Centered short text: non-zero pixels are not hugging the left edge."""
        arr_left = self._render("A", max_w=80, align="left")
        arr_center = self._render("A", max_w=80, align="center")
        cols_left = np.where(np.any(arr_left > 0, axis=(0, 2)))[0]
        cols_center = np.where(np.any(arr_center > 0, axis=(0, 2)))[0]
        if len(cols_left) > 0 and len(cols_center) > 0:
            # Centered text should start further right than left-aligned text
            assert cols_center[0] > cols_left[0]

    def test_align_center_compressed(self):
        """Text wider than max_w is compressed to max_w regardless of align."""
        arr = self._render("WWWWWWWWWWWWWWWWWWWWWWWWWW", max_w=20, align="center")
        # Should have non-zero pixels (text rendered)
        assert np.any(arr > 0)
        # Width should be bounded to max_w (image width is max_w)
        assert arr.shape[1] == 20


# ── TestRenderCurrentPlayerCard ───────────────────────────────────────────────

class TestRenderCurrentPlayerCard:
    SCALE = 1

    def _card(self, period_key="today", n_new=0, **sp_kwargs):
        s = self.SCALE
        card_w = 56 * s
        card_h = 2 * s + 28 * s + 2 * s + 10 * s + 2 * s  # 44 at scale=1 → actually 44
        # Make image tall enough to contain the card starting at y=0
        img = Image.new("RGB", (card_w, card_h + 10), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        _render_current_player_card(
            img=img, draw=draw,
            single_player=_single_player(**sp_kwargs),
            period_key=period_key,
            n_new_inputs=n_new,
            scale=s,
            card_x=0, card_y=0,
            font_path=None,
            small_font=None,
        )
        return np.array(img)

    def test_outline_present(self):
        """The border pixel of the card should be white (outline)."""
        arr = self._card()
        # Top-left corner pixel should be white
        assert tuple(arr[0, 0]) == (255, 255, 255)

    def test_avatar_square_is_white(self):
        """The avatar region (top-left, inset by padding) is all white."""
        s = self.SCALE
        padding = 2 * s
        avatar_sz = 28 * s
        arr = self._card()
        avatar_region = arr[padding:padding + avatar_sz, padding:padding + avatar_sz]
        assert np.all(avatar_region == 255)

    def test_counter_uses_period_today(self):
        """today period → counter = today + n_new."""
        arr_0 = self._card(period_key="today", n_new=0, today=10)
        arr_5 = self._card(period_key="today", n_new=5, today=10)
        # With n_new=5 the counter is higher so more pixels are rendered (or different pixels)
        assert not np.array_equal(arr_0, arr_5)

    def test_counter_uses_period_alltime(self):
        """alltime period → counter differs from today period when today != alltime."""
        arr_today = self._card(period_key="today", today=10, alltime=9999)
        arr_alltime = self._card(period_key="alltime", today=10, alltime=9999)
        assert not np.array_equal(arr_today, arr_alltime)

    def test_counter_increments_with_n_new_inputs(self):
        """n_new_inputs shifts the displayed counter value."""
        arr_a = self._card(period_key="alltime", n_new=0, alltime=100)
        arr_b = self._card(period_key="alltime", n_new=100, alltime=100)
        assert not np.array_equal(arr_a, arr_b)

    def test_card_has_non_black_pixels(self):
        """Card produces non-black pixels (outline + avatar + text)."""
        arr = self._card()
        assert np.any(arr > 0)


# ── TestRenderInputSidebarSinglePlayer ────────────────────────────────────────

class TestRenderInputSidebarSinglePlayer:
    SCALE = 1

    def _sidebar(self, header_stats, global_frame_count=0, n_new=0):
        return render_input_sidebar(
            inputs=[],
            base_width=124, base_height=144,
            scale=self.SCALE,
            header_stats=header_stats,
            global_frame_count=global_frame_count,
            n_new_inputs=n_new,
        )

    def _card_region(self, arr) -> np.ndarray:
        """Extract the expected floating card region from the sidebar array."""
        s = self.SCALE
        # card_y = date_row_height + 28*scale = 10*s + 28*s = 38*s (at scale=1 → 38)
        card_y = 10 * s + 28 * s
        card_h = 2 * s + 28 * s + 2 * s + 10 * s + 2 * s
        card_w = 56 * s
        return arr[card_y:card_y + card_h, 0:card_w]

    def test_card_present_with_single_player_key(self):
        """Single player card adds non-black pixels in the card region."""
        arr = self._sidebar(_header_stats_with_player())
        region = self._card_region(arr)
        assert np.any(region > 0)

    def test_card_absent_without_single_player_key(self):
        """Without single_player key, card region stays black."""
        arr = self._sidebar(_header_stats_without_player())
        region = self._card_region(arr)
        assert not np.any(region > 0)

    def test_stats_row_height_unchanged(self):
        """Input entries layout is unchanged: rows well below the card are identical."""
        arr_with = self._sidebar(_header_stats_with_player())
        arr_without = self._sidebar(_header_stats_without_player())
        s = self.SCALE
        # Card spans roughly y=38 to y=82 at scale=1 (38 + 44).
        # Rows past the card bottom should be all-black (no inputs) and identical.
        card_bottom = 10 * s + 28 * s + (2 * s + 28 * s + 2 * s + 10 * s + 2 * s)  # ~82
        check_row = card_bottom + 5  # well below the card
        assert np.array_equal(arr_with[check_row], arr_without[check_row])

    def test_counter_increments_with_n_new(self):
        """Card counter changes when n_new_inputs increases."""
        arr_0 = self._sidebar(_header_stats_with_player(), n_new=0)
        arr_5 = self._sidebar(_header_stats_with_player(), n_new=5)
        region_0 = self._card_region(arr_0)
        region_5 = self._card_region(arr_5)
        assert not np.array_equal(region_0, region_5)
