"""Command handlers for Telegram bot commands.

This module implements handlers for all bot commands:
/start_game, /current_frame, /save, /load, /status, /help
"""

import logging
from io import BytesIO
from time import time
from typing import Optional, Dict, Tuple

from telegram import Update
from telegram.ext import ContextTypes

from src.config import settings
from src.game import game_controller_manager
from src.handlers.input_handler import get_input_handler
from src.keyboard import (
    create_game_message_text,
    create_help_text,
    create_input_keyboard,
    create_save_slot_keyboard,
)
from src.models.game_state import GameButton
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)

# Cache: (chat_id, user_id) -> (is_admin: bool, timestamp: float)
_admin_cache: Dict[Tuple[int, int], Tuple[bool, float]] = {}
_CACHE_TTL = 30  # seconds

def _get_cached_admin_status(chat_id: int, user_id: int) -> bool | None:
    """Get cached admin status if available and not expired.

    Args:
        chat_id: Telegram chat ID
        user_id: Telegram user ID

    Returns:
        Cached admin status (True/False) or None if not cached/expired
    """
    key = (chat_id, user_id)
    if key in _admin_cache:
        is_admin, timestamp = _admin_cache[key]
        if time() - timestamp < _CACHE_TTL:
            return is_admin
        else:
            del _admin_cache[key]  # Expired, remove from cache
    return None

def _cache_admin_status(chat_id: int, user_id: int, is_admin: bool) -> None:
    """Cache admin status for a user in a chat.

    Args:
        chat_id: Telegram chat ID
        user_id: Telegram user ID
        is_admin: Whether the user is an admin
    """
    _admin_cache[(chat_id, user_id)] = (is_admin, time())


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


