"""Command handlers for Telegram bot commands.

This module implements handlers for all bot commands:
/start_game, /current_frame, /save, /load, /status, /help
"""

import logging
from io import BytesIO
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from src.config import settings
from src.game import game_controller_manager
from src.handlers.input_handler import get_input_handler
from src.keyboard import (
    create_confirmation_keyboard,
    create_game_message_text,
    create_help_text,
    create_input_keyboard,
    create_save_slot_keyboard,
)
from src.models.game_state import GameButton
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)


def _check_chat_allowed(update: Update) -> bool:
    """Check if the chat is allowed to use the bot.
    
    Args:
        update: Telegram Update object
        
    Returns:
        True if chat is allowed, False otherwise
    """
    chat_id = update.effective_chat.id
    if not settings.allowed_chat_ids:
        return True
    return chat_id in settings.allowed_chat_ids


async def _ensure_game_active(chat_id: int) -> tuple[bool, str | None]:
    """Ensure a game is active for the chat, auto-starting if needed.

    If no game is active, this function will:
    1. Initialize the game controller
    2. Try to load save slot 1 if it exists
    3. Fall back to initial state if slot 1 doesn't exist or fails

    Args:
        chat_id: Telegram chat ID

    Returns:
        Tuple of (success: bool, error_message: str | None)
        If success is True, a game is now active.
        If success is False, error_message contains the reason.
    """
    # Check if game is already active
    controller = game_controller_manager.get_controller(chat_id)
    if controller and controller.is_initialized():
        return True, None

    try:
        # Initialize controller
        controller = await game_controller_manager.get_or_create_controller(chat_id)

        # Try to load slot 1 if it exists
        state_data = state_manager.load_from_slot(chat_id, 1)
        if state_data is not None:
            try:
                controller.load_state(state_data)
                logger.info(f"Auto-started game for chat {chat_id} from slot 1")
                return True, None
            except Exception as e:
                logger.warning(f"Failed to load slot 1 for chat {chat_id}: {e}")
                # Fall through to initial state

        # Use initial state (fresh game)
        logger.info(f"Auto-started game for chat {chat_id} with initial state")
        return True, None

    except Exception as e:
        logger.error(f"Failed to auto-start game for chat {chat_id}: {e}")
        return False, "Failed to start game. Please try /start_game manually."


async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start_game command.
    
    Initializes a new game or restarts an existing one.
    Loads the initial save state and sends the first frame.
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return
    
    chat_id = update.effective_chat.id
    
    await update.message.reply_text("🎮 Starting Pokémon Red...")
    
    try:
        handler = get_input_handler(context.bot)
        
        # Clean up any existing session
        handler.cleanup_session(chat_id)
        
        # Start new game
        message_id = await handler.start_game(chat_id)
        
        logger.info(f"Started game for chat {chat_id}, message {message_id}")
        
    except Exception as e:
        logger.error(f"Error starting game for chat {chat_id}: {e}")
        await update.message.reply_text(
            "❌ Failed to start game. Please make sure the ROM file is available."
        )


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume command.

    Resumes the game by removing the keyboard from the old message
    and sending a new game message with the current frame.
    Unlike /start_game, this does not restart the game.
    Auto-starts the game if not already active.
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return

    chat_id = update.effective_chat.id

    # Ensure game is active (auto-start if needed)
    success, error_msg = await _ensure_game_active(chat_id)
    if not success:
        await update.message.reply_text(f"❌ {error_msg}")
        return

    try:
        handler = get_input_handler(context.bot)

        # Check if input is in progress
        if handler.is_input_in_progress(chat_id):
            await update.message.reply_text(
                "⏳ Input is being processed. Please wait..."
            )
            return

        # Resume game - remove old keyboard, send new message
        message_id = await handler.resume_game(chat_id)

        if message_id:
            logger.info(f"Resumed game for chat {chat_id}")
        else:
            await update.message.reply_text(
                "❌ Failed to resume game. Try /start_game first."
            )

    except Exception as e:
        logger.error(f"Error resuming game for chat {chat_id}: {e}")
        await update.message.reply_text(
            "❌ Error resuming game. Please try again."
        )


async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /save command.
    
    Saves the current game state to a slot.
    Usage: /save [slot_number]
    If no slot specified, uses the next available slot.
    Auto-starts the game if not already active.
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return
    
    chat_id = update.effective_chat.id
    
    # Ensure game is active (auto-start if needed)
    success, error_msg = await _ensure_game_active(chat_id)
    if not success:
        await update.message.reply_text(f"❌ {error_msg}")
        return
    
    controller = game_controller_manager.get_controller(chat_id)
    
    # Parse slot number
    slot_number: Optional[int] = None
    if context.args:
        try:
            slot_number = int(context.args[0])
            if slot_number < 0 or slot_number >= settings.save_slots:
                await update.message.reply_text(
                    f"❌ Invalid slot number. Use 0-{settings.save_slots - 1}."
                )
                return
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid slot number. Please use a number."
            )
            return
    
    try:
        # Get slot to save to
        if slot_number is None:
            # Find next available slot
            existing_slots = state_manager.list_save_slots(chat_id, max_slots=settings.save_slots)
            used_slots = {s.slot_number for s in existing_slots}
            
            # Find first available slot
            for i in range(settings.save_slots):
                if i not in used_slots:
                    slot_number = i
                    break
            else:
                # All slots used, use slot 0
                slot_number = 0
        
        # Save the state
        state_data = controller.save_state()
        info = state_manager.save_to_slot(
            chat_id=chat_id,
            slot_number=slot_number,
            state_data=state_data,
            description=f"Manual save by user",
            is_auto_save=False,
        )
        
        await update.message.reply_text(
            f"💾 Game saved to slot {slot_number}!"
        )
        
        logger.info(f"Saved game for chat {chat_id} to slot {slot_number}")
        
    except Exception as e:
        logger.error(f"Error saving game for chat {chat_id}: {e}")
        await update.message.reply_text(
            "❌ Failed to save game. Please try again."
        )


