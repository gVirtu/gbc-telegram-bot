"""Tests for timelapse encoding queue (DB-driven event model)."""

import pytest
import asyncio
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

from src.tasks.timelapse_encoder import TimelapseEncodingQueue
from src.db.manager import DatabaseManager
from src.models.game_state import TimelapseJobRow

import os
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")


def _make_job_row(tmp_path, chat_id="123", frame_count=3) -> TimelapseJobRow:
    folder = tmp_path / "frames" / chat_id / "20260221_abcd"
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(frame_count):
        arr = np.full((144, 160, 3), i * 50, dtype=np.uint8)
        np.save(str(folder / f"frame_{i:06d}.npy"), arr)
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
        timestamp="2026-02-21T10:30:00",
        fps=10,
        compositing_context=ctx,
        frame_count=frame_count,
        status="pending",
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
def queue(db_manager):
    return TimelapseEncodingQueue(db_manager)


class TestTimelapseEncodingQueue:
    """Tests for TimelapseEncodingQueue (DB-driven)."""

    def test_trigger_worker_creates_task(self, queue):
        """trigger_worker creates a task if chat_id not already active."""
        with patch('asyncio.create_task', side_effect=lambda coro: coro.close() or Mock()) as mock_create_task:
            queue.trigger_worker("123")
            mock_create_task.assert_called_once()

    def test_trigger_worker_noop_if_already_active(self, queue):
        """trigger_worker is a no-op if worker already running."""
        queue._active.add("123")
        with patch('asyncio.create_task', side_effect=lambda coro: coro.close() or Mock()) as mock_create_task:
            queue.trigger_worker("123")
            mock_create_task.assert_not_called()

    def test_trigger_worker_accepts_int_chat_id(self, queue):
        """trigger_worker converts int chat_id to str."""
        with patch('asyncio.create_task', side_effect=lambda coro: coro.close() or Mock()) as mock_create_task:
            queue.trigger_worker(456)
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_worker_processes_pending_jobs(self, queue, tmp_path):
        """_run_worker fetches and processes pending jobs until none remain."""
        job = _make_job_row(tmp_path)
        call_count = [0]

        def fetch_next(chat_id):
            call_count[0] += 1
            if call_count[0] == 1:
                return job
            return None

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_sm.fetch_next_pending_job.side_effect = fetch_next
            mock_sm.update_job_status = Mock()
            with patch.object(queue.encoder, '_encode_with_retry', new_callable=AsyncMock):
                with patch('src.utils.priority_gate.wait_while_busy', new_callable=AsyncMock):
                    with patch('shutil.rmtree'):
                        await queue._run_worker("123")

        assert "123" not in queue._active

    @pytest.mark.asyncio
    async def test_run_worker_marks_job_done_on_success(self, queue, tmp_path):
        """_run_worker updates job status to 'done' after successful encode."""
        job = _make_job_row(tmp_path)
        statuses = []

        def fetch_next(chat_id):
            return job if not statuses else None

        def update_status(job_id, status):
            statuses.append(status)

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_sm.fetch_next_pending_job.side_effect = fetch_next
            mock_sm.update_job_status.side_effect = update_status
            with patch.object(queue.encoder, '_encode_with_retry', new_callable=AsyncMock):
                with patch('src.utils.priority_gate.wait_while_busy', new_callable=AsyncMock):
                    with patch('shutil.rmtree'):
                        await queue._run_worker("123")

        assert 'processing' in statuses
        assert 'done' in statuses

    @pytest.mark.asyncio
    async def test_run_worker_marks_job_failed_on_error(self, queue, tmp_path):
        """_run_worker updates job status to 'failed' if encoding throws."""
        job = _make_job_row(tmp_path)
        statuses = []

        def fetch_next(chat_id):
            return job if not statuses else None

        def update_status(job_id, status):
            statuses.append(status)

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_sm.fetch_next_pending_job.side_effect = fetch_next
            mock_sm.update_job_status.side_effect = update_status
            with patch.object(queue.encoder, '_encode_with_retry', new_callable=AsyncMock,
                               side_effect=RuntimeError("encoding failed")):
                with patch('src.utils.priority_gate.wait_while_busy', new_callable=AsyncMock):
                    await queue._run_worker("123")

        assert 'failed' in statuses
        assert 'done' not in statuses

    @pytest.mark.asyncio
    async def test_run_worker_deletes_folder_after_success(self, queue, tmp_path):
        """_run_worker removes frame folder after successful encode."""
        job = _make_job_row(tmp_path)
        deleted = []

        def fetch_next(chat_id):
            return job if not deleted else None

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_sm.fetch_next_pending_job.side_effect = fetch_next
            mock_sm.update_job_status = Mock(side_effect=lambda *a: deleted.append(a))
            with patch.object(queue.encoder, '_encode_with_retry', new_callable=AsyncMock):
                with patch('src.utils.priority_gate.wait_while_busy', new_callable=AsyncMock):
                    with patch('shutil.rmtree') as mock_rm:
                        await queue._run_worker("123")

        mock_rm.assert_called_once_with(Path(job.folder_path))

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_active_workers(self, queue):
        """shutdown() returns once _active set is empty."""
        queue._active.add("123")

        async def clear_active():
            await asyncio.sleep(0.05)
            queue._active.discard("123")

        asyncio.create_task(clear_active())
        await asyncio.wait_for(queue.shutdown(), timeout=2.0)
        assert len(queue._active) == 0

    @pytest.mark.asyncio
    async def test_startup_recovery_triggers_workers(self, queue):
        """startup_recovery calls trigger_worker for each chat with pending jobs."""
        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_sm.reset_stuck_jobs = Mock()
            mock_sm.cleanup_orphaned_folders = Mock()
            mock_sm.get_chats_with_pending_jobs.return_value = ["111", "222"]
            mock_sm.prune_done_jobs = Mock()
            with patch.object(queue, 'trigger_worker') as mock_trigger:
                with patch('asyncio.create_task', side_effect=lambda coro: coro.close() or Mock()) as mock_create_task:
                    await queue.startup_recovery()

        mock_sm.reset_stuck_jobs.assert_called_once()
        mock_sm.cleanup_orphaned_folders.assert_called_once()
        assert mock_trigger.call_count == 2
        mock_create_task.assert_called_once()  # prune task created


