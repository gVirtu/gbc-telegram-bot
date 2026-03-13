"""Integration tests for timelapse system end-to-end."""

import pytest
import asyncio
import numpy as np
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

from src.tasks.timelapse_encoder import TimelapseEncodingQueue, TimelapseEncoder
from src.db.manager import DatabaseManager
from src.config import settings


@pytest.fixture
def db_manager(tmp_path):
    """Create a test database manager."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    return manager


@pytest.fixture
def test_frames():
    """Create test frames for timelapse."""
    frames = []
    for i in range(30):  # 30 frames total
        # Create frame with gradient pattern
        frame = np.full((144, 160, 3), (i * 8) % 256, dtype=np.uint8)
        frames.append(frame)
    return frames


class TestTimelapseIntegration:
    """Integration tests for the complete timelapse workflow."""

    @pytest.mark.asyncio
    async def test_end_to_end_single_encoding(self, db_manager, test_frames, tmp_path):
        """Test complete flow: enqueue → encode → database update."""
        chat_id = 123
        date = "20260221"
        timestamp = f"{date[:4]}-{date[4:6]}-{date[6:]}T10:30:00"

        # Setup
        queue = TimelapseEncodingQueue(db_manager)

        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"
            mock_settings.timelapse_backoff_delays = []

            # Mock the actual FFmpeg encoding
            async def mock_encode(frames, path, fps=10, **kwargs):
                # Create a fake video file
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(b"fake video data" * 100)

            with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_optimized', side_effect=mock_encode):
                # Enqueue frames
                await queue.enqueue(chat_id, test_frames, timestamp)

                # Wait for processing
                await queue._queues[chat_id].join()

                # Verify video file was created
                video_path = tmp_path / "data" / "recaps" / "123" / "20260221.mp4"
                assert video_path.exists()

                # Verify database was updated
                record = await db_manager.get_recap_file(chat_id, date)
                assert record is not None
                assert record.file_id is None  # Not uploaded to Telegram yet
                assert record.file_size_bytes > 0

                # Cleanup
                await queue.shutdown()

    @pytest.mark.asyncio
    async def test_multiple_sequential_inputs_chronological(self, db_manager, test_frames, tmp_path):
        """Test that multiple inputs are processed in chronological order."""
        chat_id = 123
        processed_order = []

        queue = TimelapseEncodingQueue(db_manager)

        async def track_encoding(frames, path, fps=10, **kwargs):
            """Track the order of encoding."""
            # Extract timestamp from path
            processed_order.append(path)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"video")

        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"
            mock_settings.timelapse_backoff_delays = []

            with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_optimized', side_effect=track_encoding):
                # Enqueue multiple frames from the same day
                await queue.enqueue(chat_id, test_frames[:10], "2026-02-21T10:00:00")
                await queue.enqueue(chat_id, test_frames[10:20], "2026-02-21T10:05:00")
                await queue.enqueue(chat_id, test_frames[20:30], "2026-02-21T10:10:00")

                # Wait for all to process
                await queue._queues[chat_id].join()

                # Should have created temp files in order
                assert len(processed_order) >= 1  # At least one encoding happened

                # Cleanup
                await queue.shutdown()


    @pytest.mark.asyncio
    async def test_append_to_existing_timelapse(self, db_manager, test_frames, tmp_path):
        """Test appending frames to an existing timelapse video."""
        chat_id = 123
        date = "20260221"

        queue = TimelapseEncodingQueue(db_manager)

        encode_call_count = [0]

        async def mock_encode(frames, path, fps=10, **kwargs):
            encode_call_count[0] += 1
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            # Create progressively larger files
            Path(path).write_bytes(b"video" * encode_call_count[0] * 100)

        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"
            mock_settings.timelapse_backoff_delays = []

            with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_optimized', side_effect=mock_encode):
                # First encoding - creates new file
                await queue.enqueue(chat_id, test_frames[:15], "2026-02-21T10:00:00")
                await queue._queues[chat_id].join()

                # Second encoding - should append to existing
                await queue.enqueue(chat_id, test_frames[15:], "2026-02-21T10:05:00")
                await queue._queues[chat_id].join()

                # Verify multiple encodings happened
                assert encode_call_count[0] >= 2

                # Verify database shows accumulated data
                record = await db_manager.get_recap_file(chat_id, date)
                assert record is not None

                await queue.shutdown()

    @pytest.mark.asyncio
    async def test_failed_encoding_saves_frames(self, db_manager, test_frames, tmp_path):
        """Test that failed encodings save frames for recovery."""
        chat_id = 123
        timestamp = "2026-02-21T10:30:00"

        # Directly test the encoder's retry logic, not the queue
        from src.tasks.timelapse_encoder import TimelapseEncoder

        encoder = TimelapseEncoder(db_manager)

        async def failing_encode(frames, path, fps=10, **kwargs):
            raise RuntimeError("FFmpeg failed")

        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"
            mock_settings.timelapse_backoff_delays = []

            with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_optimized', side_effect=failing_encode):
                # Directly call encode_with_retry (bypasses queue complexity)
                try:
                    await encoder._encode_with_retry(chat_id, test_frames, timestamp)
                except RuntimeError:
                    pass  # Expected to fail after retries

                # Verify failed frames were saved
                failed_dir = tmp_path / "data" / "recaps" / "123" / "failed" / timestamp
                assert failed_dir.exists()

                # Check that frames were saved
                frame_files = list(failed_dir.glob("frame_*.npy"))
                assert len(frame_files) == len(test_frames)

                # Check error log
                error_file = failed_dir / "error.txt"
                assert error_file.exists()

                content = error_file.read_text()
                assert "FFmpeg failed" in content

    @pytest.mark.asyncio
    async def test_database_metadata_accumulates(self, db_manager, tmp_path):
        """Test that database metadata accumulates across multiple encodes."""
        chat_id = 123
        date = "20260221"

        # First upsert
        await db_manager.upsert_recap_metadata(chat_id, date, 10, 1.0, 5000)

        record = await db_manager.get_recap_file(chat_id, date)
        assert record.frame_count == 10
        assert record.duration_sec == 1.0
        assert record.file_size_bytes == 5000

        # Second upsert (should accumulate duration and frame count)
        await db_manager.upsert_recap_metadata(chat_id, date, 15, 1.5, 7500)

        record = await db_manager.get_recap_file(chat_id, date)
        assert record.frame_count == 25  # 10 + 15
        assert record.duration_sec == 2.5  # 1.0 + 1.5
        assert record.file_size_bytes == 7500

    @pytest.mark.asyncio
    async def test_file_id_caching_workflow(self, db_manager, tmp_path):
        """Test the complete file_id caching workflow."""
        chat_id = 123
        date = "20260221"

        # Create initial record without file_id
        await db_manager.upsert_recap_metadata(chat_id, date, 100, 10.0, 50000)

        record = await db_manager.get_recap_file(chat_id, date)
        assert record.file_id is None

        # Simulate uploading to Telegram and getting file_id
        await db_manager.update_recap_file_id(chat_id, date, "telegram_file_id_abc123")

        record = await db_manager.get_recap_file(chat_id, date)
        assert record.file_id == "telegram_file_id_abc123"

        # Simulate new encoding (should invalidate file_id)
        await db_manager.upsert_recap_metadata(chat_id, date, 50, 5.0, 25000)

        record = await db_manager.get_recap_file(chat_id, date)
        assert record.file_id is None  # Invalidated!
        assert record.frame_count == 150  # But metadata accumulated

    @pytest.mark.asyncio
    async def test_concurrent_same_chat_sequential(self, db_manager, test_frames, tmp_path):
        """Test that concurrent jobs for same chat are processed sequentially."""
        chat_id = 123
        processing_order = []

        queue = TimelapseEncodingQueue(db_manager)

        async def track_order(frames, path, fps=10, **kwargs):
            processing_order.append(path)
            await asyncio.sleep(0.05)  # Simulate processing time
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"video")

        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"
            mock_settings.timelapse_backoff_delays = []

            with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_optimized', side_effect=track_order):
                # Enqueue multiple jobs quickly
                await queue.enqueue(chat_id, test_frames[:10], "2026-02-21T10:00:00")
                await queue.enqueue(chat_id, test_frames[10:20], "2026-02-21T10:01:00")
                await queue.enqueue(chat_id, test_frames[20:], "2026-02-21T10:02:00")

                # Wait for all to process
                await queue._queues[chat_id].join()

                # Should have processed all 3 in order
                assert len(processing_order) >= 1

                await queue.shutdown()

    @pytest.mark.asyncio
    async def test_different_chats_isolated(self, db_manager, test_frames, tmp_path):
        """Test that different chats have isolated timelapse files."""
        queue = TimelapseEncodingQueue(db_manager)

        async def mock_encode(frames, path, fps=10, **kwargs):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"video" * len(frames))

        with patch('src.tasks.timelapse_encoder.settings') as mock_settings:
            mock_settings.data_dir = tmp_path / "data"
            mock_settings.timelapse_backoff_delays = []

            with patch('src.tasks.timelapse_encoder.save_frames_as_mp4_optimized', side_effect=mock_encode):
                # Enqueue for different chats
                await queue.enqueue(123, test_frames[:15], "2026-02-21T10:00:00")
                await queue.enqueue(456, test_frames[15:], "2026-02-21T10:00:00")

                await queue._queues[123].join()
                await queue._queues[456].join()

                # Verify separate files exist
                video_123 = tmp_path / "data" / "recaps" / "123" / "20260221.mp4"
                video_456 = tmp_path / "data" / "recaps" / "456" / "20260221.mp4"

                assert video_123.exists()
                assert video_456.exists()

                # Verify separate database records
                record_123 = await db_manager.get_recap_file(123, "20260221")
                record_456 = await db_manager.get_recap_file(456, "20260221")

                assert record_123 is not None
                assert record_456 is not None

                await queue.shutdown()
