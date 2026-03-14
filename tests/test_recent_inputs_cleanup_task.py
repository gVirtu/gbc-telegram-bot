"""Tests for the recent_inputs cleanup task loop."""

import asyncio
import os
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from src.tasks.recent_inputs_cleanup_task import _run_cleanup_cycle, run_recent_inputs_cleanup_loop


class TestRunCleanupCycle:
    @pytest.mark.asyncio
    async def test_cleanup_calls_purge_with_correct_days(self):
        """purge_old_recent_inputs should be called with the configured retention days."""
        db_manager = MagicMock()
        db_manager.purge_old_recent_inputs = MagicMock(return_value=5)

        settings = MagicMock()
        settings.recent_inputs_max_retention_days = 3

        await _run_cleanup_cycle(db_manager, settings)

        db_manager.purge_old_recent_inputs.assert_called_once_with(3)

    @pytest.mark.asyncio
    async def test_cleanup_skips_purge_when_zero(self):
        """purge_old_recent_inputs should NOT be called when retention_days is 0."""
        db_manager = MagicMock()
        db_manager.purge_old_recent_inputs = MagicMock()

        settings = MagicMock()
        settings.recent_inputs_max_retention_days = 0

        await _run_cleanup_cycle(db_manager, settings)

        db_manager.purge_old_recent_inputs.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_handles_zero_deleted_rows(self):
        """Cycle should complete without error when no rows are deleted."""
        db_manager = MagicMock()
        db_manager.purge_old_recent_inputs = MagicMock(return_value=0)

        settings = MagicMock()
        settings.recent_inputs_max_retention_days = 7

        await _run_cleanup_cycle(db_manager, settings)

        db_manager.purge_old_recent_inputs.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_cleanup_handles_purge_exception(self):
        """Cycle should not raise even if purge_old_recent_inputs raises."""
        db_manager = MagicMock()
        db_manager.purge_old_recent_inputs = MagicMock(side_effect=RuntimeError("db error"))

        settings = MagicMock()
        settings.recent_inputs_max_retention_days = 2

        # Should not raise
        await _run_cleanup_cycle(db_manager, settings)


class TestRunRecentInputsCleanupLoop:
    @pytest.mark.asyncio
    async def test_startup_runs_cleanup_immediately(self):
        """Loop should run one cleanup cycle immediately on startup, then sleep."""
        db_manager = MagicMock()
        db_manager.purge_old_recent_inputs = MagicMock(return_value=0)

        settings = MagicMock()
        settings.recent_inputs_max_retention_days = 2

        async def cancel_after_first_sleep(seconds):
            raise asyncio.CancelledError()

        with patch(
            "src.tasks.recent_inputs_cleanup_task.asyncio.sleep",
            side_effect=cancel_after_first_sleep,
        ):
            with pytest.raises(asyncio.CancelledError):
                await run_recent_inputs_cleanup_loop(db_manager, settings)

        # The startup cycle should have run
        db_manager.purge_old_recent_inputs.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_cleanup_loop_cancels_cleanly(self):
        """CancelledError should propagate cleanly from the loop."""
        db_manager = MagicMock()
        db_manager.purge_old_recent_inputs = MagicMock(return_value=0)

        settings = MagicMock()
        settings.recent_inputs_max_retention_days = 2

        with patch(
            "src.tasks.recent_inputs_cleanup_task.asyncio.sleep",
            side_effect=asyncio.CancelledError,
        ):
            with pytest.raises(asyncio.CancelledError):
                await run_recent_inputs_cleanup_loop(db_manager, settings)
