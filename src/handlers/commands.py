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


async def current_frame_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /current_frame command.
    
    Shows the current game frame. If input is being processed,
    shows a message indicating that.
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return
    
    chat_id = update.effective_chat.id
    
    try:
        handler = get_input_handler(context.bot)
        
        # Check if there's an active game
        controller = game_controller_manager.get_controller(chat_id)
        if not controller or not controller.is_initialized():
            await update.message.reply_text(
                "No active game! Use /start_game to begin playing."
            )
            return
        
        # Check if input is in progress
        if handler.is_input_in_progress(chat_id):
            await update.message.reply_text(
                "⏳ Input is being processed. Please wait..."
            )
            return
        
        # Show current frame
        message_id = await handler.show_current_frame(chat_id)
        
        if message_id:
            logger.info(f"Showed current frame for chat {chat_id}")
        else:
            await update.message.reply_text(
                "❌ Failed to show current frame. Try /start_game first."
            )
        
    except Exception as e:
        logger.error(f"Error showing frame for chat {chat_id}: {e}")
        await update.message.reply_text(
            "❌ Error showing current frame. Please try again."
        )


async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /save command.
    
    Saves the current game state to a slot.
    Usage: /save [slot_number]
    If no slot specified, uses the next available slot.
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return
    
    chat_id = update.effective_chat.id
    
    # Check if game is active
    controller = game_controller_manager.get_controller(chat_id)
    if not controller or not controller.is_initialized():
        await update.message.reply_text(
            "No active game! Use /start_game first."
        )
        return
    
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
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return
    
    chat_id = update.effective_chat.id
    
    # Check if game is active
    controller = game_controller_manager.get_controller(chat_id)
    if not controller or not controller.is_initialized():
        await update.message.reply_text(
            "No active game! Use /start_game first."
        )
        return
    
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
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return
    
    chat_id = update.effective_chat.id
    
    lines = ["📊 *Game Status*\n"]
    
    # Check if game is active
    controller = game_controller_manager.get_controller(chat_id)
    if not controller or not controller.is_initialized():
        lines.append("❌ No active game")
        lines.append("Use /start_game to begin playing.")
    else:
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
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ This bot is not authorized for this chat."
        )
        return

    chat_id = update.effective_chat.id

    # Check if game is active
    controller = game_controller_manager.get_controller(chat_id)
    if not controller or not controller.is_initialized():
        await update.message.reply_text(
            "No active game! Use /start_game to begin playing."
        )
        return

    try:
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
    "current_frame": current_frame_command,
    "print": print_command,
    "save": save_command,
    "load": load_command,
    "status": status_command,
    "help": help_command,
}
