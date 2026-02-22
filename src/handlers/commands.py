"""Command handlers for Telegram bot commands.

This module implements handlers for all bot commands:
/start_game, /current_frame, /save, /load, /status, /help
"""

import logging
from datetime import datetime
from time import time
from typing import Optional, Dict, Tuple

from telegram import Update
from telegram.ext import ContextTypes

from src.config import settings
from src.game import game_controller_manager
from src.handlers.input_handler import get_input_handler
from src.i18n import translation_manager, SUPPORTED_LANGUAGES
from src.keyboard import (
    create_help_text,
    create_save_slot_keyboard,
)
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)

# Lazy singleton for BackupManager (stateless, but avoids repeated construction)
_backup_manager = None


def _get_backup_manager():
    global _backup_manager
    if _backup_manager is None:
        from src.utils.backup_manager import BackupManager
        _backup_manager = BackupManager(state_manager, game_controller_manager, settings)
    return _backup_manager

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


async def check_admin_permission(
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
                    error_msg = translation_manager.get("permissions.admin_only", chat_id)
                    return (False, error_msg)

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
                return (False, translation_manager.get("permissions.admin_only", chat_id))

        except Exception as e:
            logger.warning(f"Failed to check admin status for user {user_id} in chat {chat_id}: {e}")
            error_msg = translation_manager.get("permissions.check_failed", chat_id)
            return (False, error_msg)

    # Other chat types (channels, etc.): default deny
    error_msg = translation_manager.get("permissions.unsupported_chat", chat_id)
    return (False, error_msg)


async def _ensure_game_active(
    chat_id: int, auto_load: bool = True
) -> tuple[bool, str | None]:
    """Ensure a game is active for the chat, auto-starting if needed.

    If no game is active, this function will:
    1. Initialize the game controller
    2. Try to load save slot 1 if it exists (unless auto_load=False)
    3. Fall back to initial state if slot 1 doesn't exist or fails

    Args:
        chat_id: Telegram chat ID
        auto_load: Whether to auto-load save states (default: True)

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
        controller = await game_controller_manager.get_or_create_controller(
            chat_id, auto_load=auto_load
        )

        # Use initial state (fresh game)
        logger.info(f"Auto-started game for chat {chat_id} with initial state")
        return True, None

    except Exception as e:
        logger.error(f"Failed to auto-start game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.start_game.auto_start_error", chat_id)
        return False, error_msg


async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start_game command.

    Initializes a new game or restarts an existing one.
    Loads the initial save state and sends the first frame.
    """
    # Check admin permission for group chats
    is_allowed, error_msg = await check_admin_permission(update, context)
    if not is_allowed:
        await update.message.reply_text(error_msg)
        return

    chat_id = update.effective_chat.id

    starting_msg = translation_manager.get("commands.start_game.starting", chat_id)
    await update.message.reply_text(starting_msg)

    try:
        handler = get_input_handler(context.bot)

        # Clean up any existing session
        handler.cleanup_session(chat_id)

        # Start new game
        message_id = await handler.start_game(chat_id)

        logger.info(f"Started game for chat {chat_id}, message {message_id}")

    except Exception as e:
        logger.error(f"Error starting game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.start_game.error", chat_id)
        await update.message.reply_text(error_msg)


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume command.

    Resumes the game by removing the keyboard from the old message
    and sending a new game message with the current frame.
    Unlike /start_game, this does not restart the game.
    Auto-starts the game if not already active.
    """
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
            wait_msg = translation_manager.get("commands.resume.processing_wait", chat_id)
            await update.message.reply_text(wait_msg)
            return

        # Resume game - remove old keyboard, send new message
        message_id = await handler.resume_game(chat_id)

        if message_id:
            logger.info(f"Resumed game for chat {chat_id}")
        else:
            error_msg = translation_manager.get("commands.resume.error_manual", chat_id)
            await update.message.reply_text(error_msg)

    except Exception as e:
        logger.error(f"Error resuming game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.resume.error", chat_id)
        await update.message.reply_text(error_msg)


async def reboot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reboot command.

    Stops the current game controller and starts a fresh one
    without loading any save state. Admin only.
    """
    # Check admin permission for group chats
    is_allowed, error_msg = await check_admin_permission(update, context)
    if not is_allowed:
        await update.message.reply_text(error_msg)
        return

    chat_id = update.effective_chat.id

    try:
        handler = get_input_handler(context.bot)

        # Check if input is in progress
        if handler.is_input_in_progress(chat_id):
            wait_msg = translation_manager.get("commands.reboot.processing_wait", chat_id)
            await update.message.reply_text(wait_msg)
            return

        # Get session to remove keyboard from old message
        session = handler._get_session(chat_id)

        # Remove keyboard from old message if it exists
        if session and session.state.message_id:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=session.state.message_id,
                    reply_markup=None,
                )
            except Exception:
                # Old message might be deleted or inaccessible, continue anyway
                pass

        # Stop existing controller gracefully
        game_controller_manager.remove_controller(chat_id)

        # Create new controller without auto-loading save states
        success, error_msg = await _ensure_game_active(chat_id, auto_load=False)
        if not success:
            await update.message.reply_text(f"❌ {error_msg}")
            return

        # Send new message with current frame
        message_id = await handler.resume_game(chat_id)

        if message_id:
            success_msg = translation_manager.get("commands.reboot.success", chat_id)
            await update.message.reply_text(success_msg)
            logger.info(f"Rebooted game for chat {chat_id}")
        else:
            error_msg = translation_manager.get("commands.reboot.error", chat_id)
            await update.message.reply_text(error_msg)

    except Exception as e:
        logger.error(f"Error rebooting game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.reboot.error", chat_id)
        await update.message.reply_text(error_msg)


