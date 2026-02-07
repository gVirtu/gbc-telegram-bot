"""Input handler for managing game interactions.

This module handles button presses, input processing, and game flow
including the first-vote-wins logic and animation phases.
"""

import asyncio
import logging
from typing import Optional

from telegram import Bot, InputMediaPhoto
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
from src.utils.frame_utils import should_update_frame
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)


class InputHandlerError(Exception):
    """Base exception for input handler errors."""
    pass


class GameNotActiveError(InputHandlerError):
    """Raised when trying to interact with a game that isn't active."""
    pass


class InputInProgressError(InputHandlerError):
    """Raised when trying to input while another input is processing."""
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

        Raises:
            GameNotActiveError: If no game is active for this chat
            InputInProgressError: If input is already being processed
        """
        chat_id = callback_query.message.chat.id
        message_id = callback_query.message.message_id
        callback_data = callback_query.data

        # Validate callback is a game button
        if not is_valid_button_callback(callback_data):
            await callback_query.answer("Invalid button")
            return

        button = get_button_from_callback(callback_data)

        # Check if chat has an active session
        session = self._get_session(chat_id)
        if not session:
            await callback_query.answer("No active game! Use /start_game first.")
            return

        # Check if input is already being processed
        if chat_id in self._processing:
            await callback_query.answer("Input already in progress! Please wait...")
            return

        # Check if message matches (prevent old message interactions)
        if session.state.message_id != message_id:
            await callback_query.answer("This game message is outdated. Use /current_frame for the latest.")
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
            await self._send_error_message(chat_id, "Error processing input. Please try again.")
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
        
        Updates the message every animation_interval seconds for
        animation_duration seconds, skipping frames that haven't changed.
        
        Args:
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            controller: GameController instance
        """
        start_time = asyncio.get_event_loop().time()
        last_update = start_time
        
        while (asyncio.get_event_loop().time() - start_time) < settings.animation_duration:
            # Tick forward
            frame = controller.tick(settings.animation_tick_frames)
            
            # Check if we should update
            should_update, frame_hash = should_update_frame(
                frame, controller.last_frame_hash
            )
            
            if should_update:
                try:
                    png_buffer = controller.get_frame_as_png()
                    await self._edit_message_media(
                        chat_id,
                        message_id,
                        png_buffer,
                        caption,
                    )
                    controller.update_frame_hash(frame_hash)
                except TelegramError as e:
                    logger.warning(f"Failed to update frame for chat {chat_id}: {e}")
            else:
                logger.debug(f"Terminating animation phase early for {chat_id}")
                break
            
            # Wait for next interval
            elapsed = asyncio.get_event_loop().time() - last_update
            sleep_time = max(0, settings.animation_interval - elapsed)
            await asyncio.sleep(sleep_time)
            last_update = asyncio.get_event_loop().time()
    
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
        photo_buffer,
        caption: str,
    ) -> None:
        """Edit a message's media (photo).
        
        Args:
            chat_id: Telegram chat ID
            message_id: Message ID to edit
            photo_buffer: BytesIO containing PNG image
        """
        try:
            await self.bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=InputMediaPhoto(media=photo_buffer, caption=caption, parse_mode="Markdown"),
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
