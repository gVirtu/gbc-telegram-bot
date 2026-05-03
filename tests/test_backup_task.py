"""Tests for the backup task loop."""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from src.tasks.backup_task import _run_backup_cycle, run_backup_loop


class TestRunBackupCycle:
    @pytest.mark.asyncio
    async def test_backup_cycle_runs_for_active_chats(self):
        backup_manager = MagicMock()
        backup_manager.get_active_chat_ids = AsyncMock(return_value=[10, 20])
        backup_manager.create_backup = AsyncMock(return_value=True)
        backup_manager.purge_old_backups = MagicMock(return_value=0)

        await _run_backup_cycle(backup_manager)

        backup_manager.get_active_chat_ids.assert_called_once()
        assert backup_manager.create_backup.call_count == 2
        backup_manager.create_backup.assert_any_call(10)
        backup_manager.create_backup.assert_any_call(20)
        assert backup_manager.purge_old_backups.call_count == 2

    @pytest.mark.asyncio
    async def test_backup_cycle_skips_failed_chat(self):
        """A chat that raises should not stop processing of other chats."""
        backup_manager = MagicMock()
        backup_manager.get_active_chat_ids = AsyncMock(return_value=[10, 20, 30])

        async def create_backup_with_failure(chat_id):
            if chat_id == 20:
                raise RuntimeError("simulated failure")
            return True

        backup_manager.create_backup = AsyncMock(side_effect=create_backup_with_failure)
        backup_manager.purge_old_backups = MagicMock(return_value=0)

        await _run_backup_cycle(backup_manager)

        assert backup_manager.create_backup.call_count == 3
        assert backup_manager.purge_old_backups.call_count == 2
        backup_manager.purge_old_backups.assert_any_call(10)
        backup_manager.purge_old_backups.assert_any_call(30)

    @pytest.mark.asyncio
    async def test_backup_cycle_does_not_purge_when_backup_fails(self):
        """Purge should not be called when create_backup returns False."""
        backup_manager = MagicMock()
        backup_manager.get_active_chat_ids = AsyncMock(return_value=[99])
        backup_manager.create_backup = AsyncMock(return_value=False)
        backup_manager.purge_old_backups = MagicMock(return_value=0)

        await _run_backup_cycle(backup_manager)

        backup_manager.purge_old_backups.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_cycle_no_active_chats(self):
        backup_manager = MagicMock()
        backup_manager.get_active_chat_ids = AsyncMock(return_value=[])
        backup_manager.create_backup = AsyncMock()
        backup_manager.purge_old_backups = MagicMock()

        await _run_backup_cycle(backup_manager)

        backup_manager.create_backup.assert_not_called()
        backup_manager.purge_old_backups.assert_not_called()


class TestRunBackupLoop:
    @pytest.mark.asyncio
    async def test_loop_sleeps_until_next_hour_on_startup(self):
        """Loop should sleep until top-of-next-hour before first cycle."""
        backup_manager = MagicMock()
        backup_manager.get_active_chat_ids = AsyncMock(return_value=[])
        backup_manager.create_backup = AsyncMock(return_value=True)
        backup_manager.purge_old_backups = MagicMock(return_value=0)

        settings = MagicMock()
        sleep_durations = []

        async def capture_sleep(seconds):
            sleep_durations.append(seconds)
            raise asyncio.CancelledError()

        with patch("src.tasks.backup_task.asyncio.sleep", side_effect=capture_sleep):
            with pytest.raises(asyncio.CancelledError):
                await run_backup_loop(backup_manager, settings)

        # First sleep should be > 0 and <= 3600 (time until next hour)
        assert len(sleep_durations) == 1
        assert 0 < sleep_durations[0] <= 3600

    @pytest.mark.asyncio
    async def test_loop_runs_cycle_then_sleeps_3600(self):
        """After startup sleep, loop should run a cycle and sleep 3600s."""
        backup_manager = MagicMock()
        backup_manager.get_active_chat_ids = AsyncMock(return_value=[42])
        backup_manager.create_backup = AsyncMock(return_value=True)
        backup_manager.purge_old_backups = MagicMock(return_value=0)

        settings = MagicMock()
        sleep_call_count = 0

        async def sleep_side_effect(seconds):
            nonlocal sleep_call_count
            sleep_call_count += 1
            if sleep_call_count == 1:
                # First sleep: startup alignment — let it pass
                return
            # Second sleep: should be 3600
            assert seconds == 3600
            raise asyncio.CancelledError()

        with patch("src.tasks.backup_task.asyncio.sleep", side_effect=sleep_side_effect):
            with pytest.raises(asyncio.CancelledError):
                await run_backup_loop(backup_manager, settings)

        # Backup cycle should have run once (after the startup sleep)
        backup_manager.get_active_chat_ids.assert_called_once()
        backup_manager.create_backup.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_loop_cancels_cleanly_during_startup_sleep(self):
        """CancelledError during startup sleep should propagate cleanly."""
        backup_manager = MagicMock()
        backup_manager.get_active_chat_ids = AsyncMock(return_value=[])

        settings = MagicMock()

        with patch("src.tasks.backup_task.asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await run_backup_loop(backup_manager, settings)

        backup_manager.get_active_chat_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_retries_after_error(self):
        """An exception in the backup cycle should cause a 60s retry sleep."""
        backup_manager = MagicMock()
        backup_manager.get_active_chat_ids = AsyncMock(
            side_effect=[RuntimeError("boom"), []]
        )
        backup_manager.create_backup = AsyncMock(return_value=True)
        backup_manager.purge_old_backups = MagicMock(return_value=0)

        settings = MagicMock()
        sleep_durations = []
        call_count = 0

        async def sleep_side_effect(seconds):
            nonlocal call_count
            call_count += 1
            sleep_durations.append(seconds)
            if call_count == 1:
                # Startup alignment sleep
                return
            if call_count == 2:
                # Error retry sleep: should be 60
                return
            # Third sleep is 3600 after successful cycle
            raise asyncio.CancelledError()

        with patch("src.tasks.backup_task.asyncio.sleep", side_effect=sleep_side_effect):
            with pytest.raises(asyncio.CancelledError):
                await run_backup_loop(backup_manager, settings)

        assert sleep_durations[1] == 60
        assert sleep_durations[2] == 3600
