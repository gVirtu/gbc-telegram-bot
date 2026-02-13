"""Input handler for managing game interactions.

This module handles button presses, input processing, and game flow
including the first-vote-wins logic and animation phases.
"""

import asyncio
import logging
from typing import Optional

from telegram import Bot, InputMediaPhoto, InputMediaAnimation, InlineKeyboardMarkup
from telegram.error import TelegramError

from src.config import settings
from src.game import GameController, game_controller_manager
from src.keyboard import (
    create_input_keyboard,
    create_game_message_text,
    get_button_from_callback,
    is_valid_button_callback,
)
from src.models.game_state import ChatGameState, ChatConfig, GameButton, GameSession
from src.models.input_queue import InputQueue, QueueItem
from src.utils.frame_utils import should_update_frame, save_frames_as_mp4
from src.utils.rate_limiter import RateLimitException
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)


class InputHandlerError(Exception):
    """Base exception for input handler errors."""
    pass


class InputHandler:
    """Handles game input processing with queue-based system.
    
    This class manages the game flow:
    1. Receiving button presses and queueing them
    2. Processing queue items sequentially with estimated timing
    3. Updating Telegram messages with new frames
    4. Managing game state transitions (IDLE/PROCESSING)
    """
    
    def __init__(self, bot: Bot):
        """Initialize the input handler.
        
        Args:
            bot: The Telegram Bot instance
        """
        self.bot = bot
        self._sessions: dict[int, GameSession] = {}
        self._processing: set[int] = set()  # Chats currently processing
        self._input_queues: dict[int, InputQueue] = {}  # Chat ID -> InputQueue
    
    def _get_session(self, chat_id: int) -> Optional[GameSession]:
        """Get or create a game session for a chat.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            GameSession if active, None otherwise
        """
        if chat_id not in self._sessions:
            # Try to load existing state
            state = state_manager.load_game_state(chat_id)
            if state:
                self._sessions[chat_id] = GameSession(chat_id=chat_id, state=state)
        
        return self._sessions.get(chat_id)
    
    def _create_session(self, chat_id: int, message_id: int) -> GameSession:
        """Create a new game session.
        
        Args:
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            
        Returns:
            New GameSession
        """
        state = ChatGameState(chat_id=chat_id, message_id=message_id)
        session = GameSession(chat_id=chat_id, state=state)
        self._sessions[chat_id] = session
        
        # Save to disk
        state_manager.save_game_state(state)
        
        return session
    
    def _get_or_create_queue(self, chat_id: int) -> InputQueue:
        """Get or create input queue for a chat."""
        if chat_id not in self._input_queues:
            session = self._get_session(chat_id)
            if session and session.state.input_queue:
                self._input_queues[chat_id] = session.state.input_queue
            else:
                self._input_queues[chat_id] = InputQueue(max_size=settings.max_queue_size)
        return self._input_queues[chat_id]
    
    def _calculate_processing_time(self, buttons: list[GameButton]) -> float:
        """Calculate estimated time to process a button sequence."""
        base_time = settings.animation_duration
        if len(buttons) > 1:
            delay_time = settings.sequence_delay_seconds * (len(buttons) - 1)
            base_time += delay_time
        return base_time
    
    def _is_processing(self, chat_id: int) -> bool:
        """Check if a chat is currently processing input."""
        return chat_id in self._processing
    
    async def handle_button_press(self, callback_query) -> None:
        """Handle a button press with queue-based processing."""
        chat_id = callback_query.message.chat.id
        message_id = callback_query.message.message_id
        callback_data = callback_query.data

        if not is_valid_button_callback(callback_data):
            try:
                await callback_query.answer("Invalid button")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        button = get_button_from_callback(callback_data)
        session = self._get_session(chat_id)
        if not session or button is None:
            try:
                await callback_query.answer("Nenhum jogo ativo! Use /start_game primeiro.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        # Validate message is current
        if session.state.message_id != message_id:
            try:
                await callback_query.answer("Esta mensagem está desatualizada. Use /resume para continuar.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        user_id = callback_query.from_user.id
        user_name = (
            callback_query.from_user.first_name or
            (f"@{callback_query.from_user.username}" if callback_query.from_user.username else "User")
        )

        # Handle RUN button specially
        if button == GameButton.RUN:
            await self._handle_run_button_press(callback_query, session, chat_id, message_id)
            return

        # Get or create queue
        queue = self._get_or_create_queue(chat_id)
        
        # Add input to queue
        success, message = queue.add_input(user_id, user_name, button)
        
        if not success:
            try:
                await callback_query.answer(message)
            except Exception as e:
                logger.error(f"Error answering callback for chat {chat_id}: {e}")
            return
        
        # Save queue to session state
        session.state.input_queue = queue
        state_manager.save_game_state(session.state)
        
        # Check if we should start processing
        if not self._is_processing(chat_id):
            try:
                await callback_query.answer(f"Processando: {button.display_name}")
                asyncio.create_task(self._process_queue_loop(chat_id, message_id))
            except Exception as e:
                logger.error(f"Error starting queue processing for chat {chat_id}: {e}")
                await self._send_error_message(chat_id, "Erro ao processar inputs! Tente de novo depois.")
        else:
            try:
                await callback_query.answer(message)
            except Exception as e:
                logger.error(f"Error answering callback for chat {chat_id}: {e}")

    async def _handle_run_button_press(
        self, callback_query, session, chat_id, message_id
    ) -> None:
        """Handle RUN button press to toggle running mode."""
        # Toggle running mode
        config = state_manager.get_or_create_chat_config(chat_id)
        
        config.running_mode = not config.running_mode
        state_manager.save_chat_config(config)
        
        # Update keyboard with new emoji
        await self._edit_message_keyboard(
            chat_id, message_id, create_input_keyboard(running_mode=config.running_mode)
        )
        
        # Answer callback
        message = "Corrida ativada 🏃" if config.running_mode else "Corrida desativada 🚶"
        try:
            await callback_query.answer(message, show_alert=False)
        except Exception as e:
            logger.error(f"Error answering callback for chat {chat_id}: {e}")

    async def _process_sequence(
        self, chat_id: int, buttons: list[GameButton], message_id: int
    ) -> None:
        """Process a sequence of buttons (backward compatibility alias).
        
        Args:
            chat_id: Telegram chat ID
            buttons: List of buttons to execute
            message_id: Message ID to edit
        """
        # Create a temporary QueueItem for backward compatibility
        item = QueueItem(
            user_id=0,  # System/unknown user for direct calls
            user_name="System",
            buttons=buttons,
        )
        await self._process_queue_item(chat_id, message_id, item)

    def _record_user_input(
        self,
        session: GameSession,
        user_id: int,
        user_name: str,
        buttons: list[GameButton],
    ) -> None:
        """Record user input (single button or sequence)."""
        from datetime import datetime

        # Increment by number of buttons in sequence
        session.state.user_input_counts[str(user_id)] = (
            session.state.user_input_counts.get(str(user_id), 0) + len(buttons)
        )

        # Add to recent inputs (store as list)
        input_record = {
            "user_id": user_id,
            "user_name": user_name,
            "buttons": [b.value for b in buttons],  # Changed to list
            "timestamp": datetime.utcnow().isoformat(),
        }

        session.state.recent_inputs.append(input_record)

        # Keep only last 3
        if len(session.state.recent_inputs) > 3:
            session.state.recent_inputs = session.state.recent_inputs[-3:]

    async def _process_queue_loop(self, chat_id: int, message_id: int) -> None:
        """Process queue items until empty."""
        self._processing.add(chat_id)
        session = self._get_session(chat_id)
        
        if not session:
            self._processing.discard(chat_id)
            return
        
        try:
            while True:
                queue = self._get_or_create_queue(chat_id)
                
                if queue.is_empty():
                    break
                
                item = queue.pop()
                if item is None:
                    break
                    
                session.state.input_queue = queue
                
                try:
                    await self._process_queue_item(chat_id, message_id, item)
                except Exception as e:
                    logger.error(f"Error processing queue item for chat {chat_id}: {e}")
                
                state_manager.save_game_state(session.state)
                
                wait_time = self._calculate_processing_time(item.buttons)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
        
        finally:
            self._processing.discard(chat_id)
            if session:
                session.state.input_in_progress = False
                state_manager.save_game_state(session.state)
            
            logger.info(f"Queue processing completed for chat {chat_id}")

    async def _process_queue_item(
        self, chat_id: int, message_id: int, item: QueueItem
    ) -> None:
        """Process a single queue item.

        Args:
            chat_id: Telegram chat ID
            message_id: Message ID to edit
            item: QueueItem to process
        """
        queue = self._get_or_create_queue(chat_id)
        controller = await game_controller_manager.get_or_create_controller(chat_id)
        session = self._get_session(chat_id)
        buttons = item.buttons
        
        # Record the input for user tracking
        self._record_user_input(session, item.user_id, item.user_name, buttons)

        # Check running mode
        config = state_manager.get_or_create_chat_config(chat_id)
        running_mode = config.running_mode if config else False

        input_keyboard = create_input_keyboard(running_mode=running_mode)

        logger.info(f"Executing sequence of {len(buttons)} buttons for chat {chat_id} (running_mode={running_mode})")

        # Animation capture settings - GameBoy runs at 60fps, capture at 10fps
        frames = []
        game_fps = 60
        capture_fps = 10
        capture_interval_frames = game_fps // capture_fps  # Capture every 6th frame

        # Directional buttons that can use running mode
        directional_buttons = (GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT)

        # Capture current frame
        frames.append(controller.get_frame().copy())

        # Execute each button with delays (synchronous, no real-time waiting)
        for i, button in enumerate(buttons):
            # Execute button
            if button == GameButton.WAIT:
                logger.debug(f"WAIT button in sequence for chat {chat_id}")
                controller.tick(frames=settings.input_hold_frames)
            elif running_mode and button in directional_buttons:
                # Running mode: hold B throughout directional input
                logger.debug(f"Executing {button.value} with B in running mode for chat {chat_id}")
                controller.send_input_with_modifier(button, GameButton.B, frames=settings.input_hold_frames)
            else:
                logger.debug(f"Executing {button.value} in sequence for chat {chat_id}")
                controller.send_input(button, frames=settings.input_hold_frames)

            # Capture frame after button
            frames.append(controller.get_frame().copy())

            # Apply delay between buttons (if not last) - synchronous frame generation
            if i < len(buttons) - 1:
                delay_frames = int(settings.sequence_delay_seconds * game_fps)
                for frame_num in range(delay_frames):
                    controller.tick(1)
                    if frame_num % capture_interval_frames == 0:
                        frames.append(controller.get_frame().copy())

        # Continue animating after last button - synchronous frame generation
        animation_frames = int(settings.animation_duration * game_fps)
        for frame_num in range(animation_frames):
            controller.tick(1)
            if frame_num % capture_interval_frames == 0:
                frames.append(controller.get_frame().copy())

        from src.utils.frame_utils import generate_tbc_frames
        tbc_frames = generate_tbc_frames(
            frames[-1] if frames else controller.get_frame(),
            overlay_path=settings.tbc_overlay_path,
            duration_frames=settings.tbc_duration_frames,
            max_width_percent=0.7
        )
        frames.extend(tbc_frames)
        
        recent = session.state.recent_inputs if session else []
        caption = create_game_message_text(recent_inputs=recent, queue_length=len(queue))

        # Generate and send MP4
        if frames:
            logger.info(f"Generating MP4 with {len(frames)} frames for chat {chat_id}")
            try:
                mp4_buffer = save_frames_as_mp4(frames, fps=capture_fps)
                mp4_buffer.seek(0)

                await self._edit_message_media(
                    chat_id, message_id, mp4_buffer, caption, media_type="animation", reply_markup=input_keyboard
                )

                _, last_hash = should_update_frame(frames[-1], None)
                controller.update_frame_hash(last_hash)
            except Exception as e:
                logger.error(f"Failed to generate MP4 for chat {chat_id}: {e}")
                try:
                    png_buffer = controller.get_frame_as_png()
                    await self._edit_message_media(chat_id, message_id, png_buffer, caption, reply_markup=input_keyboard)
                except Exception as e2:
                    logger.error(f"Fallback failed for chat {chat_id}: {e2}")

        # Auto-save if enabled
        config = state_manager.get_or_create_chat_config(chat_id)
        if config.auto_save_enabled:
            try:
                slot = state_manager.find_next_auto_save_slot(chat_id)
                state_data = controller.save_state()
                state_manager.save_to_slot(
                    chat_id=chat_id,
                    slot_number=slot,
                    state_data=state_data,
                    description=f"Auto-save",
                    is_auto_save=True,
                )
                logger.debug(f"Auto-saved to slot {slot} for chat {chat_id}")
            except Exception as e:
                logger.warning(f"Failed to auto-save for chat {chat_id}: {e}")

        logger.info(f"Completed queue item processing for chat {chat_id}")
    
    async def _edit_message_keyboard(
        self,
        chat_id: int,
        message_id: int,
        keyboard,
    ) -> None:
        """Edit a message's keyboard.
        
        Args:
            chat_id: Telegram chat ID
            message_id: Message ID to edit
            keyboard: New keyboard markup
        """
        try:
            await self.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
            )
        except TelegramError as e:
            logger.warning(f"Failed to edit keyboard for chat {chat_id}: {e}")
    
    async def _edit_message_media(
        self,
        chat_id: int,
        message_id: int,
        media_buffer,
        caption: str,
        media_type: str = "photo",
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        """Edit a message's media (photo or animation).

        Args:
            chat_id: Telegram chat ID
            message_id: Message ID to edit
            media_buffer: BytesIO containing image or animation data
            caption: Message caption
            media_type: Type of media ("photo" or "animation")
        """
        try:
            if media_type == "animation":
                # Ensure buffer has a name attribute for proper file upload
                media_buffer.name = "animation.mp4"
                media = InputMediaAnimation(
                    media=media_buffer,
                    caption=caption,
                    parse_mode="Markdown",
                )
            else:
                media = InputMediaPhoto(media=media_buffer, caption=caption, parse_mode="Markdown")

            await self.bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=media,
                reply_markup=reply_markup,
            )
        except TelegramError as e:
            logger.warning(f"Failed to edit media for chat {chat_id}: {e}")
    
    async def _send_error_message(self, chat_id: int, text: str) -> None:
        """Send an error message to the chat.
        
        Args:
            chat_id: Telegram chat ID
            text: Error message text
        """
        try:
            await self.bot.send_message(chat_id, f"❌ {text}")
        except TelegramError as e:
            logger.error(f"Failed to send error message to chat {chat_id}: {e}")
    
    async def start_game(self, chat_id: int) -> int:
        """Start a new game for a chat.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            Message ID of the sent game message
        """
        # Initialize game controller
        controller = await game_controller_manager.get_or_create_controller(chat_id)
        
        # Get initial frame
        frame = controller.get_frame()
        png_buffer = controller.get_frame_as_png()
        
        # Create session
        session = self._create_session(chat_id, 0)  # Will update message_id after sending
        
        config = state_manager.get_or_create_chat_config(chat_id)
        running_mode = config.running_mode if config else False

        queue = self._get_or_create_queue(chat_id)
        
        # Send initial message

        recent = session.state.recent_inputs if session else []
        message = await self.bot.send_photo(
            chat_id=chat_id,
            photo=png_buffer,
            caption=create_game_message_text(recent_inputs=recent, queue_length=len(queue)),
            reply_markup=create_input_keyboard(running_mode=running_mode),
            parse_mode="Markdown",
        )
        
        # Update session with message ID
        session.state.message_id = message.message_id
        state_manager.save_game_state(session.state)
        
        logger.info(f"Started game for chat {chat_id}, message {message.message_id}")
        
        return message.message_id
    
    async def show_current_frame(self, chat_id: int) -> Optional[int]:
        """Show the current game frame.
        
        If a game is active, edits the existing message. Otherwise,
        sends a new message.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            Message ID if successful, None otherwise
        """
        session = self._get_session(chat_id)
        controller = game_controller_manager.get_controller(chat_id)
        
        if not controller or not controller.is_initialized():
            return None
        
        config = state_manager.get_or_create_chat_config(chat_id)
        running_mode = config.running_mode if config else False
        
        queue = self._get_or_create_queue(chat_id)
        
        # Get current frame
        frame = controller.get_frame()
        png_buffer = controller.get_frame_as_png()
        recent = session.state.recent_inputs if session else []
        caption = create_game_message_text(recent_inputs=recent, queue_length=len(queue))
        
        if session and session.state.message_id and not session.state.input_in_progress:
            # Edit existing message
            try:
                await self._edit_message_media(
                    chat_id,
                    session.state.message_id,
                    png_buffer,
                    caption,
                )
                await self._edit_message_keyboard(
                    chat_id,
                    session.state.message_id,
                    create_input_keyboard(running_mode=running_mode),
                )
                return session.state.message_id
            except TelegramError:
                # Fall through to sending new message
                pass
        
        message = await self.bot.send_photo(
            chat_id=chat_id,
            photo=png_buffer,
            caption=caption,
            reply_markup=create_input_keyboard(running_mode=running_mode) if not (session and session.state.input_in_progress) else None,
            parse_mode="Markdown",
        )
        
        # Update or create session
        if session:
            session.state.message_id = message.message_id
        else:
            self._create_session(chat_id, message.message_id)
        
        return message.message_id

    async def resume_game(self, chat_id: int) -> Optional[int]:
        """Resume the game by sending a new message with keyboard.

        Removes the keyboard from the old game message and sends a new
        message with the current frame and input keyboard. Unlike
        start_game, this does not restart the game.

        Args:
            chat_id: Telegram chat ID

        Returns:
            Message ID of the new game message, or None if failed
        """
        session = self._get_session(chat_id)
        controller = game_controller_manager.get_controller(chat_id)
        queue = self._get_or_create_queue(chat_id)

        if not controller or not controller.is_initialized():
            return None

        config = state_manager.get_or_create_chat_config(chat_id)
        running_mode = config.running_mode if config else False
        
        # Get current frame
        png_buffer = controller.get_frame_as_png()

        # Remove keyboard from old message if it exists
        if session and session.state.message_id:
            try:
                await self.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=session.state.message_id,
                    reply_markup=None,
                )
            except TelegramError:
                # Old message might be deleted or inaccessible, continue anyway
                pass

        recent = session.state.recent_inputs if session else []
        message = await self.bot.send_photo(
            chat_id=chat_id,
            photo=png_buffer,
            caption=create_game_message_text(recent_inputs=recent, queue_length=len(queue)),
            reply_markup=create_input_keyboard(running_mode=running_mode),
            parse_mode="Markdown",
        )

        # Update session with new message ID
        if session:
            session.state.message_id = message.message_id
            state_manager.save_game_state(session.state)
        else:
            self._create_session(chat_id, message.message_id)

        logger.info(f"Resumed game for chat {chat_id}, new message {message.message_id}")

        return message.message_id

    def is_input_in_progress(self, chat_id: int) -> bool:
        """Check if input is currently being processed for a chat.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            True if input is being processed
        """
        return chat_id in self._processing
    
    def cleanup_session(self, chat_id: int) -> bool:
        """Clean up a game session.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            True if session was removed
        """
        if chat_id in self._sessions:
            del self._sessions[chat_id]
            self._processing.discard(chat_id)
            self._input_queues.pop(chat_id, None)
            
            # Stop the game controller
            game_controller_manager.remove_controller(chat_id)
            
            logger.info(f"Cleaned up session for chat {chat_id}")
            return True
        
        return False


# Singleton instance
_input_handler: Optional[InputHandler] = None


def get_input_handler(bot: Bot) -> InputHandler:
    """Get or create the singleton InputHandler instance.
    
    Args:
        bot: Telegram Bot instance
        
    Returns:
        InputHandler instance
    """
    global _input_handler
    if _input_handler is None:
        _input_handler = InputHandler(bot)
    return _input_handler
