"""Integration tests for timelapse system end-to-end (DB-driven)."""

import pytest
import asyncio
import numpy as np
from io import BytesIO
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from PIL import Image

from src.tasks.timelapse_encoder import TimelapseEncodingQueue, TimelapseEncoder
from src.db.manager import DatabaseManager
from src.models.game_state import TimelapseJobRow

import os
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")


@pytest.fixture
def db_manager(tmp_path):
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    return manager


def _write_npy_frames(folder: Path, frame_count: int = 10):
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(frame_count):
        arr = np.full((144, 160, 3), (i * 8) % 256, dtype=np.uint8)
        np.save(str(folder / f"frame_{i:06d}.npy"), arr)
    return folder


def _make_job(tmp_path, chat_id="123", frame_count=10, timestamp="2026-02-21T10:30:00") -> TimelapseJobRow:
    folder = tmp_path / "frames" / chat_id / f"20260221_{chat_id}"
    _write_npy_frames(folder, frame_count)
    ctx = {
        "frame_count": frame_count,
        "frame_skip": 1,
        "capture_fps": 15,
        "timelapse_fps": 10,
        "pre_existing_inputs": [],
        "new_inputs_with_offsets": [],
        "reactions": [],
        "user_colors": {},
    }
    return TimelapseJobRow(
        id=1,
        chat_id=chat_id,
        folder_path=str(folder),
        timestamp=timestamp,
        fps=10,
        compositing_context=ctx,
        frame_count=frame_count,
        status="pending",
        created_at=timestamp,
        updated_at=timestamp,
    )


