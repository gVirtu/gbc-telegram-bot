"""Tests for timelapse encoder functionality."""

import json
import os
import pytest
import numpy as np
from io import BytesIO
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock
from PIL import Image

from src.tasks.timelapse_encoder import TimelapseEncoder
from src.db.manager import DatabaseManager
from src.models.game_state import TimelapseJobRow

os.environ.setdefault("PYTEST_CURRENT_TEST", "1")


def _make_job_row(tmp_path, frame_count=5, frame_skip=1, fps=10) -> TimelapseJobRow:
    """Helper: write fake .npy frames to a temp folder and return a TimelapseJobRow."""
    folder = tmp_path / "frames" / "123" / "20260221_abcd1234"
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(frame_count):
        arr = np.full((144, 160, 3), i * 30, dtype=np.uint8)
        np.save(str(folder / f"frame_{i:06d}.npy"), arr)

    ctx = {
        "frame_count": frame_count,
        "frame_skip": frame_skip,
        "capture_fps": 15,
        "timelapse_fps": fps,
        "pre_existing_inputs": [],
        "new_inputs_with_offsets": [],
        "reactions": [],
        "user_colors": {},
    }
    return TimelapseJobRow(
        id=1,
        chat_id="123",
        folder_path=str(folder),
        timestamp="2026-02-21T10:30:00",
        fps=fps,
        compositing_context=ctx,
        frame_count=frame_count,
        status="processing",
        created_at="2026-02-21T10:30:00",
        updated_at="2026-02-21T10:30:00",
    )


@pytest.fixture
def db_manager(tmp_path):
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    return manager


@pytest.fixture
def encoder(db_manager):
    return TimelapseEncoder(db_manager)


class TestTimelapseEncoder:
    def test_get_video_path(self, encoder, tmp_path):
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"
            path = encoder._get_video_path(123, "20260221")
            assert path == tmp_path / "data" / "recaps" / "123" / "recap_20260221.mp4"
            assert path.parent.exists()

    def test_get_rt_video_path(self, encoder, tmp_path):
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"
            path = encoder._get_rt_video_path(123, "20260221")
            assert path == tmp_path / "data" / "recaps" / "123" / "recap_20260221_rt.mp4"

    @pytest.mark.asyncio
    async def test_update_recap_metadata(self, encoder, tmp_path):
        video_path = tmp_path / "data" / "recaps" / "123" / "20260221.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video data" * 1000)

        await encoder._update_recap_metadata(123, "20260221", video_path, 10)

        record = await encoder.db_manager.get_recap_file(123, "20260221")
        assert record is not None
        assert record.file_size_bytes > 0

    @pytest.mark.asyncio
    async def test_create_new_timelapse_streaming(self, encoder, tmp_path):
        """_create_new_timelapse_streaming should write a file via save_frames_as_mp4_streaming."""
        video_path = tmp_path / "test.mp4"
        frames = iter([np.zeros((144, 160, 3), dtype=np.uint8)] * 3)
        transform = lambda f, i: np.array(Image.fromarray(f).resize((480, 432), Image.Resampling.NEAREST))

        async def fake_streaming(frames_iter, transform_fn, path, fps, **kwargs):
            Path(path).write_bytes(b"fake timelapse")

        with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_streaming', side_effect=fake_streaming):
            await encoder._create_new_timelapse_streaming(video_path, frames, transform, fps=10)

        assert video_path.exists()

    @pytest.mark.asyncio
    async def test_create_new_timelapse_streaming_cleans_up_on_error(self, encoder, tmp_path):
        """On error, tmp file is removed and exception propagates."""
        video_path = tmp_path / "test.mp4"
        frames = iter([np.zeros((3, 3, 3), dtype=np.uint8)])
        transform = lambda f, i: f

        async def failing_encode(frames_iter, transform_fn, path, fps, **kwargs):
            Path(path).write_bytes(b"partial")
            raise RuntimeError("encode failed")

        with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_streaming', side_effect=failing_encode):
            with pytest.raises(RuntimeError):
                await encoder._create_new_timelapse_streaming(video_path, frames, transform, fps=10)

        assert not video_path.exists()

    @pytest.mark.asyncio
    async def test_do_encode_and_append_calls_streaming(self, encoder, tmp_path):
        """_do_encode_and_append loads frames from disk and calls streaming encoder."""
        job = _make_job_row(tmp_path, frame_count=5)

        async def fake_streaming(frames_iter, transform_fn, path, fps, **kwargs):
            # Consume the iterator to verify it yields frames
            frames_consumed = list(frames_iter)
            assert len(frames_consumed) == 5
            Path(path).write_bytes(b"fake video" * 100)

        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_file_size_threshold = 10 * 1024 * 1024
            with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_streaming', side_effect=fake_streaming):
                await encoder._do_encode_and_append(job)

    @pytest.mark.asyncio
    async def test_do_encode_and_append_with_frame_skip(self, encoder, tmp_path):
        """With frame_skip=2, only every other frame is loaded."""
        job = _make_job_row(tmp_path, frame_count=6, frame_skip=2)

        consumed_count = []

        async def fake_streaming(frames_iter, transform_fn, path, fps, **kwargs):
            consumed = list(frames_iter)
            consumed_count.append(len(consumed))
            Path(path).write_bytes(b"fake video" * 100)

        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_file_size_threshold = 10 * 1024 * 1024
            with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_streaming', side_effect=fake_streaming):
                await encoder._do_encode_and_append(job)

        assert consumed_count[0] == 3  # 6 frames / skip 2 = 3

    @pytest.mark.asyncio
    async def test_encode_with_retry_success_first_attempt(self, encoder, tmp_path):
        """Retry logic succeeds on first attempt."""
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.timelapse_backoff_delays = []
            with patch.object(encoder, '_do_encode_and_append', new_callable=AsyncMock) as mock_encode:
                job = _make_job_row(tmp_path)
                await encoder._encode_with_retry(job)
                assert mock_encode.call_count == 1

    @pytest.mark.asyncio
    async def test_encode_with_retry_failure_all_attempts(self, encoder, tmp_path):
        """Retry logic raises after all attempts exhausted."""
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.timelapse_backoff_delays = [0, 0, 0]
            with patch.object(encoder, '_do_encode_and_append', new_callable=AsyncMock) as mock_encode:
                mock_encode.side_effect = RuntimeError("Encoding failed")
                job = _make_job_row(tmp_path)
                with pytest.raises(RuntimeError):
                    await encoder._encode_with_retry(job)
                assert mock_encode.call_count == 3

    @pytest.mark.asyncio
    async def test_file_locking_prevents_concurrent_access(self, encoder, tmp_path):
        """File locking path executes without error."""

        async def fake_streaming(frames_iter, transform_fn, path, fps, **kwargs):
            list(frames_iter)
            Path(path).write_bytes(b"fake video")

        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_file_size_threshold = 10 * 1024 * 1024
            with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_streaming', side_effect=fake_streaming):
                with patch('fcntl.flock') as mock_flock:
                    job = _make_job_row(tmp_path)
                    await encoder._do_encode_and_append(job)
                    assert mock_flock.call_count >= 2  # LOCK_EX and LOCK_UN
