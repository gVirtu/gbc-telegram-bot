"""Tests for /recap and /gif commands."""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from telegram import Update, Message, Chat, Video, User
from telegram.ext import ContextTypes

from src.handlers.commands import recap_command, gif_command, _send_no_gameplay_message


@pytest.fixture
def mock_update():
    """Create a mock Telegram update."""
    update = Mock(spec=Update)
    update.effective_chat = Mock(spec=Chat)
    update.effective_chat.id = 123
    update.message = Mock(spec=Message)
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Create a mock Telegram context."""
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot = Mock()
    context.bot.send_video = AsyncMock()
    context.bot.send_animation = AsyncMock()
    context.args = []
    return context


class TestGifCommand:
    """Tests for /gif command (formerly /recap)."""

    @pytest.mark.asyncio
    async def test_gif_no_animation(self, mock_update, mock_context):
        """Test /gif when no animation exists."""
        with patch('src.handlers.commands.get_input_handler') as mock_get_handler:
            mock_handler = Mock()
            mock_handler._get_session.return_value = None
            mock_get_handler.return_value = mock_handler

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.return_value = "No animation found"

                await gif_command(mock_update, mock_context)

                mock_update.message.reply_text.assert_called_once_with("No animation found")

    @pytest.mark.asyncio
    async def test_gif_sends_cached_animation(self, mock_update, mock_context):
        """Test /gif sends cached animation successfully."""
        with patch('src.handlers.commands.get_input_handler') as mock_get_handler:
            mock_session = Mock()
            mock_session.state.last_animation_file_id = "cached_file_id_123"

            mock_handler = Mock()
            mock_handler._get_session.return_value = mock_session
            mock_get_handler.return_value = mock_handler

            await gif_command(mock_update, mock_context)

            mock_context.bot.send_animation.assert_called_once_with(
                chat_id=123,
                animation="cached_file_id_123",
                caption="",
            )

    @pytest.mark.asyncio
    async def test_gif_handles_expired_file_id(self, mock_update, mock_context):
        """Test /gif handles expired file_id gracefully."""
        with patch('src.handlers.commands.get_input_handler') as mock_get_handler:
            mock_session = Mock()
            mock_session.state.last_animation_file_id = "expired_file_id"

            mock_handler = Mock()
            mock_handler._get_session.return_value = mock_session
            mock_get_handler.return_value = mock_handler

            # Simulate Telegram error
            mock_context.bot.send_animation.side_effect = Exception("File expired")

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.return_value = "Animation expired"

                await gif_command(mock_update, mock_context)

                mock_update.message.reply_text.assert_called_once_with("Animation expired")


class TestRecapCommand:
    """Tests for /recap command with date support."""

    @pytest.mark.asyncio
    async def test_recap_no_args_defaults_to_today(self, mock_update, mock_context):
        """Test /recap without args uses today's date."""
        mock_context.args = []

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=None)
            mock_state_manager.get_nearest_recap_date = AsyncMock(return_value=None)

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.return_value = "No gameplay for {date}"

                await recap_command(mock_update, mock_context)

                # Should query today's date
                today = datetime.now().strftime("%Y%m%d")
                mock_state_manager.get_recap_file.assert_called_once_with(123, today)

    @pytest.mark.asyncio
    async def test_recap_parses_date_argument(self, mock_update, mock_context):
        """Test /recap YYYYMMDD parses date correctly."""
        mock_context.args = ["20260215"]

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=None)
            mock_state_manager.get_nearest_recap_date = AsyncMock(return_value=None)

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.return_value = "No gameplay"

                await recap_command(mock_update, mock_context)

                mock_state_manager.get_recap_file.assert_called_once_with(123, "20260215")

    @pytest.mark.asyncio
    async def test_recap_invalid_date_format(self, mock_update, mock_context):
        """Test /recap rejects invalid date format."""
        mock_context.args = ["2026-02-15"]  # Wrong format (should be YYYYMMDD)

        with patch('src.handlers.commands.translation_manager') as mock_trans:
            mock_trans.get.return_value = "Invalid date format"

            await recap_command(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once_with("Invalid date format")

    @pytest.mark.asyncio
    async def test_recap_invalid_date_too_short(self, mock_update, mock_context):
        """Test /recap rejects date that's too short."""
        mock_context.args = ["202602"]  # Only 6 digits

        with patch('src.handlers.commands.translation_manager') as mock_trans:
            mock_trans.get.return_value = "Invalid date format"

            await recap_command(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_recap_invalid_date_not_numeric(self, mock_update, mock_context):
        """Test /recap rejects non-numeric date."""
        mock_context.args = ["2026021a"]  # Contains letter

        with patch('src.handlers.commands.translation_manager') as mock_trans:
            mock_trans.get.return_value = "Invalid date format"

            await recap_command(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_recap_invalid_date_value(self, mock_update, mock_context):
        """Test /recap rejects invalid date value."""
        mock_context.args = ["20260231"]  # Feb 31 doesn't exist

        with patch('src.handlers.commands.translation_manager') as mock_trans:
            mock_trans.get.return_value = "Invalid date format"

            await recap_command(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_recap_sends_cached_file_id(self, mock_update, mock_context, tmp_path):
        """Test /recap uses cached file_id when available."""
        mock_context.args = ["20260215"]

        # Create fake video file
        video_path = tmp_path / "data" / "recaps" / "123" / "20260215.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        mock_record = Mock()
        mock_record.file_id = "cached_file_id_xyz"

        # Override the bot.send_video to be AsyncMock
        mock_context.bot.send_video = AsyncMock()

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=mock_record)

            # Patch at the source to catch local imports too
            with patch('src.config.settings') as mock_settings:
                mock_settings.data_dir = tmp_path / "data"

                await recap_command(mock_update, mock_context)

                # Should send with cached file_id
                mock_context.bot.send_video.assert_called_once()
                call_kwargs = mock_context.bot.send_video.call_args[1]
                assert call_kwargs['video'] == "cached_file_id_xyz"

    @pytest.mark.asyncio
    async def test_recap_uploads_when_no_file_id(self, mock_update, mock_context, tmp_path):
        """Test /recap uploads from disk when file_id is None."""
        mock_context.args = ["20260215"]

        # Create fake video file
        video_path = tmp_path / "data" / "recaps" / "123" / "20260215.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video data")

        mock_record = Mock()
        mock_record.file_id = None  # No cached file_id

        mock_message = Mock(spec=Message)
        mock_video = Mock(spec=Video)
        mock_video.file_id = "new_file_id_123"
        mock_message.video = mock_video

        # Override the bot.send_video to be AsyncMock that returns the message
        mock_context.bot.send_video = AsyncMock(return_value=mock_message)

        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_recap_file = AsyncMock(return_value=mock_record)
            mock_state_manager.update_recap_file_id = AsyncMock()

            # Patch at the source to catch local imports too
            with patch('src.config.settings') as mock_settings:
                mock_settings.data_dir = tmp_path / "data"

                await recap_command(mock_update, mock_context)

                # Should upload file
                assert mock_context.bot.send_video.call_count == 1

                # Should update file_id in database
                mock_state_manager.update_recap_file_id.assert_called_once_with(
                    123, "20260215", "new_file_id_123"
                )

    @pytest.mark.asyncio
    async def test_recap_no_gameplay_message(self, mock_update, mock_context):
        """Test /recap shows helpful message when no gameplay exists."""
        mock_context.args = ["20260215"]

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

                await recap_command(mock_update, mock_context)

                # Should suggest nearest dates
                call_text = mock_update.message.reply_text.call_args[0][0]
                assert "20260214" in call_text
                assert "20260216" in call_text

    @pytest.mark.asyncio
    async def test_recap_handles_missing_video_file(self, mock_update, mock_context, tmp_path):
        """Test /recap handles case where DB record exists but file is deleted."""
        mock_context.args = ["20260215"]

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

                    await recap_command(mock_update, mock_context)

                    # Should show "no gameplay" message
                    mock_update.message.reply_text.assert_called_once()


class TestSendNoGameplayMessage:
    """Tests for the _send_no_gameplay_message helper."""

    @pytest.mark.asyncio
    async def test_no_nearby_dates(self, mock_update, mock_context):
        """Test message when no nearby dates exist."""
        with patch('src.handlers.commands.state_manager') as mock_state_manager:
            mock_state_manager.get_nearest_recap_date = AsyncMock(return_value=None)

            with patch('src.handlers.commands.translation_manager') as mock_trans:
                mock_trans.get.return_value = "No gameplay for 20260215"

                await _send_no_gameplay_message(mock_update, mock_context, 123, "20260215")

                # Should only show base message (no suggestions)
                call_text = mock_update.message.reply_text.call_args[0][0]
                assert "20260215" in call_text

    @pytest.mark.asyncio
    async def test_only_before_date(self, mock_update, mock_context):
        """Test message when only a before date exists."""
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

                await _send_no_gameplay_message(mock_update, mock_context, 123, "20260215")

                call_text = mock_update.message.reply_text.call_args[0][0]
                assert "20260214" in call_text

    @pytest.mark.asyncio
    async def test_only_after_date(self, mock_update, mock_context):
        """Test message when only an after date exists."""
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

                await _send_no_gameplay_message(mock_update, mock_context, 123, "20260215")

                call_text = mock_update.message.reply_text.call_args[0][0]
                assert "20260216" in call_text

    @pytest.mark.asyncio
    async def test_both_dates(self, mock_update, mock_context):
        """Test message with both before and after dates."""
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

                await _send_no_gameplay_message(mock_update, mock_context, 123, "20260215")

                call_text = mock_update.message.reply_text.call_args[0][0]
                assert "20260214" in call_text
                assert "20260216" in call_text