async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /save command.

    Saves the current game state to a slot.
    Usage: /save [slot_number]
    If no slot specified, uses the next available slot.
    Auto-starts the game if not already active.
    """
    # Check admin permission for group chats
    is_allowed, error_msg = await check_admin_permission(update, context)
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
                error_msg = translation_manager.get(
                    "commands.save.invalid_slot",
                    chat_id,
                    max_slot=settings.save_slots - 1
                )
                await update.message.reply_text(error_msg)
                return
        except ValueError:
            error_msg = translation_manager.get("commands.save.invalid_number", chat_id)
            await update.message.reply_text(error_msg)
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
        state_manager.save_to_slot(
            chat_id=chat_id,
            slot_number=slot_number,
            state_data=state_data,
            description="Salvar jogo manualmente",
            is_auto_save=False,
        )

        success_msg = translation_manager.get(
            "commands.save.success",
            chat_id,
            slot=slot_number
        )
        await update.message.reply_text(success_msg)

        logger.info(f"Saved game for chat {chat_id} to slot {slot_number}")

    except Exception as e:
        logger.error(f"Error saving game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.save.error", chat_id)
        await update.message.reply_text(error_msg)


async def load_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /load command.

    Loads a game state from a slot.
    Usage: /load [slot_number]
    If no slot specified, shows available slots.
    Auto-starts the game if not already active.
    """
    # Check admin permission for group chats
    is_allowed, error_msg = await check_admin_permission(update, context)
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
        wait_msg = translation_manager.get("commands.load.processing_wait", chat_id)
        await update.message.reply_text(wait_msg)
        return

    # Parse slot number
    if not context.args:
        # Show available slots
        slots = state_manager.list_save_slots(chat_id, max_slots=settings.save_slots)

        if not slots:
            no_slots_msg = translation_manager.get("commands.load.no_slots", chat_id)
            await update.message.reply_text(no_slots_msg)
            return

        # Show slot selection keyboard
        choose_msg = translation_manager.get("commands.load.choose_slot", chat_id)
        await update.message.reply_text(
            choose_msg,
            reply_markup=create_save_slot_keyboard(chat_id, settings.save_slots)
        )
        return
    
    # Check for "backup YYYYMMDD" syntax
    if context.args[0].lower() == "backup":
        if len(context.args) < 2:
            usage_msg = translation_manager.get("commands.load.backup_usage", chat_id)
            await update.message.reply_text(usage_msg)
            return
        date_str = context.args[1]
        try:
            datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            error_msg = translation_manager.get("commands.load.backup_invalid_date", chat_id)
            await update.message.reply_text(error_msg)
            return
        backup_mgr = _get_backup_manager()
        state_data = backup_mgr.load_backup(chat_id, date_str)
        if state_data is None:
            available = backup_mgr.list_backups(chat_id)
            avail_str = ", ".join(available) if available else translation_manager.get("commands.load.backup_none_available", chat_id)
            error_msg = translation_manager.get(
                "commands.load.backup_not_found",
                chat_id,
                date=date_str,
                available=avail_str
            )
            await update.message.reply_text(error_msg)
            return
        controller.load_state(state_data)
        success_msg = translation_manager.get("commands.load.backup_success", chat_id, date=date_str)
        await update.message.reply_text(success_msg)
        return

    try:
        slot_number = int(context.args[0])
        if slot_number < 0 or slot_number >= settings.save_slots:
            error_msg = translation_manager.get(
                "commands.load.invalid_slot",
                chat_id,
                max_slot=settings.save_slots - 1
            )
            await update.message.reply_text(error_msg)
            return
    except ValueError:
        error_msg = translation_manager.get("commands.load.invalid_number", chat_id)
        await update.message.reply_text(error_msg)
        return

    try:
        # Load the state
        state_data = state_manager.load_from_slot(chat_id, slot_number)

        if state_data is None:
            error_msg = translation_manager.get("commands.load.not_found", chat_id, slot=slot_number)
            await update.message.reply_text(error_msg)
            return

        # Load into emulator
        controller.load_state(state_data)

        # Show the loaded frame
        await handler.show_current_frame(chat_id)

        success_msg = translation_manager.get("commands.load.success", chat_id, slot=slot_number)
        await update.message.reply_text(success_msg)

        logger.info(f"Loaded game for chat {chat_id} from slot {slot_number}")

    except Exception as e:
        logger.error(f"Error loading game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.load.error", chat_id)
        await update.message.reply_text(error_msg)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command.

    Shows the current game status including:
    - Whether a game is active
    - Current input status
    - Save slot information
    Auto-starts the game if not already active.
    """
    chat_id = update.effective_chat.id

    # Ensure game is active (auto-start if needed)
    success, error_msg = await _ensure_game_active(chat_id)
    if not success:
        await update.message.reply_text(f"❌ {error_msg}")
        return

    title = translation_manager.get("commands.status.title", chat_id)
    lines = [title]

    game_active_msg = translation_manager.get("commands.status.game_active", chat_id)
    lines.append(game_active_msg)

    # Check input status
    handler = get_input_handler(context.bot)
    if handler.is_input_in_progress(chat_id):
        in_progress_msg = translation_manager.get("commands.status.input_in_progress", chat_id)
        lines.append(in_progress_msg)
    else:
        waiting_msg = translation_manager.get("commands.status.waiting_input", chat_id)
        lines.append(waiting_msg)

    # Total input count
    session = handler._get_session(chat_id)
    if session and session.state.user_input_counts:
        total_count = sum(session.state.user_input_counts.values())
        total_msg = translation_manager.get("commands.status.total_inputs", chat_id, count=total_count)
        lines.append(total_msg)

    # Get last input
    session = handler._get_session(chat_id)
    if session and session.state.last_input:
        last_input_msg = translation_manager.get(
            "commands.status.last_input",
            chat_id,
            input=translation_manager.get(f'keyboard.buttons.display_name.{session.state.last_input.value}', chat_id)
        )
        lines.append(last_input_msg)

    # Save slot info
    slots = state_manager.list_save_slots(chat_id, max_slots=settings.save_slots)
    if slots:
        slots_msg = translation_manager.get(
            "commands.status.slots_used",
            chat_id,
            used=len(slots),
            total=settings.save_slots
        )
        lines.append(slots_msg)
        for slot in slots:
            marker = translation_manager.get("commands.status.auto_save_marker", chat_id) if slot.is_auto_save else ""
            slot_entry = translation_manager.get(
                "commands.status.slot_entry",
                chat_id,
                slot=slot.slot_number,
                marker=marker
            )
            lines.append(slot_entry)
    else:
        no_slots_msg = translation_manager.get("commands.status.no_slots", chat_id)
        lines.append(no_slots_msg)

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
        error_msg = translation_manager.get("commands.print.error", chat_id)
        await update.message.reply_text(error_msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command.
    
    Shows help information including button descriptions and available commands.
    """
    chat_id = update.effective_chat.id

    help_text = create_help_text(chat_id)
    
    await update.message.reply_text(
        help_text,
        parse_mode="Markdown",
    )