async def load_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /load command.
    
    Loads a game state from a slot.
    Usage: /load [slot_number]
    If no slot specified, shows available slots.
    Auto-starts the game if not already active.
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return
    
    chat_id = update.effective_chat.id
    
    # Ensure game is active (auto-start if needed)
    success, error_msg = await _ensure_game_active(chat_id)
    if not success:
        await update.message.reply_text(f"❌ {error_msg}")
        return
    
    controller = game_controller_manager.get_controller(chat_id)
    
    # Check if input is in progress
    handler = get_input_handler(context.bot)
    if handler.is_input_in_progress(chat_id):
        await update.message.reply_text(
            "⏳ Cannot load while input is being processed. Please wait..."
        )
        return
    
    # Parse slot number
    if not context.args:
        # Show available slots
        slots = state_manager.list_save_slots(chat_id, max_slots=settings.save_slots)
        
        if not slots:
            await update.message.reply_text(
                "No save slots found. Use /save [slot] to create one."
            )
            return
        
        # Show slot selection keyboard
        await update.message.reply_text(
            "Select a save slot to load:",
            reply_markup=create_save_slot_keyboard(chat_id, settings.save_slots)
        )
        return
    
    try:
        slot_number = int(context.args[0])
        if slot_number < 0 or slot_number >= settings.save_slots:
            await update.message.reply_text(
                f"❌ Invalid slot number. Use 0-{settings.save_slots - 1}."
            )
            return
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid slot number. Please use a number."
        )
        return
    
    try:
        # Load the state
        state_data = state_manager.load_from_slot(chat_id, slot_number)
        
        if state_data is None:
            await update.message.reply_text(
                f"❌ No save found in slot {slot_number}."
            )
            return
        
        # Load into emulator
        controller.load_state(state_data)
        
        # Show the loaded frame
        await handler.show_current_frame(chat_id)
        
        await update.message.reply_text(
            f"📂 Loaded game from slot {slot_number}!"
        )
        
        logger.info(f"Loaded game for chat {chat_id} from slot {slot_number}")
        
    except Exception as e:
        logger.error(f"Error loading game for chat {chat_id}: {e}")
        await update.message.reply_text(
            "❌ Failed to load game. The save file might be corrupted."
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command.

    Shows the current game status including:
    - Whether a game is active
    - Current input status
    - Save slot information
    Auto-starts the game if not already active.
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return

    chat_id = update.effective_chat.id

    # Ensure game is active (auto-start if needed)
    success, error_msg = await _ensure_game_active(chat_id)
    if not success:
        await update.message.reply_text(f"❌ {error_msg}")
        return

    lines = ["📊 *Game Status*\n"]

    controller = game_controller_manager.get_controller(chat_id)
    lines.append("✅ Game is active")

    # Check input status
    handler = get_input_handler(context.bot)
    if handler.is_input_in_progress(chat_id):
        lines.append("⏳ Input is being processed")
    else:
        lines.append("✋ Waiting for input")

    # Get last input
    session = handler._get_session(chat_id)
    if session and session.state.last_input:
        lines.append(f"🎮 Last input: {session.state.last_input.display_name}")

    # Save slot info
    slots = state_manager.list_save_slots(chat_id, max_slots=settings.save_slots)
    if slots:
        lines.append(f"\n💾 Save slots used: {len(slots)}/{settings.save_slots}")
        for slot in slots:
            auto_save_marker = " (auto)" if slot.is_auto_save else ""
            lines.append(f"  • Slot {slot.slot_number}{auto_save_marker}")
    else:
        lines.append("\n💾 No save slots used")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown"
    )


async def print_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /print command.

    Sends the current game frame as a new media message without advancing
    frames and without the input keyboard. Useful for capturing screenshots.
    Auto-starts the game if not already active.
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return

    chat_id = update.effective_chat.id

    # Ensure game is active (auto-start if needed)
    success, error_msg = await _ensure_game_active(chat_id)
    if not success:
        await update.message.reply_text(f"❌ {error_msg}")
        return

    try:
        controller = game_controller_manager.get_controller(chat_id)
        # Get current frame without advancing/ticking
        png_buffer = controller.get_frame_as_png()

        # Send as new photo message without keyboard
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=png_buffer,
            caption="🖨️ Game screenshot",
        )

        logger.info(f"Sent print frame for chat {chat_id}")

    except Exception as e:
        logger.error(f"Error printing frame for chat {chat_id}: {e}")
        await update.message.reply_text(
            "❌ Failed to capture screenshot. Please try again."
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command.
    
    Shows help information including button descriptions and available commands.
    """
    help_text = create_help_text()
    
    await update.message.reply_text(
        help_text,
        parse_mode="Markdown",
        reply_markup=create_input_keyboard()
    )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown commands."""
    await update.message.reply_text(
        "❓ Unknown command. Use /help to see available commands."
    )


# Command handlers dictionary for easy registration
COMMAND_HANDLERS = {
    "start_game": start_game_command,
    "resume": resume_command,
    "print": print_command,
    "save": save_command,
    "load": load_command,
    "status": status_command,
    "help": help_command,
}
