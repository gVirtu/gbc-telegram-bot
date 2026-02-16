"""Tests for BackupManager."""

import os
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from src.utils.backup_manager import BackupManager


def _make_backup_manager(tmp_path: Path):
    """Create a BackupManager wired to a temp data directory."""
    mock_state_manager = MagicMock()
    mock_game_mgr = MagicMock()
    mock_settings = MagicMock()
    mock_settings.data_dir = tmp_path
    mock_settings.backup_retention_days = 30

    def get_chat_backup_dir(chat_id):
        d = tmp_path / "backups" / str(chat_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    mock_settings.get_chat_backup_dir = get_chat_backup_dir

    return BackupManager(mock_state_manager, mock_game_mgr, mock_settings)


class TestCreateBackup:
    @pytest.mark.asyncio
    async def test_create_backup_writes_file(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        mock_controller = MagicMock()
        mock_controller.save_state.return_value = b"game_state_bytes"
        bm._game_controller_manager.get_or_create_controller = AsyncMock(
            return_value=mock_controller
        )

        today = datetime.utcnow().strftime("%Y%m%d")
        result = await bm.create_backup(chat_id=111)

        assert result is True
        expected = tmp_path / "backups" / "111" / f"backup_{today}.state"
        assert expected.exists()
        assert expected.read_bytes() == b"game_state_bytes"

    @pytest.mark.asyncio
    async def test_create_backup_skips_if_exists(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        today = datetime.utcnow().strftime("%Y%m%d")
        backup_dir = tmp_path / "backups" / "222"
        backup_dir.mkdir(parents=True)
        existing = backup_dir / f"backup_{today}.state"
        existing.write_bytes(b"old_data")

        mock_controller = MagicMock()
        mock_controller.save_state.return_value = b"new_data"
        bm._game_controller_manager.get_or_create_controller = AsyncMock(
            return_value=mock_controller
        )

        result = await bm.create_backup(chat_id=222)

        assert result is True
        # File should not have been overwritten
        assert existing.read_bytes() == b"old_data"
        bm._game_controller_manager.get_or_create_controller.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_backup_returns_false_if_no_controller(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        bm._game_controller_manager.get_or_create_controller = AsyncMock(return_value=None)

        result = await bm.create_backup(chat_id=333)

        assert result is False
        # No file should exist
        backup_dir = tmp_path / "backups" / "333"
        assert not any(backup_dir.glob("*.state")) if backup_dir.exists() else True


class TestLoadBackup:
    def test_load_backup_returns_bytes(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        backup_dir = tmp_path / "backups" / "444"
        backup_dir.mkdir(parents=True)
        (backup_dir / "backup_20260101.state").write_bytes(b"saved_bytes")

        result = bm.load_backup(chat_id=444, date_str="20260101")

        assert result == b"saved_bytes"

    def test_load_backup_returns_none_for_missing(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        result = bm.load_backup(chat_id=555, date_str="20260101")
        assert result is None


class TestListBackups:
    def test_list_backups_sorted(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        backup_dir = tmp_path / "backups" / "666"
        backup_dir.mkdir(parents=True)
        for date in ["20260301", "20260101", "20260201"]:
            (backup_dir / f"backup_{date}.state").write_bytes(b"data")

        result = bm.list_backups(chat_id=666)

        assert result == ["20260101", "20260201", "20260301"]

    def test_list_backups_empty_when_no_dir(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        result = bm.list_backups(chat_id=777)
        assert result == []

    def test_list_backups_ignores_other_files(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        backup_dir = tmp_path / "backups" / "888"
        backup_dir.mkdir(parents=True)
        (backup_dir / "backup_20260101.state").write_bytes(b"data")
        (backup_dir / "other_file.txt").write_bytes(b"noise")

        result = bm.list_backups(chat_id=888)

        assert result == ["20260101"]


class TestPurgeOldBackups:
    def test_purge_old_backups_removes_old_files(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        backup_dir = tmp_path / "backups" / "999"
        backup_dir.mkdir(parents=True)

        # Create one very old backup and one recent one
        cutoff = datetime.utcnow() - timedelta(days=31)
        old_date = cutoff.strftime("%Y%m%d")
        today = datetime.utcnow().strftime("%Y%m%d")

        (backup_dir / f"backup_{old_date}.state").write_bytes(b"old")
        (backup_dir / f"backup_{today}.state").write_bytes(b"new")

        deleted = bm.purge_old_backups(chat_id=999)

        assert deleted == 1
        assert not (backup_dir / f"backup_{old_date}.state").exists()
        assert (backup_dir / f"backup_{today}.state").exists()

    def test_purge_old_backups_returns_zero_for_missing_dir(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        deleted = bm.purge_old_backups(chat_id=1234)
        assert deleted == 0

    def test_purge_old_backups_keeps_recent_files(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        backup_dir = tmp_path / "backups" / "1111"
        backup_dir.mkdir(parents=True)

        # Recent backup — within retention window
        recent = (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")
        (backup_dir / f"backup_{recent}.state").write_bytes(b"recent")

        deleted = bm.purge_old_backups(chat_id=1111)

        assert deleted == 0
        assert (backup_dir / f"backup_{recent}.state").exists()


class TestGetActiveChatIds:
    @pytest.mark.asyncio
    async def test_get_active_chat_ids_returns_chat_ids(self, tmp_path):
        bm = _make_backup_manager(tmp_path)

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"chat_id": 10}, {"chat_id": 20}]
        bm._state_manager.connection.execute.return_value = mock_cursor

        result = await bm.get_active_chat_ids()

        assert result == [10, 20]
        bm._state_manager.connection.execute.assert_called_once()
        sql = bm._state_manager.connection.execute.call_args[0][0]
        assert "recent_inputs" in sql
        assert "-24 hours" in sql

    @pytest.mark.asyncio
    async def test_get_active_chat_ids_returns_empty_when_none(self, tmp_path):
        bm = _make_backup_manager(tmp_path)
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        bm._state_manager.connection.execute.return_value = mock_cursor

        result = await bm.get_active_chat_ids()

        assert result == []