async def gif_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /gif command.

    Resends the most recently sent animation as a new standalone message
    (no caption) in the chat. Any group member can use this command.
    """
    chat_id = update.effective_chat.id

    handler = get_input_handler(context.bot)
    session = handler._get_session(chat_id)

    if not session or not session.state.last_animation_file_id:
        no_anim_msg = translation_manager.get("commands.recap.no_animation", chat_id)
        await update.message.reply_text(no_anim_msg)
        return

    try:
        await context.bot.send_animation(
            chat_id=chat_id,
            animation=session.state.last_animation_file_id,
            caption="",
        )

        logger.info(f"Sent last animation for chat {chat_id} via /gif command")

    except Exception as e:
        logger.error(f"Error sending animation for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.recap.error", chat_id)
        await update.message.reply_text(error_msg)
        return

async def recap_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /recap command with optional date.

    /recap - Show today's timelapse
    /recap YYYYMMDD - Show timelapse for specific date

    Sends a daily timelapse video of all gameplay from the specified date.
    """
    chat_id = update.effective_chat.id

    # Parse date from args (default to today)
    from datetime import datetime

    if context.args:
        date_str = context.args[0]

        # Validate YYYYMMDD format
        if len(date_str) != 8 or not date_str.isdigit():
            invalid_msg = translation_manager.get("commands.recap.invalid_date", chat_id)
            await update.message.reply_text(invalid_msg)
            return

        try:
            # Validate date is valid
            datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            invalid_msg = translation_manager.get("commands.recap.invalid_date", chat_id)
            await update.message.reply_text(invalid_msg)
            return
    else:
        # Default to today
        date_str = datetime.now().strftime("%Y%m%d")

    # Query database for recap file
    recap_record = await state_manager.get_recap_file(chat_id, date_str)

    if recap_record is None:
        # No gameplay recorded for this date
        await _send_no_gameplay_message(update, context, chat_id, date_str)
        return

    # Get video path
    from pathlib import Path
    from src.config import settings

    video_path = settings.data_dir / "recaps" / str(chat_id) / f"{date_str}.mp4"

    if not video_path.exists():
        # File deleted but metadata exists
        await _send_no_gameplay_message(update, context, chat_id, date_str)
        return

    try:
        # Try sending with cached file_id first
        if recap_record.file_id:
            try:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=recap_record.file_id,
                    caption=f"📅 Recap: {date_str}",
                )
                logger.info(f"Sent cached recap for chat {chat_id}, date {date_str}")
                return
            except Exception as e:
                logger.warning(f"Failed to send cached file_id, uploading from disk: {e}")

        # Upload from disk
        with open(video_path, "rb") as video_file:
            message = await context.bot.send_video(
                chat_id=chat_id,
                video=video_file,
                caption=f"📅 Recap: {date_str}",
            )

            # Update file_id in database
            if message.video:
                await state_manager.update_recap_file_id(chat_id, date_str, message.video.file_id)
                logger.info(f"Uploaded and cached recap for chat {chat_id}, date {date_str}")

    except Exception as e:
        logger.error(f"Error sending recap for chat {chat_id}, date {date_str}: {e}")
        error_msg = translation_manager.get("commands.recap.error", chat_id)
        await update.message.reply_text(error_msg)


