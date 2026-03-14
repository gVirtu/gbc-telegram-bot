"""Tests for the recap broadcaster task and related utilities."""

import asyncio
import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from src.tasks.recap_broadcaster import _run_broadcast_cycle, run_recap_broadcast_loop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_adapter(platform="telegram"):
    adapter = MagicMock()
    adapter.platform = platform
    adapter.send_video = AsyncMock(return_value="file_id_123")
    return adapter


# ---------------------------------------------------------------------------
# get_leaders_with_flag
# ---------------------------------------------------------------------------

class TestGetLeadersWithFlag:
    def test_returns_only_leaders_with_flag(self, tmp_path):
        """Leaders with the flag enabled are returned; mirrors and non-flagged leaders are excluded."""
        from src.db.manager import DatabaseManager
        from src.models.game_state import ChatConfig

        db_path = tmp_path / "bot.db"
        manager = DatabaseManager(db_path=db_path)
        manager.initialize()

        # Leader with flag
        leader = ChatConfig(chat_id=1001, feature_flags={"auto_send_recaps": True})
        manager.save_chat_config(leader)

        # Leader without flag
        leader_no_flag = ChatConfig(chat_id=1002, feature_flags={})
        manager.save_chat_config(leader_no_flag)

        # Mirror with flag (should be excluded)
        mirror = ChatConfig(chat_id=1003, mirrors_chat_id=1001, feature_flags={"auto_send_recaps": True})
        manager.save_chat_config(mirror)

        result = manager.get_leaders_with_flag("auto_send_recaps")
        assert result == [1001]

    def test_returns_empty_when_no_leaders_have_flag(self, tmp_path):
        from src.db.manager import DatabaseManager
        from src.models.game_state import ChatConfig

        db_path = tmp_path / "bot.db"
        manager = DatabaseManager(db_path=db_path)
        manager.initialize()

        leader = ChatConfig(chat_id=2001, feature_flags={"auto_send_recaps": False})
        manager.save_chat_config(leader)

        result = manager.get_leaders_with_flag("auto_send_recaps")
        assert result == []


# ---------------------------------------------------------------------------
# _run_broadcast_cycle
# ---------------------------------------------------------------------------