class TestTimelapseIntegration:
    """Integration tests for the complete timelapse workflow."""

    @pytest.mark.asyncio
    async def test_encoder_creates_video_file(self, db_manager, tmp_path):
        """TimelapseEncoder._do_encode_and_append creates a video file."""
        job = _make_job(tmp_path)
        encoder = TimelapseEncoder(db_manager)

        async def fake_streaming(frames_iter, transform_fn, path, fps, **kwargs):
            list(frames_iter)
            Path(path).write_bytes(b"fake video data" * 100)

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_file_size_threshold = 10 * 1024 * 1024
            with patch("src.tasks.timelapse_encoder.save_frames_as_mp4_streaming", side_effect=fake_streaming):
                with patch("fcntl.flock"):
                    await encoder._do_encode_and_append(job)

        video_path = tmp_path / "recaps" / "123" / "recap_20260221.mp4"
        assert video_path.exists()

    @pytest.mark.asyncio
    async def test_database_metadata_updated_after_encode(self, db_manager, tmp_path):
        """After encoding, recap_files DB record is created."""
        job = _make_job(tmp_path)
        encoder = TimelapseEncoder(db_manager)

        async def fake_streaming(frames_iter, transform_fn, path, fps, **kwargs):
            list(frames_iter)
            Path(path).write_bytes(b"fake video data" * 100)

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_file_size_threshold = 10 * 1024 * 1024
            with patch("src.tasks.timelapse_encoder.save_frames_as_mp4_streaming", side_effect=fake_streaming):
                with patch("fcntl.flock"):
                    await encoder._do_encode_and_append(job)

        record = await db_manager.get_recap_file(123, "20260221")
        assert record is not None
        assert record.file_size_bytes > 0

    @pytest.mark.asyncio
    async def test_database_metadata_accumulates(self, db_manager, tmp_path):
        """Recap metadata accumulates across multiple upserts."""
        chat_id = 123
        date = "20260221"

        await db_manager.upsert_recap_metadata(chat_id, date, 10, 1.0, 5000)
        record = await db_manager.get_recap_file(chat_id, date)
        assert record.frame_count == 10
        assert record.duration_sec == 1.0
        assert record.file_size_bytes == 5000

        await db_manager.upsert_recap_metadata(chat_id, date, 15, 1.5, 7500)
        record = await db_manager.get_recap_file(chat_id, date)
        assert record.frame_count == 25  # accumulated
        assert record.duration_sec == 2.5  # accumulated
        assert record.file_size_bytes == 7500

    @pytest.mark.asyncio
    async def test_file_id_caching_workflow(self, db_manager, tmp_path):
        """file_id is stored and cleared on re-encode."""
        chat_id = 123
        date = "20260221"

        await db_manager.upsert_recap_metadata(chat_id, date, 100, 10.0, 50000)
        record = await db_manager.get_recap_file(chat_id, date)
        assert record.file_id is None

        await db_manager.update_recap_file_id(chat_id, date, 1, False, "tg_file_abc")
        record = await db_manager.get_recap_file(chat_id, date)
        assert record.file_id == "tg_file_abc"

        await db_manager.upsert_recap_metadata(chat_id, date, 50, 5.0, 25000)
        record = await db_manager.get_recap_file(chat_id, date)
        assert record.file_id is None  # invalidated by new encode
        assert record.frame_count == 150  # metadata accumulated

    @pytest.mark.asyncio
    async def test_encode_with_frame_skip(self, db_manager, tmp_path):
        """frame_skip=2 causes only every other frame to be loaded."""
        folder = tmp_path / "frames" / "123" / "20260221_skip"
        folder.mkdir(parents=True, exist_ok=True)
        frame_count = 8
        for i in range(frame_count):
            arr = np.full((144, 160, 3), i * 20, dtype=np.uint8)
            np.save(str(folder / f"frame_{i:06d}.npy"), arr)

        ctx = {
            "frame_count": frame_count,
            "frame_skip": 2,
            "capture_fps": 15,
            "timelapse_fps": 10,
            "pre_existing_inputs": [],
            "new_inputs_with_offsets": [],
            "reactions": [],
            "user_colors": {},
        }
        job = TimelapseJobRow(
            id=2, chat_id="123", folder_path=str(folder),
            timestamp="2026-02-21T10:30:00", fps=10,
            compositing_context=ctx, frame_count=frame_count,
            status="pending", created_at="2026-02-21T10:30:00",
            updated_at="2026-02-21T10:30:00",
        )
        encoder = TimelapseEncoder(db_manager)
        consumed = []

        async def fake_streaming(frames_iter, transform_fn, path, fps, **kwargs):
            consumed.extend(list(frames_iter))
            Path(path).write_bytes(b"fake video" * 10)

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_file_size_threshold = 10 * 1024 * 1024
            with patch("src.tasks.timelapse_encoder.save_frames_as_mp4_streaming", side_effect=fake_streaming):
                with patch("fcntl.flock"):
                    await encoder._do_encode_and_append(job)

        assert len(consumed) == 4  # 8 frames / skip 2 = 4

    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises(self, db_manager, tmp_path):
        """_encode_with_retry raises after all retries exhausted."""
        job = _make_job(tmp_path)
        encoder = TimelapseEncoder(db_manager)

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.timelapse_backoff_delays = [0, 0]
            with patch.object(encoder, "_do_encode_and_append", new_callable=AsyncMock,
                               side_effect=RuntimeError("FFmpeg died")):
                with pytest.raises(RuntimeError, match="FFmpeg died"):
                    await encoder._encode_with_retry(job)

    @pytest.mark.asyncio
    async def test_worker_processes_and_cleans_up(self, db_manager, tmp_path):
        """_run_worker processes a job and removes the frame folder."""
        job = _make_job(tmp_path)
        folder = Path(job.folder_path)
        assert folder.exists()

        queue = TimelapseEncodingQueue(db_manager)
        calls = [0]

        def fetch_next(chat_id):
            if calls[0] == 0:
                calls[0] += 1
                return job
            return None

        with patch("src.utils.state_manager.state_manager") as mock_sm:
            mock_sm.fetch_next_pending_job.side_effect = fetch_next
            mock_sm.update_job_status = Mock()
            with patch.object(queue.encoder, "_encode_with_retry", new_callable=AsyncMock):
                with patch("src.utils.priority_gate.wait_while_busy", new_callable=AsyncMock):
                    with patch("shutil.rmtree") as mock_rm:
                        await queue._run_worker("123")

        mock_rm.assert_called_once_with(folder)

    @pytest.mark.asyncio
    async def test_split_logic_renames_large_file(self, db_manager, tmp_path):
        """_check_and_split_if_needed renames oversized file and calls DB split."""
        encoder = TimelapseEncoder(db_manager)
        video_path = tmp_path / "recap_20260221.mp4"
        video_path.write_bytes(b"x" * 200)

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.recap_part_file_size_threshold = 100
            with patch.object(encoder.db_manager, "split_recap_part", new_callable=AsyncMock) as mock_split:
                with patch("src.tasks.timelapse_encoder.asyncio.create_task"):
                    await encoder._check_and_split_if_needed(123, "20260221", video_path, False, 1)

        assert (tmp_path / "recap_20260221_part1.mp4").exists()
        assert not video_path.exists()
        mock_split.assert_called_once_with(123, "20260221", 1, False)

    @pytest.mark.asyncio
    async def test_split_logic_fires_auto_send_task(self, db_manager, tmp_path):
        """_check_and_split_if_needed creates an asyncio task for auto_send_split_recap_part on split."""
        encoder = TimelapseEncoder(db_manager)
        await db_manager.upsert_recap_metadata(123, "20260221", 100, 10.0, 50000)
        video_path = tmp_path / "recap_20260221.mp4"
        video_path.write_bytes(b"x" * 200)

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.recap_part_file_size_threshold = 100
            with patch.object(encoder.db_manager, "split_recap_part", new_callable=AsyncMock):
                with patch("src.tasks.timelapse_encoder.asyncio.create_task") as mock_create_task:
                    mock_create_task.return_value = MagicMock()
                    # Mock the function as an AsyncMock with return_value to avoid coroutine creation
                    with patch("src.tasks.timelapse_encoder.auto_send_split_recap_part", new_callable=AsyncMock) as mock_fn:
                        mock_fn.return_value = None
                        await encoder._check_and_split_if_needed(123, "20260221", video_path, False, 1)

        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_split_logic_no_task_when_below_threshold(self, db_manager, tmp_path):
        """No asyncio task created when file is below threshold (no split)."""
        encoder = TimelapseEncoder(db_manager)
        video_path = tmp_path / "recap_20260221.mp4"
        video_path.write_bytes(b"x" * 50)

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.recap_part_file_size_threshold = 10 * 1024 * 1024
            with patch("src.tasks.timelapse_encoder.asyncio.create_task") as mock_create_task:
                with patch("src.tasks.timelapse_encoder.auto_send_split_recap_part", new_callable=AsyncMock) as mock_fn:
                    mock_fn.return_value = None
                    await encoder._check_and_split_if_needed(123, "20260221", video_path, False, 1)

        mock_create_task.assert_not_called()