async def _send_no_gameplay_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    date: str,
) -> None:
    """Send a message when no gameplay exists for a date.

    Args:
        update: Telegram update
        context: Telegram context
        chat_id: Chat ID
        date: Date in YYYYMMDD format
    """
    # Get nearest dates
    date_before = await state_manager.get_nearest_recap_date(chat_id, date, "before")
    date_after = await state_manager.get_nearest_recap_date(chat_id, date, "after")

    # Build suggestions
    suggestions = []
    if date_before:
        suggestions.append(f"← {date_before}")
    if date_after:
        suggestions.append(f"{date_after} →")

    no_gameplay_msg = translation_manager.get("commands.recap.no_gameplay", chat_id, date=date)

    if suggestions:
        try_dates_msg = translation_manager.get("commands.recap.try_dates", chat_id, dates=" | ".join(suggestions))
        full_msg = f"{no_gameplay_msg}\n{try_dates_msg}"
    else:
        full_msg = no_gameplay_msg

    await update.message.reply_text(full_msg)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown commands."""
    chat_id = update.effective_chat.id
    unknown_msg = translation_manager.get("commands.unknown", chat_id)
    await update.message.reply_text(unknown_msg)


async def message_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /m command.

    Sets or clears the custom message base text for game messages.
    Usage: /m [TEXT]
    Without TEXT, clears the custom message and reverts to default "Sua vez!"
    With TEXT, sets the custom message base text.
    Only admins can use this command.
    """

    # Check admin permission for group chats
    is_allowed, error_msg = await check_admin_permission(update, context)
    if not is_allowed:
        await update.message.reply_text(error_msg)
        return

    chat_id = update.effective_chat.id
    
    # Get or create config
    config = state_manager.get_or_create_chat_config(chat_id)
    
    # Check if TEXT was provided
    if not context.args:
        # Clear custom message (set to None)
        config.message_base_text = None
        state_manager.save_chat_config(config)
        cleared_msg = translation_manager.get("commands.message.cleared", chat_id)
        await update.message.reply_text(cleared_msg)
        logger.info(f"Cleared custom message base text for chat {chat_id}")
        return

    # Join args to form the custom text
    custom_text = " ".join(context.args)

    # Validate text length
    if len(custom_text) > 240:
        error_msg = translation_manager.get("commands.message.too_long", chat_id)
        await update.message.reply_text(error_msg)
        return

    # Save custom text
    config.message_base_text = custom_text
    state_manager.save_chat_config(config)

    success_msg = translation_manager.get("commands.message.success", chat_id, text=custom_text)
    await update.message.reply_text(success_msg)
    logger.info(f"Set custom message base text for chat {chat_id}: {custom_text}")


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /language command.

    Changes the language for the chat.
    Usage: /language [code]
    Without code, shows current language and available options.
    With code, changes the language (admin only).
    """

    chat_id = update.effective_chat.id

    # Parse argument
    if not context.args:
        # Show current language and available options
        config = state_manager.get_or_create_chat_config(chat_id)
        current_lang = config.language or settings.default_language
        available_langs = ", ".join(SUPPORTED_LANGUAGES)

        # Get message in current language
        current_msg = translation_manager.get("commands.language.current", chat_id, language=current_lang)
        available_msg = translation_manager.get("commands.language.available", chat_id, languages=available_langs)
        usage_msg = translation_manager.get("commands.language.usage", chat_id)

        await update.message.reply_text(
            f"{current_msg}\n{available_msg}\n{usage_msg}"
        )
        return

    # Check admin permission for changing language
    is_allowed, error_msg = await check_admin_permission(update, context)
    if not is_allowed:
        await update.message.reply_text(error_msg)
        return

    # Validate language code
    new_lang = context.args[0]
    if new_lang not in SUPPORTED_LANGUAGES:
        available_langs = ", ".join(SUPPORTED_LANGUAGES)
        error_msg = translation_manager.get(
            "commands.language.invalid",
            chat_id,
            languages=available_langs
        )
        await update.message.reply_text(error_msg)
        return

    # Update config
    config = state_manager.get_or_create_chat_config(chat_id)
    config.language = new_lang
    state_manager.save_chat_config(config)

    # Invalidate translation cache
    translation_manager.invalidate_cache(chat_id)

    # Confirm in NEW language
    success_msg = translation_manager.get(
        "commands.language.changed",
        chat_id,
        language=new_lang
    )
    await update.message.reply_text(success_msg)

    logger.info(f"Language changed to {new_lang} for chat {chat_id}")


async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /maintenance command.

    Toggles maintenance mode for the chat. When enabled, only admins
    can send input button commands.
    Usage: /maintenance on|off
    """

    # Check admin permission for group chats
    is_allowed, error_msg = await check_admin_permission(update, context)
    if not is_allowed:
        await update.message.reply_text(error_msg)
        return

    chat_id = update.effective_chat.id

    # Parse argument
    if not context.args:
        # Show current status
        config = state_manager.get_or_create_chat_config(chat_id)
        status_key = "commands.maintenance.enabled" if config.maintenance_mode else "commands.maintenance.disabled"
        status = translation_manager.get(status_key, chat_id)
        status_msg = translation_manager.get("commands.maintenance.status", chat_id, status=status)
        await update.message.reply_text(status_msg)
        return

    arg = context.args[0].lower()
    if arg not in ("on", "off"):
        error_msg = translation_manager.get("commands.maintenance.invalid_arg", chat_id)
        await update.message.reply_text(error_msg)
        return

    # Toggle maintenance mode
    config = state_manager.get_or_create_chat_config(chat_id)
    config.maintenance_mode = (arg == "on")
    state_manager.save_chat_config(config)

    status_key = "commands.maintenance.enabled" if config.maintenance_mode else "commands.maintenance.disabled"
    status_text = translation_manager.get(status_key, chat_id)

    message_key = "commands.maintenance.enabled_message" if config.maintenance_mode else "commands.maintenance.disabled_message"
    extra_msg = translation_manager.get(message_key, chat_id)

    changed_msg = translation_manager.get("commands.maintenance.changed", chat_id, status=status_text, message=extra_msg)
    await update.message.reply_text(changed_msg)

    logger.info(f"Maintenance mode {arg} for chat {chat_id}")


# Command handlers dictionary for easy registration
COMMAND_HANDLERS = {
    "start_game": start_game_command,
    "resume": resume_command,
    "reboot": reboot_command,
    "print": print_command,
    "save": save_command,
    "load": load_command,
    "status": status_command,
    "help": help_command,
    "gif": gif_command,
    "recap": recap_command,
    "m": message_command,
    "language": language_command,
    "maintenance": maintenance_command,
}
