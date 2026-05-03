"""Tests for realtime_recaps feature."""

import pytest
import numpy as np
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from PIL import Image

from src.handlers.commands import recap_command
from src.tasks.timelapse_encoder import TimelapseEncoder
from src.db.manager import DatabaseManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_frames():
    """Create a small list of PNG-encoded test frames."""
    frames = []
    for i in range(5):
        buf = BytesIO()
        Image.fromarray(np.full((144, 160, 3), i * 25, dtype=np.uint8)).save(buf, format="PNG", optimize=False)
        frames.append(buf.getvalue())
    return frames


@pytest.fixture
def test_audio_chunks():
    """Create a small list of stereo int8 audio chunks."""
    return [np.zeros((100, 2), dtype=np.int8) for _ in range(3)]


@pytest.fixture
def db_manager(tmp_path):
    """Create a real in-memory database manager."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    return manager


@pytest.fixture
def encoder(db_manager):
    """Create a TimelapseEncoder backed by the test db."""
    return TimelapseEncoder(db_manager)


def make_ctx(mock_adapter, args=None, chat_id=123):
    from src.adapters.base import CommandContext
    return CommandContext(
        chat_id=chat_id,
        user_id=456,
        user_name="TestUser",
        args=args or [],
        adapter=mock_adapter,
        raw=None,
    )


# ---------------------------------------------------------------------------
# Tests for save_frames_as_mp4_with_audio
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests for TimelapseEncoder._do_encode_and_append routing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Direct tests for _create_new_realtime_timelapse and _append_realtime_frames
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests for recap_command with realtime_recaps flag
# ---------------------------------------------------------------------------


class TestRecapCommandRealtimeRecaps:
    """Tests for recap_command using the realtime_recaps feature flag."""

    @pytest.mark.asyncio
    async def test_recap_uses_rt_mp4_when_flag_on_and_file_exists(self, mock_adapter, tmp_path):
        """When realtime_recaps flag is on and _rt.mp4 exists, send_video uses _rt.mp4."""
        ctx = make_ctx(mock_adapter, args=["20260312"])

        # Create the _rt.mp4 file (last/only part uses suffixless name)
        rt_video_path = tmp_path / "data" / "recaps" / "123" / "recap_20260312_rt.mp4"
        rt_video_path.parent.mkdir(parents=True, exist_ok=True)
        rt_video_path.write_bytes(b"fake realtime video data")

        mock_record = Mock()
        mock_record.file_id = None

        mock_adapter.send_video = AsyncMock(return_value=None)

        mock_leader_config = Mock()
        mock_leader_config.feature_flags = {"realtime_recaps": True}

        mock_rt_part = Mock()
        mock_rt_part.part_number = 1
        mock_rt_part.is_rt = True
        mock_rt_part.file_id = None

        with patch("src.handlers.commands.state_manager") as mock_commands_sm:
            mock_commands_sm.get_recap_file = AsyncMock(return_value=mock_record)

            with patch("src.utils.recap_utils.state_manager") as mock_utils_sm:
                mock_utils_sm.get_or_create_chat_config = Mock(return_value=mock_leader_config)
                mock_utils_sm.get_recap_parts = AsyncMock(return_value=[mock_rt_part])
                mock_utils_sm.update_recap_file_id = AsyncMock()

                with patch("src.utils.recap_utils.settings") as mock_settings:
                    mock_settings.data_dir = tmp_path / "data"
                    mock_settings.recap_part_send_delay_seconds = 10.0

                    await recap_command(ctx)

        # send_video should have been called exactly once
        mock_adapter.send_video.assert_called_once()
        # Verify the video argument is a file-like object (opened _rt.mp4)
        call_kwargs = mock_adapter.send_video.call_args
        # The video kwarg should be an open file handle (not a string file_id)
        video_arg = call_kwargs.kwargs.get("video") or call_kwargs[1].get("video")
        assert hasattr(video_arg, "read"), "Expected a file-like object for the _rt.mp4"

    @pytest.mark.asyncio
    async def test_recap_falls_back_to_regular_when_flag_off(self, mock_adapter, tmp_path):
        """When realtime_recaps flag is off, send_recap_to_chat is called for the regular path."""
        ctx = make_ctx(mock_adapter, args=["20260312"])

        # Create both the regular and the _rt.mp4 files
        regular_video_path = tmp_path / "data" / "recaps" / "123" / "recap_20260312.mp4"
        rt_video_path = tmp_path / "data" / "recaps" / "123" / "recap_20260312_rt.mp4"
        regular_video_path.parent.mkdir(parents=True, exist_ok=True)
        regular_video_path.write_bytes(b"fake regular video data")
        rt_video_path.write_bytes(b"fake realtime video data")

        mock_record = Mock()
        mock_record.file_id = None

        # feature_flags WITHOUT "realtime_recaps"
        mock_leader_config = Mock()
        mock_leader_config.feature_flags = {}

        with patch("src.handlers.commands.state_manager") as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=mock_record)
            mock_state_manager.get_or_create_chat_config = Mock(return_value=mock_leader_config)

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.data_dir = tmp_path / "data"

                with patch("src.handlers.commands.send_recap_to_chat", new_callable=AsyncMock) as mock_send:
                    mock_send.return_value = True
                    await recap_command(ctx)
                    mock_send.assert_called_once_with(123, 123, "20260312", mock_adapter)


# ---------------------------------------------------------------------------
# Tests for TimelapseEncoder split logic
# ---------------------------------------------------------------------------


class TestTimelapseEncoderSplitLogic:
    """Tests for _check_and_split_if_needed and _get_current_part_number."""

    @pytest.mark.asyncio
    async def test_no_split_when_file_below_threshold(self, encoder, tmp_path):
        """File below threshold does not trigger rename or DB split."""
        video_path = tmp_path / "recap_20260312.mp4"
        video_path.write_bytes(b"small")

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.recap_part_file_size_threshold = 10 * 1024 * 1024

            with patch.object(encoder.db_manager, "split_recap_part", new_callable=AsyncMock) as mock_split:
                await encoder._check_and_split_if_needed(123, "20260312", video_path, False, 1)

        assert video_path.exists()
        mock_split.assert_not_called()

    @pytest.mark.asyncio
    async def test_split_when_file_exceeds_threshold(self, encoder, tmp_path):
        """File over threshold is renamed to _partN and DB split is called."""
        video_path = tmp_path / "recap_20260312.mp4"
        video_path.write_bytes(b"x" * 100)

        mock_task = MagicMock()

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.recap_part_file_size_threshold = 50  # very low threshold

            with patch.object(encoder.db_manager, "split_recap_part", new_callable=AsyncMock) as mock_split:
                with patch("src.tasks.timelapse_encoder.asyncio.create_task", return_value=mock_task):
                    with patch("src.tasks.timelapse_encoder.auto_send_split_recap_part", new_callable=MagicMock):
                        await encoder._check_and_split_if_needed(123, "20260312", video_path, False, 1)

        part_path = tmp_path / "recap_20260312_part1.mp4"
        assert part_path.exists()
        assert not video_path.exists()
        mock_split.assert_called_once_with(123, "20260312", 1, False)

    @pytest.mark.asyncio
    async def test_split_rt_uses_rt_suffix(self, encoder, tmp_path):
        """RT splits use _rt suffix in the part filename."""
        video_path = tmp_path / "recap_20260312_rt.mp4"
        video_path.write_bytes(b"x" * 100)

        mock_task = MagicMock()

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.recap_part_file_size_threshold = 50

            with patch.object(encoder.db_manager, "split_recap_part", new_callable=AsyncMock) as mock_split:
                with patch("src.tasks.timelapse_encoder.asyncio.create_task", return_value=mock_task):
                    with patch("src.tasks.timelapse_encoder.auto_send_split_recap_part", new_callable=MagicMock):
                        await encoder._check_and_split_if_needed(123, "20260312", video_path, True, 2)

        part_path = tmp_path / "recap_20260312_part2_rt.mp4"
        assert part_path.exists()
        assert not video_path.exists()
        mock_split.assert_called_once_with(123, "20260312", 2, True)

    @pytest.mark.asyncio
    async def test_no_split_when_file_missing(self, encoder, tmp_path):
        """Missing file does not raise and does not trigger split."""
        video_path = tmp_path / "nonexistent.mp4"

        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.recap_part_file_size_threshold = 1

            with patch.object(encoder.db_manager, "split_recap_part", new_callable=AsyncMock) as mock_split:
                await encoder._check_and_split_if_needed(123, "20260312", video_path, False, 1)

        mock_split.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_current_part_number_defaults_to_1_when_no_parts(self, encoder):
        """Returns 1 when no DB rows exist for the chat/date/is_rt."""
        result = await encoder._get_current_part_number(123, "20260312", False)
        assert result == 1

    @pytest.mark.asyncio
    async def test_get_current_part_number_returns_highest(self, encoder):
        """Returns the highest part_number from DB rows."""
        await encoder.db_manager.upsert_recap_metadata(123, "20260312", 100, 10.0, 1000, part_number=1)
        await encoder.db_manager.split_recap_part(123, "20260312", 1, False)

        result = await encoder._get_current_part_number(123, "20260312", False)
        assert result == 2