class TestRunBroadcastCycle:
    @pytest.mark.asyncio
    async def test_skips_silently_when_no_recap_file(self, tmp_path):
        """If the recap mp4 doesn't exist for a leader, skip without sending."""
        with (
            patch("src.tasks.recap_broadcaster.state_manager") as mock_sm,
            patch("src.tasks.recap_broadcaster.settings") as mock_settings,
            patch("src.tasks.recap_broadcaster.get_adapter") as mock_get_adapter,
            patch("src.tasks.recap_broadcaster.send_recap_to_chat") as mock_send,
            patch("src.tasks.recap_broadcaster.get_input_handler"),
        ):
            mock_settings.data_dir = tmp_path
            mock_sm.get_leaders_with_flag.return_value = [100]
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = MagicMock(platform="telegram")
            mock_get_adapter.return_value = make_adapter()

            # No file on disk
            await _run_broadcast_cycle()

            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_excludes_media_only_mirrors(self, tmp_path):
        """Media-only mirror chats should not receive the recap broadcast."""
        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)

        # We need to know yesterday's date to create the file
        from datetime import datetime, timedelta
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")
        (recap_dir / f"{yesterday}.mp4").write_bytes(b"fake video")

        with (
            patch("src.tasks.recap_broadcaster.state_manager") as mock_sm,
            patch("src.tasks.recap_broadcaster.settings") as mock_settings,
            patch("src.tasks.recap_broadcaster.get_adapter") as mock_get_adapter,
            patch("src.tasks.recap_broadcaster.is_media_only_mirror") as mock_media_only,
            patch("src.tasks.recap_broadcaster.send_recap_to_chat") as mock_send,
            patch("src.tasks.recap_broadcaster.get_input_handler") as mock_get_handler,
        ):
            mock_settings.data_dir = tmp_path
            mock_sm.get_leaders_with_flag.return_value = [100]
            mock_sm.get_mirror_chat_ids.return_value = [200, 300]
            # 200 is media-only, 300 is not
            mock_media_only.side_effect = lambda cid: cid == 200
            mock_sm.get_or_create_chat_config.return_value = MagicMock(platform="telegram")
            mock_get_adapter.return_value = make_adapter()
            mock_send.return_value = True

            mock_handler = MagicMock()
            mock_handler.resume_game = AsyncMock()
            mock_get_handler.return_value = mock_handler

            await _run_broadcast_cycle()

            sent_to = [call.args[0] for call in mock_send.call_args_list]
            assert 100 in sent_to  # leader
            assert 300 in sent_to  # non-media-only mirror
            assert 200 not in sent_to  # media-only mirror excluded

    @pytest.mark.asyncio
    async def test_send_success_triggers_resume(self, tmp_path):
        """Successful recap send should trigger resume_game for that chat."""
        from datetime import datetime, timedelta
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")

        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)
        (recap_dir / f"{yesterday}.mp4").write_bytes(b"fake video")

        with (
            patch("src.tasks.recap_broadcaster.state_manager") as mock_sm,
            patch("src.tasks.recap_broadcaster.settings") as mock_settings,
            patch("src.tasks.recap_broadcaster.get_adapter") as mock_get_adapter,
            patch("src.tasks.recap_broadcaster.is_media_only_mirror", return_value=False),
            patch("src.tasks.recap_broadcaster.send_recap_to_chat") as mock_send,
            patch("src.tasks.recap_broadcaster.get_input_handler") as mock_get_handler,
        ):
            mock_settings.data_dir = tmp_path
            mock_sm.get_leaders_with_flag.return_value = [100]
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = MagicMock(platform="telegram")
            adapter = make_adapter()
            mock_get_adapter.return_value = adapter
            mock_send.return_value = True

            mock_handler = MagicMock()
            mock_handler.resume_game = AsyncMock()
            mock_get_handler.return_value = mock_handler

            await _run_broadcast_cycle()

            mock_handler.resume_game.assert_called_once_with(100, adapter)

    @pytest.mark.asyncio
    async def test_send_failure_skips_resume(self, tmp_path):
        """Failed recap send should not trigger resume_game."""
        from datetime import datetime, timedelta
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")

        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)
        (recap_dir / f"{yesterday}.mp4").write_bytes(b"fake video")

        with (
            patch("src.tasks.recap_broadcaster.state_manager") as mock_sm,
            patch("src.tasks.recap_broadcaster.settings") as mock_settings,
            patch("src.tasks.recap_broadcaster.get_adapter") as mock_get_adapter,
            patch("src.tasks.recap_broadcaster.is_media_only_mirror", return_value=False),
            patch("src.tasks.recap_broadcaster.send_recap_to_chat") as mock_send,
            patch("src.tasks.recap_broadcaster.get_input_handler") as mock_get_handler,
        ):
            mock_settings.data_dir = tmp_path
            mock_sm.get_leaders_with_flag.return_value = [100]
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = MagicMock(platform="telegram")
            mock_get_adapter.return_value = make_adapter()
            mock_send.return_value = False

            mock_handler = MagicMock()
            mock_handler.resume_game = AsyncMock()
            mock_get_handler.return_value = mock_handler

            await _run_broadcast_cycle()

            mock_handler.resume_game.assert_not_called()


# ---------------------------------------------------------------------------
# run_recap_broadcast_loop
# ---------------------------------------------------------------------------

class TestRunRecapBroadcastLoop:
    @pytest.mark.asyncio
    async def test_loop_cancels_cleanly(self):
        """CancelledError should propagate cleanly from the loop."""
        with patch("src.tasks.recap_broadcaster.asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await run_recap_broadcast_loop()
