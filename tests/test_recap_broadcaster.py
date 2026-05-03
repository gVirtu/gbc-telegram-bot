"""Tests for the recap broadcaster task and related utilities."""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from unittest.mock import ANY

from src.tasks.recap_broadcaster import _run_broadcast_cycle, run_recap_broadcast_loop
from src.utils.recap_utils import send_recap_to_chat


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
        """If get_unsent_recap_parts returns empty, skip without sending."""
        with (
            patch("src.tasks.recap_broadcaster.state_manager") as mock_sm,
            patch("src.tasks.recap_broadcaster.settings") as mock_settings,
            patch("src.tasks.recap_broadcaster.get_adapter") as mock_get_adapter,
            patch("src.tasks.recap_broadcaster.send_recap_to_chat") as mock_send,
            patch("src.tasks.recap_broadcaster.get_input_handler"),
        ):
            mock_settings.data_dir = tmp_path
            mock_sm.get_leaders_with_flag.return_value = [100]
            mock_sm.get_unsent_recap_parts = AsyncMock(return_value=[])
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={}
            )
            mock_get_adapter.return_value = make_adapter()

            await _run_broadcast_cycle()

            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_excludes_media_only_mirrors(self, tmp_path):
        """Media-only mirror chats should not receive the recap broadcast."""
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
            mock_sm.get_unsent_recap_parts = AsyncMock(return_value=[make_part(1)])
            mock_sm.get_mirror_chat_ids.return_value = [200, 300]
            # 200 is media-only, 300 is not
            mock_media_only.side_effect = lambda cid: cid == 200
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={}
            )
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
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
            mock_sm.get_unsent_recap_parts = AsyncMock(return_value=[make_part(1)])
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={}
            )
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
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
            mock_sm.get_unsent_recap_parts = AsyncMock(return_value=[make_part(1)])
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={}
            )
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
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


# ---------------------------------------------------------------------------
# Tests for send_recap_to_chat multi-part logic
# ---------------------------------------------------------------------------

def make_part(part_number, is_rt=False, file_id=None):
    part = Mock()
    part.part_number = part_number
    part.is_rt = is_rt
    part.file_id = file_id
    return part


