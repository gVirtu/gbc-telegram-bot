"""Tests for the backup task loop."""

import asyncio
import os
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call

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

        # All three chats should have been attempted
        assert backup_manager.create_backup.call_count == 3
        # Purge only called for successful chats (10 and 30)
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
    async def test_startup_runs_backup_cycle_immediately(self):
        """Loop should run one backup cycle immediately on startup, then sleep."""
        backup_manager = MagicMock()
        backup_manager.get_active_chat_ids = AsyncMock(return_value=[42])
        backup_manager.create_backup = AsyncMock(return_value=True)
        backup_manager.purge_old_backups = MagicMock(return_value=0)

        settings = MagicMock()
        settings.backup_hour = 0
        settings.backup_minute = 0

        # Cancel the task quickly after the first cycle to avoid infinite loop
        async def cancel_after_first_sleep(seconds):
            raise asyncio.CancelledError()

        with patch("src.tasks.backup_task.asyncio.sleep", side_effect=cancel_after_first_sleep):
            with pytest.raises(asyncio.CancelledError):
                await run_backup_loop(backup_manager, settings)

        # The startup cycle should have run
        backup_manager.get_active_chat_ids.assert_called_once()
        backup_manager.create_backup.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_loop_cancels_cleanly(self):
        """CancelledError should propagate cleanly from the loop."""
        backup_manager = MagicMock()
        backup_manager.get_active_chat_ids = AsyncMock(return_value=[])
        backup_manager.create_backup = AsyncMock()
        backup_manager.purge_old_backups = MagicMock()

        settings = MagicMock()
        settings.backup_hour = 0
        settings.backup_minute = 0

        with patch("src.tasks.backup_task.asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await run_backup_loop(backup_manager, settings)
