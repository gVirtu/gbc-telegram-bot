"""Input handler for managing game interactions.

This module handles button presses, input processing, and game flow
including the first-vote-wins logic and animation phases.
"""

import asyncio
import logging
from typing import Optional

from telegram import Bot, InputMediaPhoto, InputMediaAnimation
from telegram.error import TelegramError

from src.config import settings
from src.game import GameController, game_controller_manager
from src.keyboard import (
    create_input_keyboard,
    create_game_message_text,
    create_processing_keyboard,
    get_button_from_callback,
    is_valid_button_callback,
)
from src.models.game_state import ChatGameState, GameButton, GameSession
from src.utils.frame_utils import should_update_frame, save_frames_as_gif
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)


class InputHandlerError(Exception):
    """Base exception for input handler errors."""
    pass


class InputHandler:
    """Handles game input processing and state management.
    
    This class manages the game flow:
    1. Receiving button presses (first-vote-wins)
    2. Processing inputs with animation
    3. Updating Telegram messages with new frames
    4. Managing game state transitions
    
    Example:
        >>> handler = InputHandler(bot)
        >>> await handler.handle_button_press(callback_query)
    """
    
    def __init__(self, bot: Bot):
        """Initialize the input handler.
        
        Args:
            bot: The Telegram Bot instance
        """
        self.bot = bot
        self._sessions: dict[int, GameSession] = {}
        self._processing: set[int] = set()  # Chats currently processing input
    
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
    
    async def handle_button_press(self, callback_query) -> None:
        """Handle a button press from a user.

        Implements first-vote-wins logic. If input is already being
        processed, rejects the press.

        Args:
            callback_query: Telegram CallbackQuery object
        """
        chat_id = callback_query.message.chat.id
        message_id = callback_query.message.message_id
        callback_data = callback_query.data

        # Validate callback is a game button
        if not is_valid_button_callback(callback_data):
            try:
                await callback_query.answer("Invalid button")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        button = get_button_from_callback(callback_data)

        # Check if chat has an active session
        session = self._get_session(chat_id)
        if not session:
            try:
                await callback_query.answer("Nenhum jogo ativo! Use /start_game primeiro.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        # Check if input is already being processed
        if chat_id in self._processing:
            try:
                await callback_query.answer("Input já está em progresso! Por favor aguarde.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        # Check if message matches (prevent old message interactions)
        if session.state.message_id != message_id:
            try:
                await callback_query.answer("Esta mensagem está desatualizada. Use /resume para continuar.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        # Extract user info
        user_id = callback_query.from_user.id
        user_name = (
            callback_query.from_user.first_name or
            (f"@{callback_query.from_user.username}" if callback_query.from_user.username else "User")
        )

        # Lock input processing
        self._processing.add(chat_id)
        session.state.input_in_progress = True
        session.state.last_input = button
        session.record_activity()

        # Record user input
        self._record_user_input(session, user_id, user_name, button)

        try:
            # Acknowledge the button press
            await callback_query.answer(f"Processando: {button.display_name}")

            # Process the input
            await self._process_input(chat_id, button, message_id)

        except Exception as e:
            logger.error(f"Error processing input for chat {chat_id}: {e}")
            await self._send_error_message(chat_id, "Erro ao processar, por favor tente novamente.")
        finally:
            # Always unlock
            self._processing.discard(chat_id)
            session.state.input_in_progress = False
            state_manager.save_game_state(session.state)

    def _record_user_input(
        self,
        session: GameSession,
        user_id: int,
        user_name: str,
        button: GameButton,
    ) -> None:
        """Record a user input in the session state.

        Updates user_input_counts and recent_inputs (max 3, FIFO).

        Args:
            session: Game session to update
            user_id: Telegram user ID
            user_name: User's display name
            button: Button that was pressed
        """
        from datetime import datetime

        # Increment user's total count
        session.state.user_input_counts[user_id] = (
            session.state.user_input_counts.get(user_id, 0) + 1
        )

        # Add to recent inputs
        input_record = {
            "user_id": user_id,
            "user_name": user_name,
            "button": button.value,
            "timestamp": datetime.utcnow().isoformat(),
        }

        session.state.recent_inputs.append(input_record)

        # Keep only last 3 (FIFO)
        if len(session.state.recent_inputs) > 3:
            session.state.recent_inputs = session.state.recent_inputs[-3:]

    async def _process_input(
        self,
        chat_id: int,
        button: GameButton,
        message_id: int,
    ) -> None:
        """Process a game input and animate the results.
        
        Args:
            chat_id: Telegram chat ID
            button: The button that was pressed
            message_id: Telegram message ID to edit
        """
        # Get or create game controller
        controller = await game_controller_manager.get_or_create_controller(chat_id)
        
        # Update message to show processing state (remove keyboard)
        await self._edit_message_keyboard(
            chat_id,
            message_id,
            create_processing_keyboard(button),
        )
        
        # Execute the input
        logger.info(f"Executing input {button.value} for chat {chat_id}")
        if button == GameButton.WAIT:
            # WAIT button: Don't press any button, just tick the emulator
            # This allows the animation phase to show game progress without input
            logger.debug(f"WAIT button pressed for chat {chat_id}, skipping button input")
            frame = controller.tick(frames=settings.input_hold_frames)
        else:
            # Normal button: press and hold
            frame = controller.send_input(button, frames=settings.input_hold_frames)
        session = self._get_session(chat_id)
        recent = session.state.recent_inputs if session else []
        caption = create_game_message_text(recent_inputs=recent)
        
        # Animation phase
        await self._animate_frames(chat_id, message_id, controller, caption)
        
        # Re-enable input with fresh keyboard
        await self._edit_message_keyboard(
            chat_id,
            message_id,
            create_input_keyboard(),
        )
        
        
        # Auto-save if enabled
        config = state_manager.get_or_create_chat_config(chat_id)
        if config.auto_save_enabled:
            try:
                # Get next slot
                slot = state_manager.find_next_auto_save_slot(chat_id)
                
                # Save state
                state_data = controller.save_state()
                state_manager.save_to_slot(
                    chat_id=chat_id,
                    slot_number=slot,
                    state_data=state_data,
                    description=f"Auto-save",
                    is_auto_save=True,
                )
                logger.debug(f"Auto-saved game to slot {slot} for chat {chat_id}")
            except Exception as e:
                logger.warning(f"Failed to auto-save for chat {chat_id}: {e}")
        
        logger.info(f"Completed input processing for chat {chat_id}")
    
    async def _animate_frames(
        self,
        chat_id: int,
        message_id: int,
        controller: GameController,
        caption: str,
    ) -> None:
        """Animate frame updates during the animation phase.
        
        Accumulates frames and sends them as a single GIF animation.
        
        Args:
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            controller: GameController instance
            caption: Message caption
        """
        frames = []
        start_time = asyncio.get_event_loop().time()
        
        # Capture frames at 10 FPS for the GIF
        capture_fps = 10
        capture_interval = 1.0 / capture_fps
        duration_ms = int(capture_interval * 1000)
        
        # Determine how many game frames to tick per capture
        # If we want 10 FPS output and game runs at 60 FPS, we might want to just tick enough to match time?
        # Or we use settings.animation_tick_frames if that logic was specific to game speed.
        # User said "tick the emulator over the animation duration".
        # Let's stick closer to the original game speed feeling.
        # If we capture every 0.1s, we should ideally tick 6 frames (0.1s * 60fps).
        frames_per_tick = 6 
        
        logger.info(f"Starting animation phase for chat {chat_id}, accumulating frames...")
        
        while (asyncio.get_event_loop().time() - start_time) < settings.animation_duration:
            # Tick forward
            controller.tick(frames_per_tick)
            
            # Capture frame
            frames.append(controller.get_frame().copy())
            
            # Wait for next capture interval
            await asyncio.sleep(capture_interval)
            
        if frames:
            logger.info(f"Generating GIF for chat {chat_id} with {len(frames)} frames")
            try:
                # Generate GIF
                # Determine last frame duration (2 seconds)
                gif_buffer = save_frames_as_gif(
                    frames,
                    duration=duration_ms,
                    last_frame_duration=2000
                )
                # Ensure buffer is at start position
                gif_buffer.seek(0)

                # Send GIF
                await self._edit_message_media(
                    chat_id,
                    message_id,
                    gif_buffer,
                    caption,
                    media_type="animation"
                )
                
                # Update hash with the last frame so we don't resend it immediately if next action is same
                _, last_hash = should_update_frame(frames[-1], None)
                controller.update_frame_hash(last_hash)
            except Exception as e:
                logger.error(f"Failed to generate or send GIF for chat {chat_id}: {e}")
                # Fallback to sending the last frame as photo
                try:
                    png_buffer = controller.get_frame_as_png()
                    await self._edit_message_media(
                        chat_id,
                        message_id,
                        png_buffer,
                        caption
                    )
                except Exception as e2:
                    logger.error(f"Fallback failed for chat {chat_id}: {e2}")
    
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
                media_buffer.name = "animation.gif"
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
        
        # Send initial message

        recent = session.state.recent_inputs if session else []
        message = await self.bot.send_photo(
            chat_id=chat_id,
            photo=png_buffer,
            caption=create_game_message_text(recent_inputs=recent),
            reply_markup=create_input_keyboard(),
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
        
        # Get current frame
        frame = controller.get_frame()
        png_buffer = controller.get_frame_as_png()
        recent = session.state.recent_inputs if session else []
        caption = create_game_message_text(recent_inputs=recent)
        
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
                    create_input_keyboard(),
                )
                return session.state.message_id
            except TelegramError:
                # Fall through to sending new message
                pass
        
        message = await self.bot.send_photo(
            chat_id=chat_id,
            photo=png_buffer,
            caption=caption,
            reply_markup=create_input_keyboard() if not (session and session.state.input_in_progress) else None,
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

        if not controller or not controller.is_initialized():
            return None

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
            caption=create_game_message_text(recent_inputs=recent),
            reply_markup=create_input_keyboard(),
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
