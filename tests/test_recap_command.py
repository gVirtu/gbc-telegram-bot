"""Tests for /recap and /gif commands."""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from src.handlers.commands import recap_command, gif_command, _send_no_gameplay_message


def make_ctx(mock_adapter, args=None, chat_id=123):
    from src.adapters.base import CommandContext
    return CommandContext(chat_id=chat_id, user_id=456, user_name="TestUser",
                         args=args or [], adapter=mock_adapter, raw=None)


class TestGifCommand:
    """Tests for /gif command (formerly /recap)."""

    @pytest.mark.asyncio
    async def test_gif_no_animation(self, mock_adapter):
        """Test /gif when no animation exists."""
        ctx = make_ctx(mock_adapter)

        with patch('src.handlers.commands.get_input_handler') as mock_get_handler:
            mock_handler = Mock()
            mock_handler._get_session.return_value = None
            mock_get_handler.return_value = mock_handler

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.return_value = "No animation found"

                await gif_command(ctx)

                mock_adapter.send_text.assert_called_once_with(123, "No animation found")

    @pytest.mark.asyncio
    async def test_gif_sends_cached_animation(self, mock_adapter):
        """Test /gif sends cached animation successfully."""
        ctx = make_ctx(mock_adapter)

        with patch('src.handlers.commands.get_input_handler') as mock_get_handler:
            mock_session = Mock()
            mock_session.state.last_animation_file_id = "cached_file_id_123"

            mock_handler = Mock()
            mock_handler._get_session.return_value = mock_session
            mock_get_handler.return_value = mock_handler

            await gif_command(ctx)

            mock_adapter.send_animation.assert_called_once_with(
                chat_id=123,
                animation="cached_file_id_123",
                caption="",
            )

    @pytest.mark.asyncio
    async def test_gif_falls_back_to_cache_when_no_file_id(self, mock_adapter):
        """Test /gif loads from local cache when file_id is None."""
        from io import BytesIO
        ctx = make_ctx(mock_adapter)
        mock_adapter.preferred_animation_format = "mp4"
        cached_buf = BytesIO(b"cached_video_data")

        with patch('src.handlers.commands.get_input_handler') as mock_get_handler:
            mock_session = Mock()
            mock_session.state.last_animation_file_id = None
            mock_handler = Mock()
            mock_handler._get_session.return_value = mock_session
            mock_get_handler.return_value = mock_handler

            with patch('src.handlers.commands.load_last_animation', return_value=cached_buf) as mock_load:
                await gif_command(ctx)

                mock_load.assert_called_once_with(123, "mp4")
                mock_adapter.send_animation.assert_called_once_with(
                    chat_id=123,
                    animation=cached_buf,
                    caption="",
                )

    @pytest.mark.asyncio
    async def test_gif_falls_back_to_cache_on_expired_file_id(self, mock_adapter):
        """Test /gif falls back to local cache when file_id send raises."""
        from io import BytesIO
        ctx = make_ctx(mock_adapter)
        mock_adapter.preferred_animation_format = "mp4"
        cached_buf = BytesIO(b"cached_video_data")

        with patch('src.handlers.commands.get_input_handler') as mock_get_handler:
            mock_session = Mock()
            mock_session.state.last_animation_file_id = "expired_file_id"
            mock_handler = Mock()
            mock_handler._get_session.return_value = mock_session
            mock_get_handler.return_value = mock_handler

            # First call (file_id) raises, second call (buffer) succeeds
            mock_adapter.send_animation.side_effect = [Exception("File expired"), None]

            with patch('src.handlers.commands.load_last_animation', return_value=cached_buf):
                await gif_command(ctx)

                assert mock_adapter.send_animation.call_count == 2
                second_call = mock_adapter.send_animation.call_args_list[1]
                assert second_call.kwargs["animation"] is cached_buf

    @pytest.mark.asyncio
    async def test_gif_error_when_no_file_id_and_no_cache(self, mock_adapter):
        """Test /gif sends error message when file_id is None and cache is empty."""
        ctx = make_ctx(mock_adapter)
        mock_adapter.preferred_animation_format = "mp4"

        with patch('src.handlers.commands.get_input_handler') as mock_get_handler:
            mock_session = Mock()
            mock_session.state.last_animation_file_id = None
            mock_handler = Mock()
            mock_handler._get_session.return_value = mock_session
            mock_get_handler.return_value = mock_handler

            with patch('src.handlers.commands.load_last_animation', return_value=None):
                with patch('src.handlers.commands.translation_manager') as mock_trans:
                    mock_trans.get.return_value = "No animation found"

                    await gif_command(ctx)

                    mock_adapter.send_animation.assert_not_called()
                    mock_adapter.send_text.assert_called_once_with(123, "No animation found")

    @pytest.mark.asyncio
    async def test_gif_error_when_expired_file_id_and_no_cache(self, mock_adapter):
        """Test /gif sends error message when file_id expired and cache is empty."""
        ctx = make_ctx(mock_adapter)
        mock_adapter.preferred_animation_format = "mp4"

        with patch('src.handlers.commands.get_input_handler') as mock_get_handler:
            mock_session = Mock()
            mock_session.state.last_animation_file_id = "expired_file_id"
            mock_handler = Mock()
            mock_handler._get_session.return_value = mock_session
            mock_get_handler.return_value = mock_handler

            mock_adapter.send_animation.side_effect = Exception("File expired")

            with patch('src.handlers.commands.load_last_animation', return_value=None):
                with patch('src.handlers.commands.translation_manager') as mock_trans:
                    mock_trans.get.return_value = "No animation found"

                    await gif_command(ctx)

                    mock_adapter.send_text.assert_called_once_with(123, "No animation found")

    @pytest.mark.asyncio
    async def test_gif_mirror_uses_leader_cache(self, mock_adapter):
        """Test /gif for a mirror chat resolves to leader's cache."""
        from io import BytesIO
        ctx = make_ctx(mock_adapter, chat_id=200)
        mock_adapter.preferred_animation_format = "mp4"
        cached_buf = BytesIO(b"leader_video_data")

        with patch('src.handlers.commands.get_leader_chat_id', return_value=100) as mock_leader:
            with patch('src.handlers.commands.get_input_handler') as mock_get_handler:
                mock_session = Mock()
                mock_session.state.last_animation_file_id = None
                mock_handler = Mock()
                mock_handler._get_session.return_value = mock_session
                mock_get_handler.return_value = mock_handler

                with patch('src.handlers.commands.load_last_animation', return_value=cached_buf) as mock_load:
                    await gif_command(ctx)

                    mock_leader.assert_called_once_with(200)
                    mock_load.assert_called_once_with(100, "mp4")


