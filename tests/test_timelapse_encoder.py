"""Tests for timelapse encoder functionality."""

import pytest
import numpy as np
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

from src.tasks.timelapse_encoder import TimelapseEncoder, TimelapseJob
from src.db.manager import DatabaseManager


@pytest.fixture
def db_manager(tmp_path):
    """Create a test database manager."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    return manager


@pytest.fixture
def encoder(db_manager):
    """Create a timelapse encoder."""
    return TimelapseEncoder(db_manager)


@pytest.fixture
def test_frames():
    """Create test frames (10 frames, 144x160x3)."""
    frames = []
    for i in range(10):
        # Create frame with different color for each frame
        frame = np.full((144, 160, 3), i * 25, dtype=np.uint8)
        frames.append(frame)
    return frames


class TestTimelapseEncoder:
    """Tests for TimelapseEncoder."""

    def test_get_video_path(self, encoder, tmp_path):
        """Test video path generation."""
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"

            path = encoder._get_video_path(123, "20260221")

            assert path == tmp_path / "data" / "recaps" / "123" / "20260221.mp4"
            assert path.parent.exists()

    def test_get_failed_frames_path(self, encoder, tmp_path):
        """Test failed frames path generation."""
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"

            timestamp = "2026-02-21T10:30:00"
            path = encoder._get_failed_frames_path(123, timestamp)

            assert path == tmp_path / "data" / "recaps" / "123" / "failed" / timestamp
            assert path.exists()

    @pytest.mark.asyncio
    async def test_save_failed_frames(self, encoder, test_frames, tmp_path):
        """Test saving failed frames for recovery."""
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"

            timestamp = "2026-02-21T10:30:00"
            error = RuntimeError("Test error")

            await encoder._save_failed_frames(123, timestamp, test_frames, error)

            failed_dir = tmp_path / "data" / "recaps" / "123" / "failed" / timestamp
            assert failed_dir.exists()

            # Check frames were saved
            for i in range(len(test_frames)):
                frame_path = failed_dir / f"frame_{i:05d}.npy"
                assert frame_path.exists()
                loaded = np.load(frame_path)
                assert np.array_equal(loaded, test_frames[i])

            # Check error file
            error_path = failed_dir / "error.txt"
            assert error_path.exists()
            with open(error_path) as f:
                content = f.read()
                assert timestamp in content
                assert "Test error" in content

    @pytest.mark.asyncio
    async def test_create_new_timelapse(self, encoder, test_frames, tmp_path):
        """Test creating a new timelapse video."""
        video_path = tmp_path / "test.mp4"

        async def mock_save_func(frames, path, fps=10):
            # Create the actual file that the code expects
            Path(path).write_bytes(b"fake video data")

        with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_optimized', side_effect=mock_save_func) as mock_save:
            await encoder._create_new_timelapse(video_path, test_frames)

            # Verify save was called
            mock_save.assert_called_once()
            args = mock_save.call_args[0]
            assert len(args[0]) == len(test_frames)

            # Verify final file exists
            assert video_path.exists()

    @pytest.mark.asyncio
    async def test_encode_job_success(self, encoder, test_frames, tmp_path):
        """Test encoding a job successfully."""
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"

            with patch.object(encoder, '_encode_with_retry') as mock_encode:
                mock_encode.return_value = None

                job = TimelapseJob(
                    chat_id=123,
                    frames=test_frames,
                    timestamp="2026-02-21T10:30:00"
                )

                await encoder.encode_job(job)

                mock_encode.assert_called_once_with(123, test_frames, "2026-02-21T10:30:00", audio_chunks=None, fps=10)

    @pytest.mark.asyncio
    async def test_encode_with_retry_success_first_attempt(self, encoder, test_frames, tmp_path):
        """Test retry logic succeeds on first attempt."""
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"
            mock_settings.timelapse_backoff_delays = []

            with patch.object(encoder, '_do_encode_and_append') as mock_encode:
                mock_encode.return_value = None

                await encoder._encode_with_retry(123, test_frames, "2026-02-21T10:30:00")

                # Should only call once (success on first attempt)
                assert mock_encode.call_count == 1

    @pytest.mark.asyncio
    async def test_encode_with_retry_failure_all_attempts(self, encoder, test_frames, tmp_path):
        """Test retry logic fails after all attempts."""
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"
            mock_settings.timelapse_backoff_delays = [0, 0, 0]

            with patch.object(encoder, '_do_encode_and_append') as mock_encode:
                mock_encode.side_effect = RuntimeError("Encoding failed")

                with patch.object(encoder, '_save_failed_frames') as mock_save_failed:
                    mock_save_failed.return_value = None

                    with pytest.raises(RuntimeError):
                        await encoder._encode_with_retry(123, test_frames, "2026-02-21T10:30:00")

                    # Should try 3 times
                    assert mock_encode.call_count == 3

                    # Should save failed frames
                    mock_save_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_recap_metadata(self, encoder, tmp_path):
        """Test updating recap metadata."""
        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"

            # Create a dummy video file
            video_path = tmp_path / "data" / "recaps" / "123" / "20260221.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"fake video data" * 1000)

            await encoder._update_recap_metadata(123, "20260221", video_path, 10)

            # Verify metadata was updated in database
            record = await encoder.db_manager.get_recap_file(123, "20260221")
            assert record is not None
            assert record.file_size_bytes > 0

    @pytest.mark.asyncio
    async def test_file_locking_prevents_concurrent_access(self, encoder, test_frames, tmp_path):
        """Test that file locking works (basic verification)."""
        # This is a simplified test - real file locking is OS-dependent
        # We mainly verify the code path executes without errors

        async def mock_save_func(frames, path, fps=10):
            # Create the actual file that the code expects
            Path(path).write_bytes(b"fake video data")

        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"

            with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_optimized', side_effect=mock_save_func):
                with patch('fcntl.flock') as mock_flock:
                    await encoder._do_encode_and_append(123, test_frames, "2026-02-21T10:30:00")

                    # Verify lock was acquired and released
                    assert mock_flock.call_count >= 2  # LOCK_EX and LOCK_UN
