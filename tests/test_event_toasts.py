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
        events = [{"event_type": "score", "awarded_score": 10, "frame_offset": 0}]
        result = render_event_toasts(img, events, 0)
        assert result.shape == img.shape
        assert not np.array_equal(result, img)

    def test_toast_fades(self):
        img = np.zeros((144, 160, 3), dtype=np.uint8)
        events = [{"event_type": "score", "awarded_score": 10, "frame_offset": 0}]
        alpha1 = render_event_toasts(img, events, 0)
        alpha_half = render_event_toasts(img, events, 22)
        assert not np.array_equal(alpha1, alpha_half)

    def test_toast_expired(self):
        img = np.zeros((144, 160, 3), dtype=np.uint8)
        events = [{"event_type": "score", "awarded_score": 10, "frame_offset": 0}]
        result = render_event_toasts(img, events, 45)
        assert np.array_equal(result, img)

    def test_max_5_toasts(self):
        img = np.zeros((288, 320, 3), dtype=np.uint8)
        events = [
            {"event_type": "score", "awarded_score": i, "frame_offset": 0}
            for i in range(10)
        ]
        result = render_event_toasts(img, events, 0)
        assert result.shape == img.shape