class TestRecapCommand:
    """Tests for /recap command with date support."""

    @pytest.mark.asyncio
    async def test_recap_no_args_defaults_to_today(self, mock_adapter):
        """Test /recap without args uses today's date."""
        ctx = make_ctx(mock_adapter, args=[])

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=None)
            mock_state_manager.get_nearest_recap_date = AsyncMock(return_value=None)

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.return_value = "No gameplay for {date}"

                await recap_command(ctx)

                # Should query today's date
                today = datetime.now().strftime("%Y%m%d")
                mock_state_manager.get_recap_file.assert_called_once_with(123, today)

    @pytest.mark.asyncio
    async def test_recap_parses_date_argument(self, mock_adapter):
        """Test /recap YYYYMMDD parses date correctly."""
        ctx = make_ctx(mock_adapter, args=["20260215"])

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=None)
            mock_state_manager.get_nearest_recap_date = AsyncMock(return_value=None)

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.return_value = "No gameplay"

                await recap_command(ctx)

                mock_state_manager.get_recap_file.assert_called_once_with(123, "20260215")

    @pytest.mark.asyncio
    async def test_recap_invalid_date_format(self, mock_adapter):
        """Test /recap rejects invalid date format."""
        ctx = make_ctx(mock_adapter, args=["2026-02-15"])  # Wrong format (should be YYYYMMDD)

        with patch('src.handlers.commands.translation_manager') as mock_trans:
            mock_trans.get.return_value = "Invalid date format"

            await recap_command(ctx)

            mock_adapter.send_text.assert_called_once_with(123, "Invalid date format")

    @pytest.mark.asyncio
    async def test_recap_invalid_date_too_short(self, mock_adapter):
        """Test /recap rejects date that's too short."""
        ctx = make_ctx(mock_adapter, args=["202602"])  # Only 6 digits

        with patch('src.handlers.commands.translation_manager') as mock_trans:
            mock_trans.get.return_value = "Invalid date format"

            await recap_command(ctx)

            mock_adapter.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_recap_invalid_date_not_numeric(self, mock_adapter):
        """Test /recap rejects non-numeric date."""
        ctx = make_ctx(mock_adapter, args=["2026021a"])  # Contains letter

        with patch('src.handlers.commands.translation_manager') as mock_trans:
            mock_trans.get.return_value = "Invalid date format"

            await recap_command(ctx)

            mock_adapter.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_recap_invalid_date_value(self, mock_adapter):
        """Test /recap rejects invalid date value."""
        ctx = make_ctx(mock_adapter, args=["20260231"])  # Feb 31 doesn't exist

        with patch('src.handlers.commands.translation_manager') as mock_trans:
            mock_trans.get.return_value = "Invalid date format"

            await recap_command(ctx)

            mock_adapter.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_recap_sends_cached_file_id(self, mock_adapter, tmp_path):
        """Test /recap delegates to send_recap_to_chat when video file exists."""
        ctx = make_ctx(mock_adapter, args=["20260215"])

        # Create fake video file so the path.exists() check passes
        video_path = tmp_path / "data" / "recaps" / "123" / "recap_20260215.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        mock_record = Mock()
        mock_record.file_id = "cached_file_id_xyz"

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=mock_record)

            with patch('src.handlers.commands.settings') as mock_settings:
                mock_settings.data_dir = tmp_path / "data"

                with patch('src.handlers.commands.send_recap_to_chat', new_callable=AsyncMock) as mock_send:
                    mock_send.return_value = True
                    await recap_command(ctx)
                    mock_send.assert_called_once_with(123, 123, "20260215", mock_adapter)

    @pytest.mark.asyncio
    async def test_recap_uploads_when_no_file_id(self, mock_adapter, tmp_path):
        """Test /recap shows error when send_recap_to_chat fails."""
        ctx = make_ctx(mock_adapter, args=["20260215"])

        # Create fake video file so the path.exists() check passes
        video_path = tmp_path / "data" / "recaps" / "123" / "recap_20260215.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video data")

        mock_record = Mock()
        mock_record.file_id = None

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=mock_record)

            with patch('src.handlers.commands.settings') as mock_settings:
                mock_settings.data_dir = tmp_path / "data"

                with patch('src.handlers.commands.send_recap_to_chat', new_callable=AsyncMock) as mock_send:
                    mock_send.return_value = False
                    with patch('src.handlers.commands.translation_manager') as mock_trans:
                        mock_trans.get.return_value = "Error sending recap"
                        await recap_command(ctx)
                        mock_adapter.send_text.assert_called_once_with(123, "Error sending recap")

    @pytest.mark.asyncio
    async def test_recap_no_gameplay_message(self, mock_adapter):
        """Test /recap shows helpful message when no gameplay exists."""
        ctx = make_ctx(mock_adapter, args=["20260215"])

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=None)
            mock_state_manager.get_nearest_recap_date = AsyncMock(side_effect=[
                "20260214",  # before
                "20260216",  # after
            ])

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.side_effect = lambda key, chat_id, **kwargs: {
                    "commands.recap.no_gameplay": f"No gameplay for {kwargs.get('date', '')}",
                    "commands.recap.try_dates": f"Try: {kwargs.get('dates', '')}",
                }[key]

                await recap_command(ctx)

                # Should suggest nearest dates
                call_text = mock_adapter.send_text.call_args[0][1]
                assert "20260214" in call_text
                assert "20260216" in call_text

    @pytest.mark.asyncio
    async def test_recap_handles_missing_video_file(self, mock_adapter, tmp_path):
        """Test /recap handles case where DB record exists but file is deleted."""
        ctx = make_ctx(mock_adapter, args=["20260215"])

        mock_record = Mock()
        mock_record.file_id = None

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=mock_record)
            mock_state_manager.get_nearest_recap_date = AsyncMock(return_value=None)

            with patch('src.handlers.commands.settings') as mock_settings:
                mock_settings.data_dir = tmp_path / "data"
                # Don't create the file - simulate deletion

                with patch('src.handlers.commands.translation_manager') as mock_trans:
                    mock_trans.get.return_value = "No gameplay"

                    await recap_command(ctx)

                    # Should show "no gameplay" message
                    mock_adapter.send_text.assert_called_once()


