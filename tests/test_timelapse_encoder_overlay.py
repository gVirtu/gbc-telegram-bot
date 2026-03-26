"""Tests for timelapse encoder after overlay refactor.

The encoder no longer owns overlay logic. Frames arrive pre-composited.
"""

import os
import pytest
import numpy as np

os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

from src.tasks.timelapse_encoder import TimelapseEncodingQueue, TimelapseEncoder


def test_video_path_uses_recap_prefix(tmp_path, monkeypatch):
    """_get_video_path returns path ending with recap_<date>.mp4."""
    from unittest.mock import MagicMock
    from src.config import settings as _settings

    monkeypatch.setattr(_settings, "data_dir", tmp_path)

    db_manager = MagicMock()
    encoder = TimelapseEncoder(db_manager)
    path = encoder._get_video_path(123, "20260313")
    assert path.name == "recap_20260313.mp4"


def test_rt_video_path_uses_recap_prefix(tmp_path, monkeypatch):
    """_get_rt_video_path returns path ending with recap_<date>_rt.mp4."""
    from unittest.mock import MagicMock
    from src.config import settings as _settings

    monkeypatch.setattr(_settings, "data_dir", tmp_path)

    db_manager = MagicMock()
    encoder = TimelapseEncoder(db_manager)
    path = encoder._get_rt_video_path(123, "20260313")
    assert path.name == "recap_20260313_rt.mp4"


def test_apply_overlay_composite_applies_sidebar():
    """apply_overlay_composite (now in frame_utils) makes frames wider."""
    from src.utils.frame_utils import apply_overlay_composite

    pre = [{"user_name": "Alice", "button": "a", "user_id": 1, "timestamp": "2026-03-21T12:00:00"}]
    frames = [np.zeros((288, 320, 3), dtype=np.uint8)]
    original_width = frames[0].shape[1]
    original_height = frames[0].shape[0]
    result = apply_overlay_composite(frames, pre, [])

    assert result[0].shape[1] > original_width
    assert result[0].shape[0] >= original_height


def test_apply_overlay_composite_adds_inputs_at_offset():
    """apply_overlay_composite: frames before offset have empty sidebar; at offset has text."""
    from src.utils.frame_utils import apply_overlay_composite

    new_input = {"user_name": "Bob", "button": "b", "user_id": 2, "timestamp": "2026-03-21T12:00:01"}
    frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(3)]
    result = apply_overlay_composite(frames, [], [(new_input, 2)])

    def sidebar_has_white(f):
        return bool(np.any(f[24:, 320:, :] > 10))

    assert not sidebar_has_white(result[0])
    assert not sidebar_has_white(result[1])
    assert sidebar_has_white(result[2])
