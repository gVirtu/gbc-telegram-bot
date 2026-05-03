"""Tests for timelapse encoder after overlay refactor.

The encoder no longer owns overlay logic. Frames arrive pre-composited.
"""

import os

os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

from src.tasks.timelapse_encoder import TimelapseEncoder


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