class TestPruneDoneJobs:
    """Tests for StateManager.prune_done_jobs() and TimelapseEncodingQueue._run_prune_loop()."""

    def test_prune_done_jobs_deletes_old_done(self, db_manager, tmp_path):
        """Old 'done' jobs are deleted; recent done, failed, and pending are kept."""
        from src.utils.state_manager import StateManager
        from datetime import datetime, timedelta

        sm = StateManager(tmp_path)

        now = datetime.utcnow()
        old = (now - timedelta(days=2)).isoformat()
        recent = (now - timedelta(hours=1)).isoformat()

        # Insert four rows directly
        sm.connection.execute(
            "INSERT INTO timelapse_jobs (chat_id, folder_path, timestamp, fps, compositing_context, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("1", "/frames/1", "2026-01-01T00:00:00", 10, "{}", "done", old, old),
        )
        sm.connection.execute(
            "INSERT INTO timelapse_jobs (chat_id, folder_path, timestamp, fps, compositing_context, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("2", "/frames/2", "2026-01-01T00:00:00", 10, "{}", "done", recent, recent),
        )
        sm.connection.execute(
            "INSERT INTO timelapse_jobs (chat_id, folder_path, timestamp, fps, compositing_context, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("3", "/frames/3", "2026-01-01T00:00:00", 10, "{}", "failed", old, old),
        )
        sm.connection.execute(
            "INSERT INTO timelapse_jobs (chat_id, folder_path, timestamp, fps, compositing_context, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("4", "/frames/4", "2026-01-01T00:00:00", 10, "{}", "pending", old, old),
        )
        sm.connection.commit()

        deleted = sm.prune_done_jobs(older_than_days=1)
        assert deleted == 1

        cursor = sm.connection.execute("SELECT chat_id, status FROM timelapse_jobs ORDER BY chat_id")
        rows = [(r["chat_id"], r["status"]) for r in cursor.fetchall()]
        assert ("1", "done") not in rows
        assert ("2", "done") in rows
        assert ("3", "failed") in rows
        assert ("4", "pending") in rows

    def test_prune_done_jobs_zero_days_disabled(self, db_manager, tmp_path):
        """older_than_days=0 deletes nothing."""
        from src.utils.state_manager import StateManager
        from datetime import datetime, timedelta

        sm = StateManager(tmp_path)
        old = (datetime.utcnow() - timedelta(days=10)).isoformat()
        sm.connection.execute(
            "INSERT INTO timelapse_jobs (chat_id, folder_path, timestamp, fps, compositing_context, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("1", "/frames/1", "2026-01-01T00:00:00", 10, "{}", "done", old, old),
        )
        sm.connection.commit()

        deleted = sm.prune_done_jobs(older_than_days=0)
        assert deleted == 0
        cursor = sm.connection.execute("SELECT COUNT(*) as cnt FROM timelapse_jobs")
        assert cursor.fetchone()["cnt"] == 1

    @pytest.mark.asyncio
    async def test_prune_loop_calls_prune_on_first_iteration(self, queue):
        """_run_prune_loop calls prune_done_jobs immediately on first iteration."""
        prune_calls = []

        async def fake_sleep(_):
            raise asyncio.CancelledError()

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_sm.prune_done_jobs.side_effect = lambda d: prune_calls.append(d)
            with patch('asyncio.sleep', side_effect=fake_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await queue._run_prune_loop()

        assert len(prune_calls) == 1

    @pytest.mark.asyncio
    async def test_prune_loop_continues_after_exception(self, queue):
        """_run_prune_loop does not crash when prune_done_jobs raises."""
        call_count = [0]

        async def fake_sleep(_):
            if call_count[0] >= 2:
                raise asyncio.CancelledError()

        def raise_then_succeed(days):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("db error")

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_sm.prune_done_jobs.side_effect = raise_then_succeed
            with patch('asyncio.sleep', side_effect=fake_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await queue._run_prune_loop()

        assert call_count[0] >= 2
