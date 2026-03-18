"""Tests for recap overlay integration in timelapse encoder."""

import asyncio
import os
import pytest
import numpy as np

os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

from src.tasks.timelapse_encoder import TimelapseJob, TimelapseEncodingQueue, TimelapseEncoder
from dataclasses import field


# ---------------------------------------------------------------------------
# 1. TimelapseJob has new fields
# ---------------------------------------------------------------------------

def test_timelapse_job_has_new_fields():
    """TimelapseJob can be created with pre_existing_inputs and new_inputs_with_offsets."""
    frames = [np.zeros((144, 160, 3), dtype=np.uint8)]
    job = TimelapseJob(
        chat_id=1,
        frames=frames,
        timestamp="2026-03-14T12:00:00",
    )
    # Defaults are empty lists
    assert job.pre_existing_inputs == []
    assert job.new_inputs_with_offsets == []

    # Can be set explicitly
    pre = [{"user_name": "Alice", "button": "a", "user_id": 1, "timestamp": "2026-03-14T12:00:00"}]
    new = [({"user_name": "Bob", "button": "b", "user_id": 2, "timestamp": "2026-03-14T12:00:01"}, 3)]
    job2 = TimelapseJob(
        chat_id=1,
        frames=frames,
        timestamp="2026-03-14T12:00:00",
        pre_existing_inputs=pre,
        new_inputs_with_offsets=new,
    )
    assert job2.pre_existing_inputs == pre
    assert job2.new_inputs_with_offsets == new


# ---------------------------------------------------------------------------
# 2. enqueue() passes new fields to the job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_passes_new_fields(tmp_path, monkeypatch):
    """enqueue() with pre_existing_inputs and new_inputs_with_offsets sets them on the job."""
    from unittest.mock import MagicMock, AsyncMock
    from src.tasks.timelapse_encoder import TimelapseEncodingQueue

    db_manager = MagicMock()
    queue = TimelapseEncodingQueue(db_manager)

    frames = [np.zeros((144, 160, 3), dtype=np.uint8)]
    pre = [{"user_name": "Alice", "button": "a", "user_id": 1, "timestamp": "2026-03-14T12:00:00"}]
    new_inputs = [({"user_name": "Bob", "button": "b", "user_id": 2, "timestamp": "2026-03-14T12:00:01"}, 5)]

    await queue.enqueue(
        chat_id=42,
        frames=frames,
        timestamp="2026-03-14T12:00:00",
        pre_existing_inputs=pre,
        new_inputs_with_offsets=new_inputs,
    )

    # Cancel the worker so the test can complete
    if 42 in queue._workers:
        queue._workers[42].cancel()
        try:
            await queue._workers[42]
        except (asyncio.CancelledError, Exception):
            pass

    # Inspect the job that was enqueued
    job = queue._queues[42].get_nowait()
    assert job.pre_existing_inputs == pre
    assert job.new_inputs_with_offsets == new_inputs


# ---------------------------------------------------------------------------
# 3. _get_video_path uses recap_ prefix
# ---------------------------------------------------------------------------

def test_video_path_uses_recap_prefix(tmp_path, monkeypatch):
    """_get_video_path returns path ending with recap_<date>.mp4."""
    from unittest.mock import MagicMock
    from src.config import settings as _settings

    monkeypatch.setattr(_settings, "data_dir", tmp_path)

    db_manager = MagicMock()
    encoder = TimelapseEncoder(db_manager)
    path = encoder._get_video_path(123, "20260313")
    assert path.name == "recap_20260313.mp4"


# ---------------------------------------------------------------------------
# 4. _get_rt_video_path uses recap_ prefix
# ---------------------------------------------------------------------------

def test_rt_video_path_uses_recap_prefix(tmp_path, monkeypatch):
    """_get_rt_video_path returns path ending with recap_<date>_rt.mp4."""
    from unittest.mock import MagicMock
    from src.config import settings as _settings

    monkeypatch.setattr(_settings, "data_dir", tmp_path)

    db_manager = MagicMock()
    encoder = TimelapseEncoder(db_manager)
    path = encoder._get_rt_video_path(123, "20260313")
    assert path.name == "recap_20260313_rt.mp4"


# ---------------------------------------------------------------------------
# 5. make_frame_transform applies sidebar (frame becomes wider)
# ---------------------------------------------------------------------------

def test_make_frame_transform_applies_sidebar():
    """Transform with one pre_existing input makes the output frame wider."""
    from src.tasks.timelapse_encoder import make_frame_transform

    pre = [{"user_name": "Alice", "button": "a", "user_id": 1, "timestamp": "2026-03-14T12:00:00"}]
    transform = make_frame_transform(pre, [])

    frame = np.zeros((144, 160, 3), dtype=np.uint8)
    result = transform(frame)

    # The sidebar is composited to the right, making result wider
    assert result.shape[1] > frame.shape[1]
    assert result.shape[0] >= frame.shape[0]


# ---------------------------------------------------------------------------
# 6. make_frame_transform adds inputs at the correct frame offset
# ---------------------------------------------------------------------------

def test_make_frame_transform_adds_inputs_at_offset():
    """Transform with new_input at offset=2: frames 0,1 have empty sidebar; frame 2 shows the input."""
    from src.tasks.timelapse_encoder import make_frame_transform

    new_input = {"user_name": "Bob", "button": "b", "user_id": 2, "timestamp": "2026-03-14T12:00:01"}
    transform = make_frame_transform([], [(new_input, 2)])

    frame = np.zeros((144, 160, 3), dtype=np.uint8)

    # All frames get the sidebar composited (just with different content)
    result0 = transform(frame.copy())
    result1 = transform(frame.copy())
    result2 = transform(frame.copy())

    # All results should be wider (sidebar is always rendered)
    assert result0.shape[1] > frame.shape[1]
    assert result1.shape[1] > frame.shape[1]
    assert result2.shape[1] > frame.shape[1]

    # Frame 2 should have content in the sidebar area (white text on black)
    # frames 0 and 1 have an all-black sidebar (no inputs yet)
    sidebar_row_start = 24
    sidebar_col_start = frame.shape[1]

    def sidebar_has_white(result):
        sidebar = result[sidebar_row_start:, sidebar_col_start:, :]
        return bool(np.any(sidebar > 10))

    assert not sidebar_has_white(result0), "Frame 0 sidebar should be empty (black)"
    assert not sidebar_has_white(result1), "Frame 1 sidebar should be empty (black)"
    assert sidebar_has_white(result2), "Frame 2 sidebar should have text (white pixels)"