class TestSendNoGameplayMessage:
    """Tests for the _send_no_gameplay_message helper."""

    @pytest.mark.asyncio
    async def test_no_nearby_dates(self, mock_adapter):
        """Test message when no nearby dates exist."""
        ctx = make_ctx(mock_adapter)

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_nearest_recap_date = AsyncMock(return_value=None)

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.return_value = "No gameplay for 20260215"

                await _send_no_gameplay_message(ctx, "20260215")

                # Should only show base message (no suggestions)
                call_text = mock_adapter.send_text.call_args[0][1]
                assert "20260215" in call_text

    @pytest.mark.asyncio
    async def test_only_before_date(self, mock_adapter):
        """Test message when only a before date exists."""
        ctx = make_ctx(mock_adapter)

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_nearest_recap_date = AsyncMock(side_effect=[
                "20260214",  # before
                None,  # after
            ])

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.side_effect = lambda key, chat_id, **kwargs: {
                    "commands.recap.no_gameplay": "No gameplay",
                    "commands.recap.try_dates": f"Try: {kwargs.get('dates', '')}",
                }[key]

                await _send_no_gameplay_message(ctx, "20260215")

                call_text = mock_adapter.send_text.call_args[0][1]
                assert "20260214" in call_text

    @pytest.mark.asyncio
    async def test_only_after_date(self, mock_adapter):
        """Test message when only an after date exists."""
        ctx = make_ctx(mock_adapter)

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_nearest_recap_date = AsyncMock(side_effect=[
                None,  # before
                "20260216",  # after
            ])

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.side_effect = lambda key, chat_id, **kwargs: {
                    "commands.recap.no_gameplay": "No gameplay",
                    "commands.recap.try_dates": f"Try: {kwargs.get('dates', '')}",
                }[key]

                await _send_no_gameplay_message(ctx, "20260215")

                call_text = mock_adapter.send_text.call_args[0][1]
                assert "20260216" in call_text

    @pytest.mark.asyncio
    async def test_both_dates(self, mock_adapter):
        """Test message with both before and after dates."""
        ctx = make_ctx(mock_adapter)

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_nearest_recap_date = AsyncMock(side_effect=[
                "20260214",  # before
                "20260216",  # after
            ])

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.side_effect = lambda key, chat_id, **kwargs: {
                    "commands.recap.no_gameplay": "No gameplay",
                    "commands.recap.try_dates": f"Try: {kwargs.get('dates', '')}",
                }[key]

                await _send_no_gameplay_message(ctx, "20260215")

                call_text = mock_adapter.send_text.call_args[0][1]
                assert "20260214" in call_text
                assert "20260216" in call_text
