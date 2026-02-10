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
    create_sequence_building_keyboard,
    create_processing_keyboard_for_sequence,
    get_button_from_callback,
    is_valid_button_callback,
)
from src.models.game_state import ChatGameState, GameButton, GameSession, SequenceBuilder
from src.utils.frame_utils import should_update_frame, save_frames_as_mp4
from src.utils.rate_limiter import get_rate_limiter, RateLimitException
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
        """Handle a button press with state machine routing."""
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
        session = self._get_session(chat_id)
        if not session:
            try:
                await callback_query.answer("Nenhum jogo ativo! Use /start_game primeiro.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        # Extract user info
        user_id = callback_query.from_user.id
        user_name = (
            callback_query.from_user.first_name or
            (f"@{callback_query.from_user.username}" if callback_query.from_user.username else "User")
        )

        # STATE MACHINE ROUTING
        if session.state.sequence_builder is not None:
            # State: BUILDING_SEQUENCE
            await self._handle_button_in_sequence_mode(
                callback_query, session, button, user_id, user_name
            )
        elif button == GameButton.SEQUENCE:
            # Transition: IDLE → BUILDING_SEQUENCE
            await self._handle_sequence_button_press(
                callback_query, session, chat_id, message_id, user_id, user_name
            )
        else:
            # State: IDLE (normal single button press)
            await self._handle_normal_button_press(
                callback_query, session, chat_id, message_id, button, user_id, user_name
            )

    async def _handle_sequence_button_press(
        self, callback_query, session, chat_id, message_id, user_id, user_name
    ) -> None:
        """Handle SEQUENCE button press to start building."""
        # Check rate limits first
        limiter = get_rate_limiter()
        try:
            limiter.check_rate_limit(chat_id)
        except RateLimitException as e:
            try:
                await callback_query.answer(
                    f"⏳ {e.message}",
                    show_alert=False
                )
            except Exception as e_inner:
                logger.error(f"Error answering callback for chat {chat_id}: {e_inner}")
            return
        
        if chat_id in self._processing:
            try:
                await callback_query.answer("Input já está em progresso! Por favor aguarde.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        if session.state.message_id != message_id:
            try:
                await callback_query.answer("Esta mensagem está desatualizada. Use /resume para continuar.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        try:
            await callback_query.answer("Iniciando construção de sequência...")
            await self._start_sequence_building(chat_id, message_id, user_id, user_name)
        except Exception as e:
            logger.error(f"Error starting sequence for chat {chat_id}: {e}")
            await self._send_error_message(chat_id, "Erro ao iniciar sequência.")

    async def _handle_button_in_sequence_mode(
        self, callback_query, session, button, user_id, user_name
    ) -> None:
        """Handle button press while building sequence."""
        builder = session.state.sequence_builder
        chat_id = session.chat_id
        message_id = callback_query.message.message_id

        # Only sequence owner can interact
        if user_id != builder.user_id:
            try:
                await callback_query.answer(
                    f"{builder.user_name} está construindo uma sequência. Aguarde sua vez."
                )
            except Exception as e:
                logger.error(f"Error in sequence mode for chat {chat_id}: {e}")
            return

        # Handle ENVIAR button
        if button == GameButton.ENVIAR:
            if builder.is_empty():
                try:
                    await callback_query.answer("Adicione pelo menos um botão antes de enviar!")
                except Exception as e:
                    logger.error(f"Error in sequence mode for chat {chat_id}: {e}")
                return

            try:
                await callback_query.answer(f"Enviando sequência com {len(builder.buttons)} botões...")
                await self._submit_sequence(chat_id, message_id)
            except Exception as e:
                logger.error(f"Error submitting sequence for chat {chat_id}: {e}")
                await self._send_error_message(chat_id, "Erro ao enviar sequência.")
            return

        # Handle SEQUENCE button (shouldn't be available, but handle gracefully)
        if button == GameButton.SEQUENCE:
            try:
                await callback_query.answer("Você já está construindo uma sequência!")
            except Exception as e:
                logger.error(f"Error in sequence mode for chat {chat_id}: {e}")
            return

        # Add button to sequence
        if builder.add_button(button):
            try:
                await callback_query.answer(f"Adicionado: {button.display_name}")

                # Update message to show current sequence
                caption = self._create_sequence_building_caption(builder)

                state_manager.save_game_state(session.state)

                # Auto-submit if full
                if builder.is_full():
                    logger.info(f"Sequence full, auto-submitting for chat {chat_id}")
                    await self._submit_sequence(chat_id, message_id)
            except Exception as e:
                logger.error(f"Error adding button to sequence for chat {chat_id}: {e}")
        else:
            try:
                await callback_query.answer("Sequência completa! Pressione Enviar.")
            except Exception as e:
                logger.error(f"Error in sequence mode for chat {chat_id}: {e}")

    async def _handle_normal_button_press(
        self, callback_query, session, chat_id, message_id, button, user_id, user_name
    ) -> None:
        """Handle normal single button press (existing logic)."""
        # Check rate limits first
        limiter = get_rate_limiter()
        try:
            limiter.check_rate_limit(chat_id)
        except RateLimitException as e:
            try:
                await callback_query.answer(
                    f"⏳ {e.message}",
                    show_alert=False
                )
            except Exception as e_inner:
                logger.error(f"Error answering callback for chat {chat_id}: {e_inner}")
            return
        
        # This is the existing logic from the original handle_button_press
        if chat_id in self._processing:
            try:
                await callback_query.answer("Input já está em progresso! Por favor aguarde.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        if session.state.message_id != message_id:
            try:
                await callback_query.answer("Esta mensagem está desatualizada. Use /resume para continuar.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        self._processing.add(chat_id)
        session.state.input_in_progress = True
        session.state.last_input = button
        session.record_activity()

        # Record as 1-item sequence
        self._record_user_input(session, user_id, user_name, [button])

        try:
            await callback_query.answer(f"Processando: {button.display_name}")
            await self._process_sequence(chat_id, [button], message_id)
        except Exception as e:
            logger.error(f"Error processing input for chat {chat_id}: {e}")
            await self._send_error_message(chat_id, "Erro ao processar, por favor tente novamente.")
        finally:
            self._processing.discard(chat_id)
            session.state.input_in_progress = False
            state_manager.save_game_state(session.state)

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
        session.state.user_input_counts[user_id] = (
            session.state.user_input_counts.get(user_id, 0) + len(buttons)
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

    async def _start_sequence_building(
        self, chat_id: int, message_id: int, user_id: int, user_name: str
    ) -> None:
        """Start sequence building mode."""
        session = self._get_session(chat_id)
        if not session:
            return

        # Create sequence builder
        session.state.sequence_builder = SequenceBuilder(
            user_id=user_id,
            user_name=user_name,
            max_length=settings.max_sequence_length,
        )

        # Lock processing
        self._processing.add(chat_id)

        # Update keyboard
        await self._edit_message_keyboard(
            chat_id, message_id, create_sequence_building_keyboard()
        )

        # Start timeout check
        asyncio.create_task(self._check_sequence_timeout(chat_id, message_id))

        state_manager.save_game_state(session.state)
        logger.info(f"Started sequence building for chat {chat_id}, user {user_id}")

    async def _check_sequence_timeout(self, chat_id: int, message_id: int) -> None:
        """Monitor sequence building for timeout."""
        while True:
            await asyncio.sleep(0.5)

            session = self._get_session(chat_id)
            if not session or session.state.sequence_builder is None:
                # Sequence was submitted or cancelled
                return

            builder = session.state.sequence_builder

            if builder.has_timed_out(settings.sequence_build_timeout):
                if builder.is_empty():
                    # Silent cancel
                    logger.info(f"Sequence timeout with no buttons for chat {chat_id}")
                    session.state.sequence_builder = None
                    self._processing.discard(chat_id)

                    await self._edit_message_keyboard(
                        chat_id, message_id, create_input_keyboard()
                    )

                    state_manager.save_game_state(session.state)
                    return
                else:
                    # Auto-submit
                    logger.info(f"Sequence timeout, auto-submitting {len(builder.buttons)} buttons for chat {chat_id}")
                    await self._submit_sequence(chat_id, message_id)
                    return

    async def _submit_sequence(self, chat_id: int, message_id: int) -> None:
        """Submit and execute a sequence."""
        session = self._get_session(chat_id)
        if not session or not session.state.sequence_builder:
            return

        builder = session.state.sequence_builder
        buttons = builder.buttons.copy()
        user_id = builder.user_id
        user_name = builder.user_name

        # Clear sequence builder (transition to PROCESSING)
        session.state.sequence_builder = None
        state_manager.save_game_state(session.state)

        # Record entire sequence
        self._record_user_input(session, user_id, user_name, buttons)

        try:
            await self._process_sequence(chat_id, buttons, message_id)
        except Exception as e:
            logger.error(f"Error processing sequence for chat {chat_id}: {e}")
            await self._send_error_message(chat_id, "Erro ao processar sequência.")
        finally:
            self._processing.discard(chat_id)
            session.state.input_in_progress = False
            state_manager.save_game_state(session.state)

    def _create_sequence_building_caption(self, builder: SequenceBuilder) -> str:
        """Create caption for sequence building mode."""
        if builder.is_empty():
            return "_Construindo sequência: (vazio)_"
        emoji_sequence = " ".join([b.emoji for b in builder.buttons])
        return f"_Construindo sequência: {emoji_sequence}_"

    async def _process_sequence(
        self, chat_id: int, buttons: list[GameButton], message_id: int
    ) -> None:
        """Process a sequence of buttons (handles both single and multiple).

        Args:
            chat_id: Telegram chat ID
            buttons: List of buttons to execute (can be 1 item for single press)
            message_id: Message ID to edit
        """
        controller = await game_controller_manager.get_or_create_controller(chat_id)

        # Update to processing state
        await self._edit_message_keyboard(
            chat_id, message_id, create_processing_keyboard_for_sequence(buttons)
        )

        logger.info(f"Executing sequence of {len(buttons)} buttons for chat {chat_id}")

        # Animation capture settings - GameBoy runs at 60fps, capture at 10fps
        frames = []
        game_fps = 60
        capture_fps = 10
        capture_interval_frames = game_fps // capture_fps  # Capture every 6th frame

        # Execute each button with delays (synchronous, no real-time waiting)
        for i, button in enumerate(buttons):
            # Execute button
            if button == GameButton.WAIT:
                logger.debug(f"WAIT button in sequence for chat {chat_id}")
                controller.tick(frames=settings.input_hold_frames)
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
        session = self._get_session(chat_id)
        recent = session.state.recent_inputs if session else []
        caption = create_game_message_text(recent_inputs=recent)

        animation_frames = int(settings.animation_duration * game_fps)
        for frame_num in range(animation_frames):
            controller.tick(1)
            if frame_num % capture_interval_frames == 0:
                frames.append(controller.get_frame().copy())

        # Generate and send MP4
        if frames:
            logger.info(f"Generating MP4 with {len(frames)} frames for chat {chat_id}")
            try:
                mp4_buffer = save_frames_as_mp4(frames, fps=capture_fps)
                mp4_buffer.seek(0)

                await self._edit_message_media(
                    chat_id, message_id, mp4_buffer, caption, media_type="animation"
                )

                _, last_hash = should_update_frame(frames[-1], None)
                controller.update_frame_hash(last_hash)
            except Exception as e:
                logger.error(f"Failed to generate MP4 for chat {chat_id}: {e}")
                try:
                    png_buffer = controller.get_frame_as_png()
                    await self._edit_message_media(chat_id, message_id, png_buffer, caption)
                except Exception as e2:
                    logger.error(f"Fallback failed for chat {chat_id}: {e2}")

        # Re-enable input
        await self._edit_message_keyboard(chat_id, message_id, create_input_keyboard())

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

        logger.info(f"Completed sequence processing for chat {chat_id}")
    
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
