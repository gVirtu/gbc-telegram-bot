"""Tests for auto_send_split_recap_part utility."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from src.utils.recap_utils import auto_send_split_recap_part


def make_part(part_number, is_rt=False, file_id=None, auto_sent_at=None):
    part = Mock()
    part.part_number = part_number
    part.is_rt = is_rt
    part.file_id = file_id
    part.auto_sent_at = auto_sent_at
    return part


def make_adapter(platform="telegram"):
    adapter = MagicMock()
    adapter.platform = platform
    adapter.send_video = AsyncMock(return_value="file_id_123")
    return adapter


class TestAutoSendSplitRecapPart:

    @pytest.mark.asyncio
    async def test_skips_when_leader_has_no_auto_send_recaps_flag(self):
        """Does nothing if the leader chat doesn't have auto_send_recaps enabled."""
        with patch("src.utils.recap_utils.state_manager") as mock_sm:
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                feature_flags={}
            )

            await auto_send_split_recap_part(100, "20260221", 1, False)

            mock_sm.get_mirror_chat_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_only_the_target_part_to_leader(self):
        """Only the specific finalized part is sent to the leader."""
        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.send_recap_to_chat") as mock_send,
            patch("src.utils.recap_utils.get_adapter") as mock_get_adapter,
            patch("src.utils.recap_utils.is_media_only_mirror", return_value=False),
            patch("src.utils.recap_utils.get_input_handler") as mock_get_handler,
        ):
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={"auto_send_recaps": True}
            )
            part1 = make_part(1)
            part2 = make_part(2)
            mock_sm.get_recap_parts = AsyncMock(return_value=[part1, part2])
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
            mock_get_adapter.return_value = make_adapter()
            mock_send.return_value = True
            mock_handler = MagicMock()
            mock_handler.resume_game = AsyncMock()
            mock_get_handler.return_value = mock_handler

            await auto_send_split_recap_part(100, "20260221", 1, False)

            # send_recap_to_chat called with only part1 in parts_to_send
            call_kwargs = mock_send.call_args.kwargs
            assert call_kwargs["parts_to_send"] == [part1]

    @pytest.mark.asyncio
    async def test_marks_auto_sent_at_after_all_recipients(self):
        """auto_sent_at is marked after all recipients have been handled."""
        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.send_recap_to_chat") as mock_send,
            patch("src.utils.recap_utils.get_adapter") as mock_get_adapter,
            patch("src.utils.recap_utils.is_media_only_mirror", return_value=False),
            patch("src.utils.recap_utils.get_input_handler") as mock_get_handler,
        ):
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={"auto_send_recaps": True}
            )
            part1 = make_part(1)
            mock_sm.get_recap_parts = AsyncMock(return_value=[part1])
            mock_sm.get_mirror_chat_ids.return_value = [200]
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
            mock_get_adapter.return_value = make_adapter()
            mock_send.return_value = True
            mock_handler = MagicMock()
            mock_handler.resume_game = AsyncMock()
            mock_get_handler.return_value = mock_handler

            await auto_send_split_recap_part(100, "20260221", 1, False)

            # Both recipients sent, then mark_recap_part_auto_sent called once
            assert mock_send.call_count == 2  # leader + mirror
            mock_sm.mark_recap_part_auto_sent.assert_called_once_with(100, "20260221", 1, False)

    @pytest.mark.asyncio
    async def test_excludes_media_only_mirrors(self):
        """Media-only mirrors are not included as recipients."""
        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.send_recap_to_chat") as mock_send,
            patch("src.utils.recap_utils.get_adapter") as mock_get_adapter,
            patch("src.utils.recap_utils.is_media_only_mirror") as mock_media_only,
            patch("src.utils.recap_utils.get_input_handler") as mock_get_handler,
        ):
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={"auto_send_recaps": True}
            )
            part1 = make_part(1)
            mock_sm.get_recap_parts = AsyncMock(return_value=[part1])
            mock_sm.get_mirror_chat_ids.return_value = [200]
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
            mock_media_only.return_value = True  # mirror is media-only
            mock_get_adapter.return_value = make_adapter()
            mock_send.return_value = True
            mock_handler = MagicMock()
            mock_handler.resume_game = AsyncMock()
            mock_get_handler.return_value = mock_handler

            await auto_send_split_recap_part(100, "20260221", 1, False)

            # Only leader (100), not mirror (200)
            sent_to = [call.args[0] for call in mock_send.call_args_list]
            assert 100 in sent_to
            assert 200 not in sent_to

    @pytest.mark.asyncio
    async def test_resumes_game_after_successful_send(self):
        """resume_game is called for each successful send."""
        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.send_recap_to_chat") as mock_send,
            patch("src.utils.recap_utils.get_adapter") as mock_get_adapter,
            patch("src.utils.recap_utils.is_media_only_mirror", return_value=False),
            patch("src.utils.recap_utils.get_input_handler") as mock_get_handler,
        ):
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={"auto_send_recaps": True}
            )
            part1 = make_part(1)
            mock_sm.get_recap_parts = AsyncMock(return_value=[part1])
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
            adapter = make_adapter()
            mock_get_adapter.return_value = adapter
            mock_send.return_value = True
            mock_handler = MagicMock()
            mock_handler.resume_game = AsyncMock()
            mock_get_handler.return_value = mock_handler

            await auto_send_split_recap_part(100, "20260221", 1, False)

            mock_handler.resume_game.assert_called_once_with(100, adapter)

    @pytest.mark.asyncio
    async def test_does_not_mark_auto_sent_when_all_sends_fail(self):
        """auto_sent_at not marked if no recipients received the part."""
        with (
            patch("src.utils.recap_utils.state_manager") as mock_sm,
            patch("src.utils.recap_utils.send_recap_to_chat") as mock_send,
            patch("src.utils.recap_utils.get_adapter") as mock_get_adapter,
            patch("src.utils.recap_utils.is_media_only_mirror", return_value=False),
            patch("src.utils.recap_utils.get_input_handler"),
        ):
            mock_sm.get_or_create_chat_config.return_value = MagicMock(
                platform="telegram", feature_flags={"auto_send_recaps": True}
            )
            part1 = make_part(1)
            mock_sm.get_recap_parts = AsyncMock(return_value=[part1])
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.mark_recap_part_auto_sent = AsyncMock()
            mock_get_adapter.return_value = make_adapter()
            mock_send.return_value = False  # send fails

            await auto_send_split_recap_part(100, "20260221", 1, False)

            mock_sm.mark_recap_part_auto_sent.assert_not_called()
