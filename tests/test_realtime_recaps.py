"""Tests for realtime_recaps feature."""

import asyncio
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call

from src.handlers.commands import recap_command
from src.tasks.timelapse_encoder import TimelapseEncoder
from src.utils.frame_utils import save_frames_as_mp4_with_audio
from src.db.manager import DatabaseManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_frames():
    """Create a small list of test frames."""
    return [np.full((144, 160, 3), i * 25, dtype=np.uint8) for i in range(5)]


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


class TestSaveFramesAsMp4WithAudio:
    """Tests for the save_frames_as_mp4_with_audio function."""

    @pytest.mark.asyncio
    async def test_with_audio_uses_audio_ffmpeg_flags(self, test_frames, test_audio_chunks, tmp_path):
        """When audio_chunks is non-empty, FFmpeg command should include -f s16le and -c:a aac."""
        output_path = str(tmp_path / "out.mp4")
        captured_cmd = []

        async def fake_subprocess(*cmd, **kwargs):
            captured_cmd.extend(cmd)
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.stdin.write = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess):
            await save_frames_as_mp4_with_audio(test_frames, test_audio_chunks, output_path)

        assert "-f" in captured_cmd
        idx_f = [i for i, v in enumerate(captured_cmd) if v == "-f"]
        # There should be at least one '-f s16le' pair
        assert any(captured_cmd[i + 1] == "s16le" for i in idx_f)
        assert "-c:a" in captured_cmd
        aac_idx = captured_cmd.index("-c:a")
        assert captured_cmd[aac_idx + 1] == "aac"

    @pytest.mark.asyncio
    async def test_without_audio_uses_an_flag(self, test_frames, tmp_path):
        """When audio_chunks is empty, FFmpeg command should include -an."""
        output_path = str(tmp_path / "out.mp4")
        captured_cmd = []

        async def fake_subprocess(*cmd, **kwargs):
            captured_cmd.extend(cmd)
            proc = MagicMock()
            proc.stdin = MagicMock()
            proc.stdin.write = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess):
            await save_frames_as_mp4_with_audio(test_frames, [], output_path)

        assert "-an" in captured_cmd
        assert "-c:a" not in captured_cmd
        assert "s16le" not in captured_cmd


# ---------------------------------------------------------------------------
# Tests for TimelapseEncoder._do_encode_and_append routing
# ---------------------------------------------------------------------------


class TestTimelapseEncoderRouting:
    """Tests that _do_encode_and_append routes to the correct method."""

    @pytest.mark.asyncio
    async def test_routes_to_realtime_when_audio_chunks_present(self, encoder, test_frames, test_audio_chunks, tmp_path):
        """When audio_chunks is non-empty, _create_new_realtime_timelapse should be called."""
        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.data_dir = tmp_path / "data"

            with patch.object(encoder, "_create_new_realtime_timelapse", new_callable=AsyncMock) as mock_rt:
                with patch.object(encoder, "_create_new_timelapse", new_callable=AsyncMock) as mock_regular:
                    with patch.object(encoder, "_update_recap_metadata", new_callable=AsyncMock):
                        with patch("fcntl.flock"):
                            await encoder._do_encode_and_append(
                                chat_id=123,
                                frames=test_frames,
                                timestamp="2026-03-12T10:00:00",
                                audio_chunks=test_audio_chunks,
                                fps=15,
                            )

            mock_rt.assert_called_once()
            mock_regular.assert_not_called()

    @pytest.mark.asyncio
    async def test_routes_to_regular_when_audio_chunks_none(self, encoder, test_frames, tmp_path):
        """When audio_chunks is None, _create_new_timelapse should be called."""
        with patch("src.tasks.timelapse_encoder.settings") as mock_settings:
            mock_settings.data_dir = tmp_path / "data"

            with patch.object(encoder, "_create_new_realtime_timelapse", new_callable=AsyncMock) as mock_rt:
                with patch.object(encoder, "_create_new_timelapse", new_callable=AsyncMock) as mock_regular:
                    with patch.object(encoder, "_update_recap_metadata", new_callable=AsyncMock):
                        with patch("fcntl.flock"):
                            await encoder._do_encode_and_append(
                                chat_id=123,
                                frames=test_frames,
                                timestamp="2026-03-12T10:00:00",
                                audio_chunks=None,
                                fps=10,
                            )

            mock_regular.assert_called_once()
            mock_rt.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for recap_command with realtime_recaps flag
# ---------------------------------------------------------------------------


class TestRecapCommandRealtimeRecaps:
    """Tests for recap_command using the realtime_recaps feature flag."""

    @pytest.mark.asyncio
    async def test_recap_uses_rt_mp4_when_flag_on_and_file_exists(self, mock_adapter, tmp_path):
        """When realtime_recaps flag is on and _rt.mp4 exists, send_video uses _rt.mp4."""
        ctx = make_ctx(mock_adapter, args=["20260312"])

        # Create the _rt.mp4 file
        rt_video_path = tmp_path / "data" / "recaps" / "123" / "20260312_rt.mp4"
        rt_video_path.parent.mkdir(parents=True, exist_ok=True)
        rt_video_path.write_bytes(b"fake realtime video data")

        mock_record = Mock()
        mock_record.file_id = None

        mock_adapter.send_video = AsyncMock(return_value=None)

        mock_leader_config = Mock()
        mock_leader_config.feature_flags = {"realtime_recaps": True}

        with patch("src.handlers.commands.state_manager") as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=mock_record)
            mock_state_manager.get_or_create_chat_config = Mock(return_value=mock_leader_config)

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.data_dir = tmp_path / "data"

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
        """When realtime_recaps flag is off, the regular video path should be used."""
        ctx = make_ctx(mock_adapter, args=["20260312"])

        # Create both the regular and the _rt.mp4 files
        regular_video_path = tmp_path / "data" / "recaps" / "123" / "20260312.mp4"
        rt_video_path = tmp_path / "data" / "recaps" / "123" / "20260312_rt.mp4"
        regular_video_path.parent.mkdir(parents=True, exist_ok=True)
        regular_video_path.write_bytes(b"fake regular video data")
        rt_video_path.write_bytes(b"fake realtime video data")

        mock_record = Mock()
        mock_record.file_id = None

        mock_adapter.send_video = AsyncMock(return_value=None)

        # feature_flags WITHOUT "realtime_recaps"
        mock_leader_config = Mock()
        mock_leader_config.feature_flags = {}

        with patch("src.handlers.commands.state_manager") as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=mock_record)
            mock_state_manager.get_or_create_chat_config = Mock(return_value=mock_leader_config)
            mock_state_manager.update_recap_file_id = AsyncMock()

            with patch("src.handlers.commands.settings") as mock_settings:
                mock_settings.data_dir = tmp_path / "data"

                await recap_command(ctx)

        # send_video should still have been called (for the regular file)
        mock_adapter.send_video.assert_called_once()
        # The video arg should again be a file-like object from the regular path
        call_kwargs = mock_adapter.send_video.call_args
        video_arg = call_kwargs.kwargs.get("video") or call_kwargs[1].get("video")
        assert hasattr(video_arg, "read"), "Expected a file-like object for the regular .mp4"