class TestSendRecapToChat:
    """Tests for multi-part send_recap_to_chat."""

    @pytest.mark.asyncio
    async def test_no_parts_returns_false(self, tmp_path):
        """Returns False when no parts exist in DB."""
        adapter = make_adapter()
        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.settings") as mock_settings,
        ):
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_send_delay_seconds = 10.0
            mock_sm.get_or_create_chat_config.return_value = MagicMock(feature_flags={})
            mock_sm.get_recap_parts = AsyncMock(return_value=[])

            result = await send_recap_to_chat(100, 100, "20260221", adapter)

        assert result is False
        adapter.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_part_sends_no_delay(self, tmp_path):
        """Single part is sent without delay."""
        adapter = make_adapter()
        video_path = tmp_path / "recaps" / "100" / "recap_20260221.mp4"
        video_path.parent.mkdir(parents=True)
        video_path.write_bytes(b"fake video")

        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.settings") as mock_settings,
            patch("src.utils.recap_utils.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_send_delay_seconds = 10.0
            mock_sm.get_or_create_chat_config.return_value = MagicMock(feature_flags={})
            mock_sm.get_recap_parts = AsyncMock(return_value=[make_part(1)])
            mock_sm.update_recap_file_id = AsyncMock()

            result = await send_recap_to_chat(100, 100, "20260221", adapter)

        assert result is True
        adapter.send_video.assert_called_once()
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_part_sends_delay_between_parts_not_after_last(self, tmp_path):
        """Delay is inserted between parts but NOT after the last part."""
        adapter = make_adapter()
        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)
        # Part 1 uses named file, last part uses suffixless
        (recap_dir / "recap_20260221_part1.mp4").write_bytes(b"part1")
        (recap_dir / "recap_20260221.mp4").write_bytes(b"part2")

        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.settings") as mock_settings,
            patch("src.utils.recap_utils.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_send_delay_seconds = 10.0
            mock_sm.get_or_create_chat_config.return_value = MagicMock(feature_flags={})
            mock_sm.get_recap_parts = AsyncMock(return_value=[make_part(1), make_part(2)])
            mock_sm.update_recap_file_id = AsyncMock()

            result = await send_recap_to_chat(100, 100, "20260221", adapter)

        assert result is True
        assert adapter.send_video.call_count == 2
        mock_sleep.assert_called_once_with(10.0)

    @pytest.mark.asyncio
    async def test_cache_hit_reuses_file_id_per_part(self, tmp_path):
        """File ID is reused for parts that have a cached file_id (Telegram)."""
        adapter = make_adapter(platform="telegram")
        adapter.send_video = AsyncMock(return_value="new_file_id")

        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)
        (recap_dir / "recap_20260221.mp4").write_bytes(b"part1")

        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.settings") as mock_settings,
            patch("src.utils.recap_utils.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_send_delay_seconds = 10.0
            mock_sm.get_or_create_chat_config.return_value = MagicMock(feature_flags={})
            mock_sm.get_recap_parts = AsyncMock(return_value=[make_part(1, file_id="cached_fid")])

            result = await send_recap_to_chat(100, 100, "20260221", adapter)

        assert result is True
        # Called with the cached file_id (not an open file)
        adapter.send_video.assert_called_once()
        call_video_arg = adapter.send_video.call_args.kwargs.get("video")
        assert call_video_arg == "cached_fid"

    @pytest.mark.asyncio
    async def test_cache_miss_falls_back_to_disk(self, tmp_path):
        """Cache failure falls back to disk upload and other parts are unaffected."""
        adapter = make_adapter(platform="telegram")
        # First call (file_id) raises, second (disk) succeeds
        adapter.send_video = AsyncMock(side_effect=[Exception("expired"), "new_file_id"])

        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)
        (recap_dir / "recap_20260221.mp4").write_bytes(b"video")

        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.settings") as mock_settings,
            patch("src.utils.recap_utils.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_send_delay_seconds = 10.0
            mock_sm.get_or_create_chat_config.return_value = MagicMock(feature_flags={})
            mock_sm.get_recap_parts = AsyncMock(return_value=[make_part(1, file_id="stale_fid")])
            mock_sm.update_recap_file_id = AsyncMock()

            result = await send_recap_to_chat(100, 100, "20260221", adapter)

        assert result is True
        assert adapter.send_video.call_count == 2
        # new_file_id should have been cached
        mock_sm.update_recap_file_id.assert_called_once_with(100, "20260221", 1, False, "new_file_id")

    @pytest.mark.asyncio
    async def test_missing_part_file_skipped_send_continues(self, tmp_path):
        """Missing part file is skipped with a warning; remaining parts are still sent."""
        adapter = make_adapter()
        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)
        # Only last part file exists
        (recap_dir / "recap_20260221.mp4").write_bytes(b"part2")
        # Part 1 file intentionally absent

        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.settings") as mock_settings,
            patch("src.utils.recap_utils.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_send_delay_seconds = 10.0
            mock_sm.get_or_create_chat_config.return_value = MagicMock(feature_flags={})
            mock_sm.get_recap_parts = AsyncMock(return_value=[make_part(1), make_part(2)])
            mock_sm.update_recap_file_id = AsyncMock()

            result = await send_recap_to_chat(100, 100, "20260221", adapter)

        # Part 2 was still sent
        assert result is True
        adapter.send_video.assert_called_once()
        # Delay was still applied after the skipped part 1 (before part 2)
        mock_sleep.assert_called_once_with(10.0)

    @pytest.mark.asyncio
    async def test_discord_no_file_id_logic(self, tmp_path):
        """On Discord, file_id cache is never used regardless of parts."""
        adapter = make_adapter(platform="discord")
        adapter.send_video = AsyncMock(return_value=None)

        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)
        (recap_dir / "recap_20260221.mp4").write_bytes(b"video")

        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.settings") as mock_settings,
            patch("src.utils.recap_utils.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_send_delay_seconds = 10.0
            mock_sm.get_or_create_chat_config.return_value = MagicMock(feature_flags={})
            # Part has a file_id but it should NOT be used on Discord
            mock_sm.get_recap_parts = AsyncMock(return_value=[make_part(1, file_id="some_file_id")])
            mock_sm.update_recap_file_id = AsyncMock()

            result = await send_recap_to_chat(100, 100, "20260221", adapter)

        assert result is True
        # Called once with a file-like object (disk upload), not with the file_id string
        adapter.send_video.assert_called_once()
        video_arg = adapter.send_video.call_args.kwargs.get("video")
        assert hasattr(video_arg, "read"), "Expected disk upload on Discord"


# ---------------------------------------------------------------------------
# Tests for send_recap_to_chat with parts_to_send parameter
# ---------------------------------------------------------------------------

class TestSendRecapToChatPartFilter:
    """Tests for send_recap_to_chat with parts_to_send parameter."""

    @pytest.mark.asyncio
    async def test_parts_to_send_restricts_which_parts_are_sent(self, tmp_path):
        """When parts_to_send is provided, only those parts are sent."""
        adapter = make_adapter()
        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)
        (recap_dir / "recap_20260221_part1.mp4").write_bytes(b"part1")
        (recap_dir / "recap_20260221.mp4").write_bytes(b"part2")

        part1 = make_part(1)
        part2 = make_part(2)

        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.settings") as mock_settings,
            patch("src.utils.recap_utils.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_send_delay_seconds = 1.0
            mock_sm.get_or_create_chat_config.return_value = MagicMock(feature_flags={})
            # All parts returned from DB
            mock_sm.get_recap_parts = AsyncMock(return_value=[part1, part2])
            mock_sm.update_recap_file_id = AsyncMock()

            # Only send part2 (the last/current one)
            result = await send_recap_to_chat(100, 100, "20260221", adapter, parts_to_send=[part2])

        assert result is True
        assert adapter.send_video.call_count == 1  # only part2

    @pytest.mark.asyncio
    async def test_caption_shows_total_all_parts_count_not_filtered_count(self, tmp_path):
        """Caption 'part X of Y' uses total parts count even when only subset is sent."""
        adapter = make_adapter()
        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)
        # Only create the last part file (part2 = current unnumbered file)
        (recap_dir / "recap_20260221.mp4").write_bytes(b"part2")

        part1 = make_part(1)
        part2 = make_part(2)

        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.settings") as mock_settings,
            patch("src.utils.recap_utils.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_send_delay_seconds = 1.0
            mock_sm.get_or_create_chat_config.return_value = MagicMock(feature_flags={})
            mock_sm.get_recap_parts = AsyncMock(return_value=[part1, part2])
            mock_sm.update_recap_file_id = AsyncMock()

            await send_recap_to_chat(100, 100, "20260221", adapter, parts_to_send=[part2])

        caption = adapter.send_video.call_args.kwargs["caption"]
        assert "2 of 2" in caption  # total=2, not filtered count=1

    @pytest.mark.asyncio
    async def test_non_last_part_in_filtered_list_uses_numbered_filename(self, tmp_path):
        """Parts that are NOT the overall last use recap_{date}_partN.mp4 path."""
        adapter = make_adapter()
        recap_dir = tmp_path / "recaps" / "100"
        recap_dir.mkdir(parents=True)
        (recap_dir / "recap_20260221_part1.mp4").write_bytes(b"part1")
        (recap_dir / "recap_20260221.mp4").write_bytes(b"part2")

        part1 = make_part(1)
        part2 = make_part(2)

        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.settings") as mock_settings,
            patch("src.utils.recap_utils.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.data_dir = tmp_path
            mock_settings.recap_part_send_delay_seconds = 1.0
            mock_sm.get_or_create_chat_config.return_value = MagicMock(feature_flags={})
            mock_sm.get_recap_parts = AsyncMock(return_value=[part1, part2])
            mock_sm.update_recap_file_id = AsyncMock()

            # Send only part1 (not the overall last)
            result = await send_recap_to_chat(100, 100, "20260221", adapter, parts_to_send=[part1])

        assert result is True
        # The video arg should be an open file from the numbered path
        video_arg = adapter.send_video.call_args.kwargs["video"]
        assert hasattr(video_arg, "read")  # file object, not string


# ---------------------------------------------------------------------------
# Tests for _run_broadcast_cycle with unsent parts
# ---------------------------------------------------------------------------

class TestRunBroadcastCycleUnsentParts:

    @pytest.mark.asyncio
    async def test_skips_leader_when_all_parts_already_auto_sent(self, tmp_path):
        """If all parts for a leader have auto_sent_at set, skip that leader entirely."""
        with (
            patch("src.tasks.recap_broadcaster.state_manager") as mock_sm,
            patch("src.tasks.recap_broadcaster.settings") as mock_settings,
            patch("src.tasks.recap_broadcaster.send_recap_to_chat") as mock_send,
            patch("src.tasks.recap_broadcaster.get_input_handler"),
        ):
            mock_settings.data_dir = tmp_path
            mock_sm.get_leaders_with_flag.return_value = [100]
            # get_unsent_recap_parts returns empty (all already sent)
            mock_sm.get_unsent_recap_parts = AsyncMock(return_value=[])
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={}
            )

            await _run_broadcast_cycle()

            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_only_unsent_parts_not_all_parts(self, tmp_path):
        """Broadcaster passes pre-filtered unsent_parts to send_recap_to_chat."""
        from unittest.mock import Mock
        unsent_part = Mock()
        unsent_part.part_number = 2

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
            mock_sm.get_unsent_recap_parts = AsyncMock(return_value=[unsent_part])
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={}
            )
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
            mock_get_adapter.return_value = make_adapter()
            mock_send.return_value = True
            mock_handler = MagicMock()
            mock_handler.resume_game = AsyncMock()
            mock_get_handler.return_value = mock_handler

            await _run_broadcast_cycle()

            # parts_to_send kwarg should be the unsent list
            call_kwargs = mock_send.call_args.kwargs
            assert call_kwargs.get("parts_to_send") == [unsent_part]

    @pytest.mark.asyncio
    async def test_marks_auto_sent_after_all_recipients(self, tmp_path):
        """After all recipients handled, mark_recap_part_auto_sent called for each unsent part."""
        from unittest.mock import Mock
        unsent_part = Mock()
        unsent_part.part_number = 1
        unsent_part.is_rt = False

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
            mock_sm.get_unsent_recap_parts = AsyncMock(return_value=[unsent_part])
            mock_sm.get_mirror_chat_ids.return_value = [200]
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={}
            )
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
            mock_get_adapter.return_value = make_adapter()
            mock_send.return_value = True
            mock_handler = MagicMock()
            mock_handler.resume_game = AsyncMock()
            mock_get_handler.return_value = mock_handler

            await _run_broadcast_cycle()

            # Both recipients sent, then ONE mark call
            assert mock_send.call_count == 2  # leader + mirror
            mock_sm.mark_recap_part_auto_sent.assert_called_once_with(100, ANY, 1, False)

    @pytest.mark.asyncio
    async def test_does_not_mark_when_send_fails(self, tmp_path):
        """auto_sent_at not marked if all sends fail."""
        from unittest.mock import Mock
        unsent_part = Mock()
        unsent_part.part_number = 1
        unsent_part.is_rt = False

        with (
            patch("src.tasks.recap_broadcaster.state_manager") as mock_sm,
            patch("src.tasks.recap_broadcaster.settings") as mock_settings,
            patch("src.tasks.recap_broadcaster.get_adapter") as mock_get_adapter,
            patch("src.tasks.recap_broadcaster.is_media_only_mirror", return_value=False),
            patch("src.tasks.recap_broadcaster.send_recap_to_chat") as mock_send,
            patch("src.tasks.recap_broadcaster.get_input_handler"),
        ):
            mock_settings.data_dir = tmp_path
            mock_sm.get_leaders_with_flag.return_value = [100]
            mock_sm.get_unsent_recap_parts = AsyncMock(return_value=[unsent_part])
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={}
            )
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
            mock_get_adapter.return_value = make_adapter()
            mock_send.return_value = False

            await _run_broadcast_cycle()

            mock_sm.mark_recap_part_auto_sent.assert_not_called()
