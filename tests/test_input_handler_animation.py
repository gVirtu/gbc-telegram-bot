
import pytest
from unittest.mock import Mock, AsyncMock, patch, ANY
import numpy as np
from src.handlers.input_handler import InputHandler
from src.models.game_state import ChatGameState, GameSession, GameButton
from telegram import InputMediaAnimation

class TestInputHandlerAnimation:
    """Tests for InputHandler animation logic (GIF generation)."""

    @pytest.mark.asyncio
    async def test_animate_frames_sends_gif(self):
        """Test that _animate_frames accumulates frames and sends a GIF."""
        mock_bot = Mock()
        mock_bot.edit_message_media = AsyncMock()
        
        handler = InputHandler(mock_bot)
        chat_id = 123
        message_id = 456
        caption = "Test Caption"
        
        # Mock GameController
        mock_controller = Mock()
        mock_controller.get_frame.return_value = np.zeros((144, 160, 3), dtype=np.uint8)
        mock_controller.tick = Mock()
        mock_controller.update_frame_hash = Mock()
        
        # Mock settings and time
        with patch('src.handlers.input_handler.settings') as mock_settings, \
             patch('asyncio.get_event_loop') as mock_loop, \
             patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep, \
             patch('src.handlers.input_handler.save_frames_as_gif') as mock_save_gif:
            
            # Configure settings
            mock_settings.animation_duration = 0.5  # Run for 0.5 seconds
            
            # Mock time to advance
            # We need the loop condition (time - start < duration) to be true a few times then false
            # start_time is set at beginning.
            # We side_effect time() to simulate passage of time
            mock_loop.return_value.time.side_effect = [0, 0.1, 0.2, 0.3, 0.4, 0.6] 
            
            # mock_save_gif should return a BytesIO-like object so we can set .name
            from io import BytesIO
            mock_buffer = BytesIO(b"GIF_DATA")
            mock_save_gif.return_value = mock_buffer
            
            await handler._animate_frames(chat_id, message_id, mock_controller, caption)
            
            # Verify .name was set (even though we pass it explicitly now, checking buffer name is still valid)
            assert mock_buffer.name == "animation.gif"
            
            # Verify controller tick called multiple times
            assert mock_controller.tick.call_count >= 1
            assert mock_controller.get_frame.call_count >= 1
            
            # Verify save_frames_as_gif called
            mock_save_gif.assert_called_once()
            args, kwargs = mock_save_gif.call_args
            assert "duration" in kwargs
            assert kwargs["last_frame_duration"] == 2000
            
            # Verify edit_message_media called with InputMediaAnimation
            mock_bot.edit_message_media.assert_called_once()
            call_args = mock_bot.edit_message_media.call_args
            assert call_args.kwargs["chat_id"] == chat_id
            assert call_args.kwargs["message_id"] == message_id
            
            media_obj = call_args.kwargs["media"]
            assert isinstance(media_obj, InputMediaAnimation)
            # The media attribute is converted to InputFile, so we just check it exists
            assert media_obj.media is not None
            assert media_obj.caption == caption
            # filename is not exposed as an attribute on InputMediaAnimation instance in some versions
            # assert media_obj.filename == "animation.gif"

    @pytest.mark.asyncio
    async def test_animate_frames_fallback_on_error(self):
        """Test fallback to photo if GIF generation fails."""
        mock_bot = Mock()
        mock_bot.edit_message_media = AsyncMock()
        
        handler = InputHandler(mock_bot)
        
        mock_controller = Mock()
        mock_controller.get_frame.return_value = np.zeros((144, 160, 3), dtype=np.uint8)
        mock_controller.get_frame_as_png.return_value = b"PNG_DATA"
        
        with patch('src.handlers.input_handler.settings') as mock_settings, \
             patch('asyncio.get_event_loop') as mock_loop, \
             patch('asyncio.sleep', new_callable=AsyncMock), \
             patch('src.handlers.input_handler.save_frames_as_gif', side_effect=Exception("GIF Error")):
            
            mock_settings.animation_duration = 0.2
            mock_loop.return_value.time.side_effect = [0, 0.1, 0.3]
            
            await handler._animate_frames(123, 456, mock_controller, "caption")
            
            # Should have called edit_message_media with PNG fallback (InputMediaPhoto is default inside the method if not animation)
            # The method _edit_message_media defaults to photo if media_type is not "animation" 
            # OR if we call it with default args.
            # In the exception handler: await self._edit_message_media(..., png_buffer, caption)
            
            assert mock_bot.edit_message_media.call_count == 1
            call_args = mock_bot.edit_message_media.call_args
            media_obj = call_args.kwargs["media"]
            # Should be Photo here because we called with png_buffer and default type
            # Note: The test setup mocks InputHandler._edit_message_media? No, we are testing logic inside it.
            # Wait, InputHandler._edit_message_media logic:
            # if media_type == "animation": ... else: ...
            
            # Verify it's NOT animation
            from telegram import InputMediaPhoto
            assert isinstance(media_obj, InputMediaPhoto)
            assert media_obj.media is not None
            assert media_obj.caption == "caption"
