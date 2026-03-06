"""Input handler for managing game interactions.

This module handles button presses, input processing, and game flow
including the first-vote-wins logic and animation phases.
"""

import asyncio
import logging
import time
from typing import Optional, TYPE_CHECKING
from datetime import datetime

from src.adapters.base import BotAdapter
from src.config import settings
from src.game import game_controller_manager
from src.i18n import translation_manager
from src.keyboard import (
    create_game_message_text,
    get_button_from_callback,
    is_valid_button_callback,
)
from src.models.game_state import ChatGameState, GameButton, GameSession, ModifierButtonSpec
from src.models.input_queue import InputQueue, QueueItem
from src.utils.frame_utils import (  # noqa: F401 (needed for test patching)
    save_frames_as_mp4,
    generate_tbc_frames,
)
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
    3. Updating platform messages with new frames via adapters
    4. Managing game state transitions (IDLE/PROCESSING)
    """

    def __init__(self):
        """Initialize the input handler."""
        self._sessions: dict[int, GameSession] = {}
        self._processing: set[int] = set()  # Chats currently processing
        self._input_queues: dict[int, InputQueue] = {}  # Chat ID -> InputQueue

    def _get_session(self, chat_id: int) -> Optional[GameSession]:
        """Get or create a game session for a chat."""
        if chat_id not in self._sessions:
            state = state_manager.load_game_state(chat_id)
            if state:
                self._sessions[chat_id] = GameSession(chat_id=chat_id, state=state)

        return self._sessions.get(chat_id)

    def _create_session(self, chat_id: int, message_id: int) -> GameSession:
        """Create a new game session."""
        state = ChatGameState(chat_id=chat_id, message_id=message_id)
        session = GameSession(chat_id=chat_id, state=state)
        self._sessions[chat_id] = session

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

    def _get_message_base_text(self, chat_id: int) -> str | None:
        """Get custom message base text for a chat if configured."""
        try:
            config = state_manager.load_chat_config(chat_id)
            if config and config.message_base_text:
                return config.message_base_text
        except Exception:
            pass
        return None

    def _is_processing(self, chat_id: int) -> bool:
        """Check if a chat is currently processing input."""
        return chat_id in self._processing

    def _get_adapter_for_chat(self, chat_id: int) -> Optional[BotAdapter]:
        """Look up the platform adapter for a given chat.

        Args:
            chat_id: The chat ID to look up

        Returns:
            BotAdapter for the chat's platform, or None if not found
        """
        from src.adapters.base import get_adapter
        config = state_manager.load_chat_config(chat_id)
        platform = config.platform if config else "telegram"
        return get_adapter(platform)

    async def handle_button_press(
        self,
        callback_data: str,
        chat_id: int,
        message_id: int,
        user_id: int,
        user_name: str,
        adapter: BotAdapter,
        raw: object = None,
    ) -> None:
        """Handle a button press with queue-based processing.

        Args:
            callback_data: The callback data string (button value)
            chat_id: Platform chat ID
            message_id: Message ID being interacted with
            user_id: User ID who pressed the button
            user_name: Display name of the user
            adapter: Platform adapter for sending responses
            raw: Platform-specific event object (for answering interactions)
        """
        # Handle modifier button presses before GameButton validation
        if callback_data.startswith("modifier_"):
            session = self._get_session(chat_id)
            if not session:
                try:
                    await adapter.answer_interaction(raw, translation_manager.get("game.no_active_game", chat_id))
                except Exception as e:
                    logger.error(f"Error processing modifier for chat {chat_id}: {e}")
                return
            if session.state.message_id != message_id:
                try:
                    await adapter.answer_interaction(raw, translation_manager.get("game.message_outdated", chat_id))
                except Exception as e:
                    logger.error(f"Error processing modifier for chat {chat_id}: {e}")
                return
            key = callback_data[len("modifier_"):]
            await self._handle_modifier_button_press(raw, chat_id, message_id, key, adapter)
            return

        if not is_valid_button_callback(callback_data):
            try:
                await adapter.answer_interaction(raw, "Invalid button")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        button = get_button_from_callback(callback_data)
        session = self._get_session(chat_id)
        if not session or button is None:
            try:
                error_msg = translation_manager.get("game.no_active_game", chat_id)
                await adapter.answer_interaction(raw, error_msg)
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        # Validate message is current
        if session.state.message_id != message_id:
            try:
                error_msg = translation_manager.get("game.message_outdated", chat_id)
                await adapter.answer_interaction(raw, error_msg)
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        # Get or create queue
        queue = self._get_or_create_queue(chat_id)

        # Add input to queue
        success, (message_key, message_params) = queue.add_input(user_id, user_name, button)

        if not success:
            try:
                await adapter.answer_interaction(raw, translation_manager.get(message_key, chat_id, **message_params))
            except Exception as e:
                logger.error(f"Error answering callback for chat {chat_id}: {e}")
            return

        # Save queue to session state
        session.state.input_queue = queue
        state_manager.save_game_state(session.state)

        # Check if we should start processing
        if not self._is_processing(chat_id):
            try:
                await adapter.answer_interaction(raw, translation_manager.get('game.input_processing', chat_id, input=translation_manager.get(f'keyboard.buttons.display_name.{button.value}', chat_id)))
                asyncio.create_task(self._process_queue_loop(chat_id, message_id, adapter))
            except Exception as e:
                logger.error(f"Error starting queue processing for chat {chat_id}: {e}")
                await self._send_error_message(chat_id, translation_manager.get('game.input_processing_error', chat_id), adapter)
        else:
            try:
                await adapter.answer_interaction(raw, translation_manager.get(message_key, chat_id, **message_params))
            except Exception as e:
                logger.error(f"Error answering callback for chat {chat_id}: {e}")

    async def _handle_modifier_button_press(
        self, raw: object, chat_id: int, message_id: int, key: str, adapter: BotAdapter
    ) -> None:
        """Handle a modifier button press to toggle modifier state."""
        config = state_manager.get_or_create_chat_config(chat_id)
        config.modifier_states[key] = not config.modifier_states.get(key, False)
        state_manager.save_chat_config(config)

        controller = await game_controller_manager.get_or_create_controller(chat_id)
        modifier_specs = controller.get_modifier_specs() if controller else []

        keyboard = adapter.build_game_keyboard(chat_config=config, modifier_specs=modifier_specs)
        await adapter.edit_game_keyboard(chat_id, message_id, keyboard)

        spec = next((s for s in modifier_specs if s.key == key), None)
        if spec:
            is_active = config.modifier_states[key]
            label_key = spec.active_label_key if is_active else spec.inactive_label_key
            message = translation_manager.get(label_key, chat_id)
        else:
            message = ""
        try:
            await adapter.answer_interaction(raw, message)
        except Exception as e:
            logger.error(f"Error answering modifier callback for chat {chat_id}: {e}")

    async def _process_sequence(
        self, chat_id: int, buttons: list[GameButton], message_id: int, adapter: BotAdapter
    ) -> None:
        """Process a sequence of buttons (backward compatibility alias)."""
        item = QueueItem(
            user_id=0,
            user_name="System",
            buttons=buttons,
        )
        await self._process_queue_item(chat_id, message_id, item, adapter)

    def _record_user_input(
        self,
        session: GameSession,
        user_id: int,
        user_name: str,
        buttons: list[GameButton],
    ) -> None:
        """Record user input (single button or sequence)."""
        session.state.user_input_counts[str(user_id)] = (
            session.state.user_input_counts.get(str(user_id), 0) + len(buttons)
        )

        input_record = {
            "user_id": user_id,
            "user_name": user_name,
            "buttons": [b.value for b in buttons],
            "timestamp": datetime.utcnow().isoformat(),
        }

        session.state.recent_inputs.append(input_record)

        if len(session.state.recent_inputs) > 3:
            session.state.recent_inputs = session.state.recent_inputs[-3:]

    async def _process_queue_loop(self, chat_id: int, message_id: int, adapter: BotAdapter) -> None:
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
                wait_time = self._calculate_processing_time(item.buttons)

                try:
                    result = await self._process_queue_item(chat_id, message_id, item, adapter)
                    if result["animation_duration"]:
                        wait_time = result["animation_duration"]
                except Exception as e:
                    logger.error(f"Error processing queue item for chat {chat_id}: {e}")

                state_manager.save_game_state(session.state)

                if wait_time > 0:
                    await asyncio.sleep(wait_time)

        finally:
            self._processing.discard(chat_id)
            if session:
                session.state.input_in_progress = False
                state_manager.save_game_state(session.state)

            logger.info(f"Queue processing completed for chat {chat_id}")

    async def _process_queue_item(
        self, chat_id: int, message_id: int, item: QueueItem, adapter: BotAdapter
    ) -> dict:
        """Process a single queue item."""
        queue = self._get_or_create_queue(chat_id)
        controller = await game_controller_manager.get_or_create_controller(chat_id)
        checkpoint = controller.save_state()
        session = self._get_session(chat_id)
        buttons = item.buttons

        hook_context = controller.begin_hooks()

        self._record_user_input(session, item.user_id, item.user_name, buttons)

        config = state_manager.get_or_create_chat_config(chat_id)
        modifier_specs = controller.get_modifier_specs()
        modifier_states = config.modifier_states if config else {}

        input_keyboard = adapter.build_game_keyboard(chat_config=config, modifier_specs=modifier_specs)

        logger.info(f"Executing sequence of {len(buttons)} buttons for chat {chat_id} (modifier_states={modifier_states})")

        # Animation capture settings - GameBoy runs at 60fps, capture at 10fps
        frames = []
        game_fps = 60
        capture_fps = 10
        capture_interval_frames = game_fps // capture_fps

        frames.append(controller.get_frame().copy())

        for i, button in enumerate(buttons):
            if button == GameButton.WAIT:
                logger.debug(f"WAIT button in sequence for chat {chat_id}")
                controller.tick(frames=settings.input_hold_frames)
            else:
                applied = False
                for spec in modifier_specs:
                    if modifier_states.get(spec.key) and button in spec.applies_to:
                        logger.debug(f"Executing {button.value} with {spec.modifier_button.value} modifier for chat {chat_id}")
                        controller.send_input_with_modifier(button, spec.modifier_button, frames=settings.input_hold_frames)
                        applied = True
                        break
                if not applied:
                    logger.debug(f"Executing {button.value} in sequence for chat {chat_id}")
                    controller.send_input(button, frames=settings.input_hold_frames)

            frames.append(controller.get_frame().copy())

            if i < len(buttons) - 1:
                delay_frames = int(settings.sequence_delay_seconds * game_fps)
                for frame_num in range(delay_frames):
                    controller.tick(1)
                    if frame_num % capture_interval_frames == 0:
                        frames.append(controller.get_frame().copy())

        # Continue animating after last button press
        animation_frames = int(settings.animation_duration * game_fps)
        wait_call_threshold = hook_context.get("inputWaitCalls", {}).get("_total", 0) + game_fps

        for frame_num in range(animation_frames):
            controller.tick(1)
            if hook_context.get("inputWaitCalls", {}).get("_total", 0) > wait_call_threshold:
                logger.info("Input wait loop detected, finishing animation early")
                break
            if frame_num % capture_interval_frames == 0:
                frames.append(controller.get_frame().copy())

        logger.info(f"Animation completed for chat {chat_id} in {animation_frames} frames")

        controller.end_hooks(hook_context)

        if hook_context.get("dangerousActions", {}).get("_total", 0) > 0:
            logger.info(f"Dangerous action ({str(hook_context.get('dangerousActions', {}))}) blocked for chat {chat_id}")
            controller.load_state(checkpoint)
            error_msg = translation_manager.get("game.safe_mode_blocked", chat_id)
            await self._send_error_message(chat_id, error_msg, adapter)
            return {"animation_duration": None}

        animation_duration_seconds = len(frames) / capture_fps

        tbc_frames = generate_tbc_frames(
            frames[-1] if frames else controller.get_frame(),
            overlay_path=settings.tbc_overlay_path,
            duration_frames=settings.tbc_duration_frames,
            max_width_percent=0.7
        )
        frames.extend(tbc_frames)

        recent = session.state.recent_inputs if session else []
        base_text = self._get_message_base_text(chat_id)
        caption = create_game_message_text(recent_inputs=recent, queue_length=len(queue), base_text_override=base_text, chat_id=chat_id)

        if frames:
            logger.info(f"Generating MP4 with {len(frames)} frames for chat {chat_id}")
            try:
                mp4_buffer = save_frames_as_mp4(frames, fps=capture_fps)
                mp4_buffer.seek(0)

                file_id = await adapter.edit_game_message(
                    chat_id, message_id, caption, input_keyboard, mp4_buffer, media_type="animation"
                )
                if file_id and session:
                    session.state.last_animation_file_id = file_id

                    # Enqueue timelapse encoding (non-blocking)
                    from src.tasks.timelapse_encoder import timelapse_queue
                    from datetime import datetime

                    if timelapse_queue is not None:
                        try:
                            frames_without_tbc = frames[:-settings.tbc_duration_frames] if len(frames) > settings.tbc_duration_frames else frames
                            skipped_frames = frames_without_tbc[::settings.timelapse_frame_skip]
                            timestamp = datetime.now().isoformat()
                            await timelapse_queue.enqueue(chat_id, skipped_frames, timestamp)
                            logger.debug(f"Enqueued {len(skipped_frames)} frames for timelapse encoding (chat {chat_id})")
                        except Exception as e:
                            logger.warning(f"Failed to enqueue timelapse for chat {chat_id}: {e}")

            except Exception as e:
                logger.error(f"Failed to generate MP4 for chat {chat_id}: {e}")
                try:
                    png_buffer = controller.get_frame_as_png()
                    await adapter.edit_game_message(chat_id, message_id, caption, input_keyboard, png_buffer, media_type="photo")
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
                    description="Auto-save",
                    is_auto_save=True,
                )
                logger.debug(f"Auto-saved to slot {slot} for chat {chat_id}")
            except Exception as e:
                logger.warning(f"Failed to auto-save for chat {chat_id}: {e}")

        logger.info(f"Completed queue item processing for chat {chat_id}")
        return {"animation_duration": animation_duration_seconds}

    async def _edit_message_keyboard(
        self, chat_id: int, message_id: int, keyboard, adapter: BotAdapter
    ) -> None:
        """Helper to edit message keyboard via adapter."""
        try:
            await adapter.edit_game_keyboard(chat_id=chat_id, message_id=message_id, keyboard=keyboard)
        except Exception as e:
            logger.error(f"Failed to edit keyboard for message {message_id} in chat {chat_id}: {e}")

    async def _edit_message_media(
        self, chat_id: int, message_id: int, media_buffer, caption: str, adapter: BotAdapter,
        media_type: str = "photo", keyboard=None
    ) -> Optional[str]:
        """Helper to edit message media via adapter."""
        try:
            return await adapter.edit_game_message(chat_id, message_id, caption, keyboard, media_buffer, media_type=media_type)
        except Exception as e:
            logger.error(f"Failed to edit media for message {message_id} in chat {chat_id}: {e}")
            return None

    async def _send_error_message(self, chat_id: int, text: str, adapter: BotAdapter) -> None:
        """Send an error message to the chat."""
        try:
            await adapter.send_text(chat_id, f"❌ {text}")
        except Exception as e:
            logger.error(f"Failed to send error message to chat {chat_id}: {e}")

    async def start_game(self, chat_id: int, adapter: BotAdapter) -> int:
        """Start a new game for a chat.

        Args:
            chat_id: Platform chat ID
            adapter: Platform adapter for sending messages

        Returns:
            Message ID of the sent game message
        """
        controller = await game_controller_manager.get_or_create_controller(chat_id)
        png_buffer = controller.get_frame_as_png()

        session = self._create_session(chat_id, 0)

        config = state_manager.get_or_create_chat_config(chat_id)
        modifier_specs = controller.get_modifier_specs()

        queue = self._get_or_create_queue(chat_id)

        recent = session.state.recent_inputs if session else []
        base_text = self._get_message_base_text(chat_id)
        text = create_game_message_text(recent_inputs=recent, queue_length=len(queue), base_text_override=base_text, chat_id=chat_id)
        keyboard = adapter.build_game_keyboard(chat_config=config, modifier_specs=modifier_specs)

        message_id = await adapter.send_game_message(chat_id, text, keyboard, png_buffer)

        session.state.message_id = message_id
        state_manager.save_game_state(session.state)

        logger.info(f"Started game for chat {chat_id}, message {message_id}")

        return message_id

    async def show_current_frame(self, chat_id: int, adapter: BotAdapter) -> Optional[int]:
        """Show the current game frame.

        Args:
            chat_id: Platform chat ID
            adapter: Platform adapter for sending messages

        Returns:
            Message ID if successful, None otherwise
        """
        session = self._get_session(chat_id)
        controller = game_controller_manager.get_controller(chat_id)

        if not controller or not controller.is_initialized():
            return None

        config = state_manager.get_or_create_chat_config(chat_id)
        modifier_specs = controller.get_modifier_specs()

        queue = self._get_or_create_queue(chat_id)

        png_buffer = controller.get_frame_as_png()
        recent = session.state.recent_inputs if session else []
        base_text = self._get_message_base_text(chat_id)
        caption = create_game_message_text(recent_inputs=recent, queue_length=len(queue), base_text_override=base_text, chat_id=chat_id)
        keyboard = adapter.build_game_keyboard(chat_config=config, modifier_specs=modifier_specs)

        if session and session.state.message_id and not session.state.input_in_progress:
            try:
                await adapter.edit_game_message(
                    chat_id,
                    session.state.message_id,
                    caption,
                    keyboard,
                    png_buffer,
                    media_type="photo",
                )
                return session.state.message_id
            except Exception:
                pass

        message_id = await adapter.send_game_message(
            chat_id,
            caption,
            keyboard if not (session and session.state.input_in_progress) else None,
            png_buffer,
        )

        if session:
            session.state.message_id = message_id
        else:
            self._create_session(chat_id, message_id)

        return message_id

    async def resume_game(self, chat_id: int, adapter: BotAdapter) -> Optional[int]:
        """Resume the game by sending a new message with keyboard.

        Args:
            chat_id: Platform chat ID
            adapter: Platform adapter for sending messages

        Returns:
            Message ID of the new game message, or None if failed
        """
        session = self._get_session(chat_id)
        controller = game_controller_manager.get_controller(chat_id)
        queue = self._get_or_create_queue(chat_id)

        if not controller or not controller.is_initialized():
            return None

        config = state_manager.get_or_create_chat_config(chat_id)
        modifier_specs = controller.get_modifier_specs()

        png_buffer = controller.get_frame_as_png()

        # Remove keyboard from old message if it exists
        if session and session.state.message_id:
            try:
                await adapter.edit_game_keyboard(chat_id, session.state.message_id, None)
            except Exception:
                pass

        recent = session.state.recent_inputs if session else []
        base_text = self._get_message_base_text(chat_id)
        text = create_game_message_text(recent_inputs=recent, queue_length=len(queue), base_text_override=base_text, chat_id=chat_id)
        keyboard = adapter.build_game_keyboard(chat_config=config, modifier_specs=modifier_specs)

        message_id = await adapter.send_game_message(chat_id, text, keyboard, png_buffer)

        if session:
            session.state.message_id = message_id
            state_manager.save_game_state(session.state)
        else:
            self._create_session(chat_id, message_id)

        logger.info(f"Resumed game for chat {chat_id}, new message {message_id}")

        return message_id

    def is_input_in_progress(self, chat_id: int) -> bool:
        """Check if input is currently being processed for a chat."""
        return chat_id in self._processing

    def cleanup_session(self, chat_id: int) -> bool:
        """Clean up a game session."""
        if chat_id in self._sessions:
            del self._sessions[chat_id]
            self._processing.discard(chat_id)
            self._input_queues.pop(chat_id, None)

            game_controller_manager.remove_controller(chat_id)

            logger.info(f"Cleaned up session for chat {chat_id}")
            return True

        return False


# Singleton instance
_input_handler: Optional[InputHandler] = None


def get_input_handler() -> InputHandler:
    """Get or create the singleton InputHandler instance.

    Returns:
        InputHandler instance
    """
    global _input_handler
    if _input_handler is None:
        _input_handler = InputHandler()
    return _input_handler
