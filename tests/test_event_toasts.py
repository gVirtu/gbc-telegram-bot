"""Tests for render_event_toasts function."""

import numpy as np

from src.utils.frame_utils import render_event_toasts


class TestRenderEventToasts:
    def test_no_events_returns_unchanged(self):
        img = np.zeros((144, 160, 3), dtype=np.uint8)
        result = render_event_toasts(img, [], 0)
        assert np.array_equal(result, img)

    def test_single_toast_renders(self):
        img = np.zeros((144, 160, 3), dtype=np.uint8)
        events = [{"event_type": "score", "title": "Scored", "awarded_score": 10, "frame_offset": 0}]
        result = render_event_toasts(img, events, 0)
        assert result.shape == img.shape
        assert not np.array_equal(result, img)

    def test_toast_holds_full_opacity(self):
        img = np.zeros((144, 160, 3), dtype=np.uint8)
        events = [{"event_type": "score", "title": "Scored", "awarded_score": 10, "frame_offset": 0}]
        alpha0 = render_event_toasts(img, events, 0)
        alpha22 = render_event_toasts(img, events, 22)
        assert np.array_equal(alpha0, alpha22)

    def test_toast_fades(self):
        img = np.zeros((144, 160, 3), dtype=np.uint8)
        events = [{"event_type": "score", "title": "Scored", "awarded_score": 10, "frame_offset": 0}]
        alpha0 = render_event_toasts(img, events, 0)
        alpha_mid_fade = render_event_toasts(img, events, 45)
        assert not np.array_equal(alpha0, alpha_mid_fade)

    def test_toast_expired(self):
        img = np.zeros((144, 160, 3), dtype=np.uint8)
        events = [{"event_type": "score", "title": "Scored", "awarded_score": 10, "frame_offset": 0}]
        result = render_event_toasts(img, events, 60)
        assert np.array_equal(result, img)

    def test_title_fallback_to_event_type(self):
        img = np.zeros((144, 160, 3), dtype=np.uint8)
        events = [{"event_type": "score", "awarded_score": 10, "frame_offset": 0}]
        result = render_event_toasts(img, events, 0)
        assert not np.array_equal(result, img)

    def test_max_5_toasts(self):
        img = np.zeros((288, 320, 3), dtype=np.uint8)
        events = [
            {"event_type": "score", "title": f"Event {i}", "awarded_score": i, "frame_offset": 0}
            for i in range(10)
        ]
        result = render_event_toasts(img, events, 0)
        assert result.shape == img.shape
