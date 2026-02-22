"""Tests for timelapse encoding queue."""

import pytest
import asyncio
import numpy as np
from unittest.mock import Mock, patch, AsyncMock

from src.tasks.timelapse_encoder import TimelapseEncodingQueue, TimelapseEncoder
from src.db.manager import DatabaseManager


@pytest.fixture
def db_manager(tmp_path):
    """Create a test database manager."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    return manager


@pytest.fixture
def queue(db_manager):
    """Create a timelapse encoding queue."""
    return TimelapseEncodingQueue(db_manager)


@pytest.fixture
def test_frames():
    """Create test frames."""
    frames = []
    for i in range(5):
        frame = np.full((144, 160, 3), i * 50, dtype=np.uint8)
        frames.append(frame)
    return frames


class TestTimelapseEncodingQueue:
    """Tests for TimelapseEncodingQueue."""

    @pytest.mark.asyncio
    async def test_enqueue_creates_queue_and_worker(self, queue, test_frames):
        """Test that enqueuing creates queue and worker for new chat."""
        chat_id = 123

        with patch.object(queue.encoder, 'encode_job', new_callable=AsyncMock) as mock_encode:
            # Enqueue a job
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:30:00")

            # Verify queue and worker were created
            assert chat_id in queue._queues
            assert chat_id in queue._workers

            # Wait a bit for worker to process
            await queue._queues[chat_id].join()

            # Verify job was processed
            mock_encode.assert_called_once()

            # Cleanup
            await queue.shutdown()

    @pytest.mark.asyncio
    async def test_sequential_processing_fifo(self, queue, test_frames):
        """Test that jobs are processed sequentially in FIFO order."""
        chat_id = 123
        processed_order = []

        async def track_processing(job):
            processed_order.append(job.timestamp)
            await asyncio.sleep(0.05)  # Simulate processing time

        with patch.object(queue.encoder, 'encode_job', side_effect=track_processing):
            # Enqueue multiple jobs
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:00:00")
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:01:00")
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:02:00")

            # Wait for processing
            await queue._queues[chat_id].join()

            # Verify FIFO order
            assert processed_order == [
                "2026-02-21T10:00:00",
                "2026-02-21T10:01:00",
                "2026-02-21T10:02:00",
            ]

            # Cleanup
            await queue.shutdown()

    @pytest.mark.asyncio
    async def test_parallel_processing_different_chats(self, queue, test_frames):
        """Test that different chats are processed in parallel."""
        chat_123_processed = []
        chat_456_processed = []

        async def track_processing(job):
            if job.chat_id == 123:
                chat_123_processed.append(job.timestamp)
            else:
                chat_456_processed.append(job.timestamp)
            await asyncio.sleep(0.05)

        with patch.object(queue.encoder, 'encode_job', side_effect=track_processing):
            # Enqueue jobs for different chats
            await queue.enqueue(123, test_frames, "2026-02-21T10:00:00")
            await queue.enqueue(456, test_frames, "2026-02-21T10:00:00")

            # Wait for processing
            await queue._queues[123].join()
            await queue._queues[456].join()

            # Verify both were processed (parallel execution)
            assert len(chat_123_processed) == 1
            assert len(chat_456_processed) == 1

            # Cleanup
            await queue.shutdown()

    @pytest.mark.asyncio
    async def test_error_handling_continues_processing(self, queue, test_frames):
        """Test that errors don't stop queue processing."""
        chat_id = 123
        call_count = [0]

        async def failing_then_succeeding(job):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("First job failed")
            # Second job succeeds
            return

        with patch.object(queue.encoder, 'encode_job', side_effect=failing_then_succeeding):
            # Enqueue two jobs
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:00:00")
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:01:00")

            # Wait for processing
            await queue._queues[chat_id].join()

            # Verify both jobs were attempted (even though first failed)
            assert call_count[0] == 2

            # Cleanup
            await queue.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_in_flight_jobs(self, queue, test_frames):
        """Test that shutdown waits for in-flight jobs to complete."""
        chat_id = 123
        completed = [False]

        async def long_running_job(job):
            await asyncio.sleep(0.1)
            completed[0] = True

        with patch.object(queue.encoder, 'encode_job', side_effect=long_running_job):
            # Enqueue a job
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:00:00")

            # Give worker time to start
            await asyncio.sleep(0.05)

            # Shutdown should wait for completion (with reasonable timeout)
            await asyncio.wait_for(queue.shutdown(), timeout=5.0)

            # Job should have completed
            assert completed[0] is True

    @pytest.mark.asyncio
    async def test_queue_size_tracking(self, queue, test_frames):
        """Test that queue size is tracked correctly."""
        chat_id = 123
        processing_count = [0]

        # Block first job, let others pass
        first_job_started = asyncio.Event()
        allow_first_job = asyncio.Event()

        async def controlled_job(job):
            processing_count[0] += 1
            if processing_count[0] == 1:
                # First job blocks
                first_job_started.set()
                await allow_first_job.wait()
            # Other jobs complete immediately

        with patch.object(queue.encoder, 'encode_job', side_effect=controlled_job):
            # Enqueue multiple jobs
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:00:00")
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:01:00")
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:02:00")

            # Wait for first job to start processing
            await first_job_started.wait()

            # Queue should have 2 items remaining (first one is being processed)
            assert queue._queues[chat_id].qsize() == 2

            # Allow first job to complete
            allow_first_job.set()

            # Wait a bit for all jobs to complete
            await queue._queues[chat_id].join()

            # Now queue should be empty
            assert queue._queues[chat_id].qsize() == 0

            # Cleanup
            await queue.shutdown()

    @pytest.mark.asyncio
    async def test_worker_cleanup_on_cancellation(self, queue, test_frames):
        """Test that workers are properly cleaned up on cancellation."""
        chat_id = 123

        with patch.object(queue.encoder, 'encode_job', new_callable=AsyncMock):
            # Enqueue a job to create worker
            await queue.enqueue(chat_id, test_frames, "2026-02-21T10:00:00")

            # Wait for worker to be created
            await asyncio.sleep(0.05)

            # Verify worker exists
            assert chat_id in queue._workers

            # Shutdown cancels workers
            await queue.shutdown()

            # Worker should be cancelled
            assert queue._workers[chat_id].cancelled() or queue._workers[chat_id].done()