async def _check_admin_permission(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> tuple[bool, str | None]:
    """Check if user has admin permission for restricted commands.

    In private chats, all users are allowed.
    In group/supergroup chats, only admins and creators are allowed.

    Args:
        update: Telegram Update object
        context: Telegram Context object

    Returns:
        Tuple of (is_allowed: bool, error_message: str | None)
    """
    chat_type = update.effective_chat.type

    # Private chats: always allow
    if chat_type == "private":
        return (True, None)

    # Group/supergroup chats: check admin status
    if chat_type in ("group", "supergroup"):
        try:
            chat_id = update.effective_chat.id
            user_id = update.effective_user.id

            # Check cache first
            cached = _get_cached_admin_status(chat_id, user_id)
            if cached is not None:
                if cached:
                    return (True, None)
                else:
                    return (False, "🔒 Apenas administradores do grupo podem usar este comando.")

            # Get member status from Telegram API
            chat_member = await context.bot.get_chat_member(chat_id, user_id)

            # Check if user is admin or creator
            # Note: chat_member.status is a string: "creator", "administrator", "member", "left", "kicked"
            is_admin = chat_member.status in ("creator", "administrator")

            # Cache the result
            _cache_admin_status(chat_id, user_id, is_admin)

            if is_admin:
                return (True, None)
            else:
                return (False, "🔒 Apenas administradores do grupo podem usar este comando.")

        except Exception as e:
            logger.warning(f"Failed to check admin status for user {user_id} in chat {chat_id}: {e}")
            return (False, "⚠️ Não pude verificar as permissões. Por favor, tente novamente ou entre em contato com o administrador do bot.")

    # Other chat types (channels, etc.): default deny
    return (False, "🔒 Este comando não está disponível neste tipo de chat.")


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
        
        # Use initial state (fresh game)
        logger.info(f"Auto-started game for chat {chat_id} with initial state")
        return True, None

    except Exception as e:
        logger.error(f"Failed to auto-start game for chat {chat_id}: {e}")
        return False, "Não consegui iniciar o jogo. Tente usar o comando /start_game manualmente."


async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start_game command.

    Initializes a new game or restarts an existing one.
    Loads the initial save state and sends the first frame.
    """
    if not _check_chat_allowed(update):
        await update.message.reply_text(
            "❌ Este bot não está autorizado para este chat."
        )
        return

    # Check admin permission for group chats
    is_allowed, error_msg = await _check_admin_permission(update, context)
    if not is_allowed:
        await update.message.reply_text(error_msg)
        return

    chat_id = update.effective_chat.id
    
    await update.message.reply_text("Iniciando...")
    
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
            "❌ Não consegui iniciar o jogo. Por favor, tente novamente ou entre em contato com o administrador do bot."
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
            "❌ Este bot não está autorizado para este chat."
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
                "⏳ Um botão foi pressionado recentemente. Por favor aguarde..."
            )
            return

        # Resume game - remove old keyboard, send new message
        message_id = await handler.resume_game(chat_id)

        if message_id:
            logger.info(f"Resumed game for chat {chat_id}")
        else:
            await update.message.reply_text(
                "❌ Não consegui retomar o jogo. Tente usar o comando /start_game manualmente."
            )

    except Exception as e:
        logger.error(f"Error resuming game for chat {chat_id}: {e}")
        await update.message.reply_text(
            "❌ Não consegui retomar o jogo. Tente novamente."
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
            "❌ Este bot não está autorizado para este chat."
        )
        return

    # Check admin permission for group chats
    is_allowed, error_msg = await _check_admin_permission(update, context)
    if not is_allowed:
        await update.message.reply_text(error_msg)
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
                    f"❌ Slot inválido. Use 0-{settings.save_slots - 1}."
                )
                return
        except ValueError:
            await update.message.reply_text(
                "❌ Slot inválido, você deve utilizar um número."
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
            description=f"Salvar jogo manualmente",
            is_auto_save=False,
        )
        
        await update.message.reply_text(
            f"💾 Jogo salvo no slot {slot_number}!"
        )
        
        logger.info(f"Saved game for chat {chat_id} to slot {slot_number}")
        
    except Exception as e:
        logger.error(f"Error saving game for chat {chat_id}: {e}")
        await update.message.reply_text(
            "❌ Não consegui salvar o jogo. Tente novamente."
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
            "❌ Este bot não está autorizado para este chat."
        )
        return

    # Check admin permission for group chats
    is_allowed, error_msg = await _check_admin_permission(update, context)
    if not is_allowed:
        await update.message.reply_text(error_msg)
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
            "⏳ Um botão foi pressionado recentemente. Antes de carregar, por favor aguarde."
        )
        return
    
    # Parse slot number
    if not context.args:
        # Show available slots
        slots = state_manager.list_save_slots(chat_id, max_slots=settings.save_slots)
        
        if not slots:
            await update.message.reply_text(
                "Nenhum slot de salvamento encontrado. Use /save [slot] para criar um."
            )
            return
        
        # Show slot selection keyboard
        await update.message.reply_text(
            "Escolha um slot para carregar:",
            reply_markup=create_save_slot_keyboard(chat_id, settings.save_slots)
        )
        return
    
    try:
        slot_number = int(context.args[0])
        if slot_number < 0 or slot_number >= settings.save_slots:
            await update.message.reply_text(
                f"❌ Slot inválido. Use 0-{settings.save_slots - 1}."
            )
            return
    except ValueError:
        await update.message.reply_text(
            "❌ Slot inválido, você deve utilizar um número."
        )
        return
    
    try:
        # Load the state
        state_data = state_manager.load_from_slot(chat_id, slot_number)
        
        if state_data is None:
            await update.message.reply_text(
                f"❌ Nenhum save encontrado no slot {slot_number}."
            )
            return
        
        # Load into emulator
        controller.load_state(state_data)
        
        # Show the loaded frame
        await handler.show_current_frame(chat_id)
        
        await update.message.reply_text(
            f"📂 Carregado jogo do slot {slot_number}!"
        )
        
        logger.info(f"Loaded game for chat {chat_id} from slot {slot_number}")
        
    except Exception as e:
        logger.error(f"Error loading game for chat {chat_id}: {e}")
        await update.message.reply_text(
            "❌ Não consegui carregar o jogo. O arquivo de salvamento pode estar corrompido."
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
            "❌ Este bot não está autorizado para este chat."
        )
        return

    chat_id = update.effective_chat.id

    # Ensure game is active (auto-start if needed)
    success, error_msg = await _ensure_game_active(chat_id)
    if not success:
        await update.message.reply_text(f"❌ {error_msg}")
        return

    lines = ["📊 *Status do jogo*\n"]

    controller = game_controller_manager.get_controller(chat_id)
    lines.append("✅ Jogo ativo")

    # Check input status
    handler = get_input_handler(context.bot)
    if handler.is_input_in_progress(chat_id):
        lines.append("⏳ Input em progresso")
    else:
        lines.append("✋ Aguardando input")
        
    # Total input count
    session = handler._get_session(chat_id)
    if session and session.state.user_input_counts:
        lines.append(f"📈 Total de inputs: {sum(session.state.user_input_counts.values())}")

    # Get last input
    session = handler._get_session(chat_id)
    if session and session.state.last_input:
        lines.append(f"🎮 Input anterior: {session.state.last_input.display_name}")

    # Save slot info
    slots = state_manager.list_save_slots(chat_id, max_slots=settings.save_slots)
    if slots:
        lines.append(f"\n💾 Slots de salvamento usados: {len(slots)}/{settings.save_slots}")
        for slot in slots:
            auto_save_marker = " (auto)" if slot.is_auto_save else ""
            lines.append(f"  • Slot {slot.slot_number}{auto_save_marker}")
    else:
        lines.append("\n💾 Nenhum slot de salvamento usado")

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
            "❌ Este bot não está autorizado para este chat."
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
            caption="",
        )

        logger.info(f"Sent print frame for chat {chat_id}")

    except Exception as e:
        logger.error(f"Error printing frame for chat {chat_id}: {e}")
        await update.message.reply_text(
            "❌ Não consegui capturar a tela. Tente novamente."
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
        "❓ Comando desconhecido. Use /help para ver os comandos disponíveis."
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
