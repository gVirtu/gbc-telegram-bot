"""Command handlers for bot commands.

This module implements handlers for all bot commands:
/start_game, /current_frame, /save, /load, /status, /help

All command functions accept a CommandContext which provides platform-agnostic
access to the adapter, chat_id, user_id, user_name, and args.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Tuple

from src.adapters.base import CommandContext
from src.config import settings
from src.game import game_controller_manager
from src.handlers.input_handler import get_input_handler
from src.i18n import translation_manager, SUPPORTED_LANGUAGES
from src.keyboard import create_help_text
from src.utils.mirror_utils import broadcast_text, get_leader_chat_id
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


async def check_admin_permission(ctx: CommandContext) -> tuple[bool, str | None]:
    """Check if user has admin permission for restricted commands.

    Delegates to the platform adapter's is_admin() method.

    Args:
        ctx: CommandContext with adapter, chat_id, user_id, raw

    Returns:
        Tuple of (is_allowed: bool, error_message: str | None)
    """
    try:
        is_admin = await ctx.adapter.is_admin(ctx.chat_id, ctx.user_id, ctx.raw)
        if is_admin:
            return (True, None)
        error_msg = translation_manager.get("permissions.admin_only", ctx.chat_id)
        return (False, error_msg)
    except Exception as e:
        logger.warning(f"Failed to check admin status for user {ctx.user_id} in chat {ctx.chat_id}: {e}")
        error_msg = translation_manager.get("permissions.check_failed", ctx.chat_id)
        return (False, error_msg)


async def _ensure_game_active(
    chat_id: int, auto_load: bool = True
) -> tuple[bool, str | None]:
    """Ensure a game is active for the chat, auto-starting if needed.

    Args:
        chat_id: Platform chat ID
        auto_load: Whether to auto-load save states (default: True)

    Returns:
        Tuple of (success: bool, error_message: str | None)
    """
    controller = game_controller_manager.get_controller(chat_id)
    if controller and controller.is_initialized():
        return True, None

    try:
        controller = await game_controller_manager.get_or_create_controller(
            chat_id, auto_load=auto_load
        )
        logger.info(f"Auto-started game for chat {chat_id} with initial state")
        return True, None

    except Exception as e:
        logger.error(f"Failed to auto-start game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.start_game.auto_start_error", chat_id)
        return False, error_msg


async def start_game_command(ctx: CommandContext) -> None:
    """Handle /start_game command.

    Initializes a new game or restarts an existing one.
    Loads the initial save state and sends the first frame.
    """
    is_allowed, error_msg = await check_admin_permission(ctx)
    if not is_allowed:
        await ctx.adapter.send_text(ctx.chat_id, error_msg)
        return

    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    if leader_id != chat_id:
        await ctx.adapter.send_text(chat_id, translation_manager.get("commands.error_mirror_only_leader", chat_id))
        return

    starting_msg = translation_manager.get("commands.start_game.starting", chat_id)
    await ctx.adapter.send_text(chat_id, starting_msg)

    try:
        handler = get_input_handler()

        # Clean up any existing session
        handler.cleanup_session(chat_id)

        # Start new game
        message_id = await handler.start_game(chat_id, ctx.adapter)

        logger.info(f"Started game for chat {chat_id}, message {message_id}")

    except Exception as e:
        logger.error(f"Error starting game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.start_game.error", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)


async def resume_command(ctx: CommandContext) -> None:
    """Handle /resume command.

    Resumes the game by removing the keyboard from the old message
    and sending a new game message with the current frame.
    """
    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    success, error_msg = await _ensure_game_active(leader_id)
    if not success:
        await ctx.adapter.send_text(chat_id, f"❌ {error_msg}")
        return

    try:
        handler = get_input_handler()

        if handler.is_input_in_progress(leader_id):
            wait_msg = translation_manager.get("commands.resume.processing_wait", chat_id)
            await ctx.adapter.send_text(chat_id, wait_msg)
            return

        message_id = await handler.resume_game(chat_id, ctx.adapter)

        if message_id:
            logger.info(f"Resumed game for chat {chat_id} (leader: {leader_id})")
        else:
            error_msg = translation_manager.get("commands.resume.error_manual", chat_id)
            await ctx.adapter.send_text(chat_id, error_msg)

    except Exception as e:
        logger.error(f"Error resuming game for chat {chat_id} (leader: {leader_id}): {e}")
        error_msg = translation_manager.get("commands.resume.error", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)


async def reboot_command(ctx: CommandContext) -> None:
    """Handle /reboot command.

    Stops the current game controller and starts a fresh one
    without loading any save state. Admin only.
    """
    is_allowed, error_msg = await check_admin_permission(ctx)
    if not is_allowed:
        await ctx.adapter.send_text(ctx.chat_id, error_msg)
        return

    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    if leader_id != chat_id:
        await ctx.adapter.send_text(chat_id, translation_manager.get("commands.error_mirror_only_leader", chat_id))
        return

    try:
        handler = get_input_handler()

        if handler.is_input_in_progress(chat_id):
            wait_msg = translation_manager.get("commands.reboot.processing_wait", chat_id)
            await ctx.adapter.send_text(chat_id, wait_msg)
            return

        # Get session to remove keyboard from old message
        session = handler._get_session(chat_id)

        # Remove keyboard from old message if it exists
        if session and session.state.message_id:
            try:
                await ctx.adapter.edit_game_keyboard(chat_id, session.state.message_id, None)
            except Exception:
                pass

        # Stop existing controller gracefully
        game_controller_manager.remove_controller(chat_id)

        # Create new controller without auto-loading save states
        success, error_msg = await _ensure_game_active(chat_id, auto_load=False)
        if not success:
            await ctx.adapter.send_text(chat_id, f"❌ {error_msg}")
            return

        # Send new message with current frame
        message_id = await handler.resume_game(chat_id, ctx.adapter)

        if message_id:
            success_msg = translation_manager.get("commands.reboot.success", chat_id)
            await ctx.adapter.send_text(chat_id, success_msg)
            logger.info(f"Rebooted game for chat {chat_id}")
        else:
            error_msg = translation_manager.get("commands.reboot.error", chat_id)
            await ctx.adapter.send_text(chat_id, error_msg)

    except Exception as e:
        logger.error(f"Error rebooting game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.reboot.error", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)


async def save_command(ctx: CommandContext) -> None:
    """Handle /save command.

    Saves the current game state to a slot.
    Usage: /save [slot_number]
    """
    is_allowed, error_msg = await check_admin_permission(ctx)
    if not is_allowed:
        await ctx.adapter.send_text(ctx.chat_id, error_msg)
        return

    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    if leader_id != chat_id:
        await ctx.adapter.send_text(chat_id, translation_manager.get("commands.error_mirror_only_leader", chat_id))
        return

    success, error_msg = await _ensure_game_active(chat_id)
    if not success:
        await ctx.adapter.send_text(chat_id, f"❌ {error_msg}")
        return

    controller = game_controller_manager.get_controller(chat_id)

    slot_number: Optional[int] = None
    if ctx.args:
        try:
            slot_number = int(ctx.args[0])
            if slot_number < 0 or slot_number >= settings.save_slots:
                error_msg = translation_manager.get(
                    "commands.save.invalid_slot",
                    chat_id,
                    max_slot=settings.save_slots - 1
                )
                await ctx.adapter.send_text(chat_id, error_msg)
                return
        except ValueError:
            error_msg = translation_manager.get("commands.save.invalid_number", chat_id)
            await ctx.adapter.send_text(chat_id, error_msg)
            return

    try:
        if slot_number is None:
            existing_slots = state_manager.list_save_slots(chat_id, max_slots=settings.save_slots)
            used_slots = {s.slot_number for s in existing_slots}

            for i in range(settings.save_slots):
                if i not in used_slots:
                    slot_number = i
                    break
            else:
                slot_number = 0

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
        await broadcast_text(chat_id, success_msg)

        logger.info(f"Saved game for chat {chat_id} to slot {slot_number}")

    except Exception as e:
        logger.error(f"Error saving game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.save.error", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)


async def load_command(ctx: CommandContext) -> None:
    """Handle /load command.

    Loads a game state from a slot.
    Usage: /load [slot_number]
    """
    is_allowed, error_msg = await check_admin_permission(ctx)
    if not is_allowed:
        await ctx.adapter.send_text(ctx.chat_id, error_msg)
        return

    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    if leader_id != chat_id:
        await ctx.adapter.send_text(chat_id, translation_manager.get("commands.error_mirror_only_leader", chat_id))
        return

    success, error_msg = await _ensure_game_active(chat_id)
    if not success:
        await ctx.adapter.send_text(chat_id, f"❌ {error_msg}")
        return

    controller = game_controller_manager.get_controller(chat_id)

    handler = get_input_handler()
    if handler.is_input_in_progress(chat_id):
        wait_msg = translation_manager.get("commands.load.processing_wait", chat_id)
        await ctx.adapter.send_text(chat_id, wait_msg)
        return

    if not ctx.args:
        slots = state_manager.list_save_slots(chat_id, max_slots=settings.save_slots)

        if not slots:
            no_slots_msg = translation_manager.get("commands.load.no_slots", chat_id)
            await ctx.adapter.send_text(chat_id, no_slots_msg)
            return

        choose_msg = translation_manager.get("commands.load.choose_slot", chat_id)
        keyboard = ctx.adapter.build_save_slot_keyboard(chat_id, settings.save_slots)
        await ctx.adapter.send_text(chat_id, choose_msg)
        return

    # Check for "backup YYYYMMDD" syntax
    if ctx.args[0].lower() == "backup":
        if len(ctx.args) < 2:
            usage_msg = translation_manager.get("commands.load.backup_usage", chat_id)
            await ctx.adapter.send_text(chat_id, usage_msg)
            return
        date_str = ctx.args[1]
        try:
            datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            error_msg = translation_manager.get("commands.load.backup_invalid_date", chat_id)
            await ctx.adapter.send_text(chat_id, error_msg)
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
            await ctx.adapter.send_text(chat_id, error_msg)
            return
        controller.load_state(state_data)
        success_msg = translation_manager.get("commands.load.backup_success", chat_id, date=date_str)
        await broadcast_text(chat_id, success_msg)
        return

    try:
        slot_number = int(ctx.args[0])
        if slot_number < 0 or slot_number >= settings.save_slots:
            error_msg = translation_manager.get(
                "commands.load.invalid_slot",
                chat_id,
                max_slot=settings.save_slots - 1
            )
            await ctx.adapter.send_text(chat_id, error_msg)
            return
    except ValueError:
        error_msg = translation_manager.get("commands.load.invalid_number", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)
        return

    try:
        state_data = state_manager.load_from_slot(chat_id, slot_number)

        if state_data is None:
            error_msg = translation_manager.get("commands.load.not_found", chat_id, slot=slot_number)
            await ctx.adapter.send_text(chat_id, error_msg)
            return

        controller.load_state(state_data)

        await handler.show_current_frame(chat_id, ctx.adapter)

        success_msg = translation_manager.get("commands.load.success", chat_id, slot=slot_number)
        await broadcast_text(chat_id, success_msg)

        logger.info(f"Loaded game for chat {chat_id} from slot {slot_number}")

    except Exception as e:
        logger.error(f"Error loading game for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.load.error", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)


async def status_command(ctx: CommandContext) -> None:
    """Handle /status command."""
    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    success, error_msg = await _ensure_game_active(leader_id)
    if not success:
        await ctx.adapter.send_text(chat_id, f"❌ {error_msg}")
        return

    title = translation_manager.get("commands.status.title", chat_id)
    lines = [title]

    game_active_msg = translation_manager.get("commands.status.game_active", chat_id)
    lines.append(game_active_msg)

    handler = get_input_handler()
    if handler.is_input_in_progress(leader_id):
        in_progress_msg = translation_manager.get("commands.status.input_in_progress", chat_id)
        lines.append(in_progress_msg)
    else:
        waiting_msg = translation_manager.get("commands.status.waiting_input", chat_id)
        lines.append(waiting_msg)

    session = handler._get_session(leader_id)
    if session and session.state.user_input_counts:
        total_count = sum(session.state.user_input_counts.values())
        total_msg = translation_manager.get("commands.status.total_inputs", chat_id, count=total_count)
        lines.append(total_msg)

    if session and session.state.last_input:
        last_input_msg = translation_manager.get(
            "commands.status.last_input",
            chat_id,
            input=translation_manager.get(f'keyboard.buttons.display_name.{session.state.last_input.value}', chat_id)
        )
        lines.append(last_input_msg)

    slots = state_manager.list_save_slots(leader_id, max_slots=settings.save_slots)
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

    await ctx.adapter.send_text(chat_id, "\n".join(lines), parse_mode="Markdown")


async def print_command(ctx: CommandContext) -> None:
    """Handle /print command.

    Sends the current game frame as a new media message (current chat only).
    """
    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    success, error_msg = await _ensure_game_active(leader_id)
    if not success:
        await ctx.adapter.send_text(chat_id, f"❌ {error_msg}")
        return

    try:
        controller = game_controller_manager.get_controller(leader_id)
        png_buffer = controller.get_frame_as_png()

        await ctx.adapter.send_screenshot(chat_id, png_buffer, caption="")

        logger.info(f"Sent print frame for chat {chat_id} (leader {leader_id})")

    except Exception as e:
        logger.error(f"Error printing frame for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.print.error", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)


async def help_command(ctx: CommandContext) -> None:
    """Handle /help command."""
    chat_id = ctx.chat_id

    help_text = create_help_text(chat_id)

    await ctx.adapter.send_text(chat_id, help_text, parse_mode="Markdown")


async def gif_command(ctx: CommandContext) -> None:
    """Handle /gif command.

    Resends the most recently sent animation as a new standalone message (current chat only).
    """
    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    handler = get_input_handler()
    session = handler._get_session(leader_id)

    if not session or not session.state.last_animation_file_id:
        no_anim_msg = translation_manager.get("commands.recap.no_animation", chat_id)
        await ctx.adapter.send_text(chat_id, no_anim_msg)
        return

    try:
        await ctx.adapter.send_animation(
            chat_id=chat_id,
            animation=session.state.last_animation_file_id,
            caption="",
        )

        logger.info(f"Sent last animation for chat {chat_id} via /gif command (leader {leader_id})")

    except Exception as e:
        logger.error(f"Error sending animation for chat {chat_id}: {e}")
        error_msg = translation_manager.get("commands.recap.error", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)


async def recap_command(ctx: CommandContext) -> None:
    """Handle /recap command with optional date.

    /recap - Show today's timelapse (current chat only; uses leader's recap files)
    /recap YYYYMMDD - Show timelapse for specific date
    """
    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    if ctx.args:
        date_str = ctx.args[0]

        if len(date_str) != 8 or not date_str.isdigit():
            invalid_msg = translation_manager.get("commands.recap.invalid_date", chat_id)
            await ctx.adapter.send_text(chat_id, invalid_msg)
            return

        try:
            datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            invalid_msg = translation_manager.get("commands.recap.invalid_date", chat_id)
            await ctx.adapter.send_text(chat_id, invalid_msg)
            return
    else:
        date_str = datetime.now().strftime("%Y%m%d")

    recap_record = await state_manager.get_recap_file(leader_id, date_str)

    if recap_record is None:
        await _send_no_gameplay_message(ctx, date_str, leader_id=leader_id)
        return

    from pathlib import Path

    video_path = settings.data_dir / "recaps" / str(leader_id) / f"{date_str}.mp4"

    if not video_path.exists():
        await _send_no_gameplay_message(ctx, date_str, leader_id=leader_id)
        return

    try:
        # Try sending with cached file_id first (Telegram only - Discord always re-uploads)
        if recap_record.file_id and ctx.adapter.platform == "telegram":
            try:
                file_id = await ctx.adapter.send_video(
                    chat_id=chat_id,
                    video=recap_record.file_id,
                    caption=f"📅 Recap: {date_str}",
                )
                if file_id:
                    logger.info(f"Sent cached recap for chat {chat_id}, date {date_str}")
                    return
            except Exception as e:
                logger.warning(f"Failed to send cached file_id, uploading from disk: {e}")

        # Upload from disk
        with open(video_path, "rb") as video_file:
            new_file_id = await ctx.adapter.send_video(
                chat_id=chat_id,
                video=video_file,
                caption=f"📅 Recap: {date_str}",
            )

            if new_file_id:
                await state_manager.update_recap_file_id(leader_id, date_str, new_file_id)
                logger.info(f"Uploaded and cached recap for chat {chat_id} (leader {leader_id}), date {date_str}")

    except Exception as e:
        logger.error(f"Error sending recap for chat {chat_id}, date {date_str}: {e}")
        error_msg = translation_manager.get("commands.recap.error", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)


async def _send_no_gameplay_message(
    ctx: CommandContext,
    date: str,
    leader_id: int | None = None,
) -> None:
    """Send a message when no gameplay exists for a date."""
    chat_id = ctx.chat_id
    if leader_id is None:
        leader_id = get_leader_chat_id(chat_id)

    date_before = await state_manager.get_nearest_recap_date(leader_id, date, "before")
    date_after = await state_manager.get_nearest_recap_date(leader_id, date, "after")

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

    await ctx.adapter.send_text(chat_id, full_msg)


async def mirror_command(ctx: CommandContext) -> None:
    """Handle /mirror command.

    Configures chat mirroring. Usage:
      /mirror <leader_chat_id>  — set this chat to mirror the leader
      /mirror unset             — remove mirroring, become independent
      /mirror status            — show current mirror configuration
    """
    chat_id = ctx.chat_id

    if not ctx.args:
        usage_msg = translation_manager.get("commands.mirror.usage", chat_id)
        await ctx.adapter.send_text(chat_id, usage_msg)
        return

    arg = ctx.args[0].lower()

    if arg == "status":
        config = state_manager.load_chat_config(chat_id)
        if config and config.mirrors_chat_id is not None:
            msg = translation_manager.get(
                "commands.mirror.status_as_mirror", chat_id, leader_id=config.mirrors_chat_id
            )
        else:
            mirror_ids = state_manager.get_mirror_chat_ids(chat_id)
            if mirror_ids:
                msg = translation_manager.get(
                    "commands.mirror.status_as_leader", chat_id, mirrors=", ".join(str(m) for m in mirror_ids)
                )
            else:
                msg = translation_manager.get("commands.mirror.status_independent", chat_id)
        await ctx.adapter.send_text(chat_id, msg)
        return

    # Admin required for set/unset
    is_allowed, error_msg = await check_admin_permission(ctx)
    if not is_allowed:
        await ctx.adapter.send_text(chat_id, translation_manager.get("commands.mirror.admin_required", chat_id))
        return

    if arg == "unset":
        config = state_manager.get_or_create_chat_config(chat_id)
        config.mirrors_chat_id = None
        state_manager.save_chat_config(config)
        msg = translation_manager.get("commands.mirror.unset_success", chat_id)
        await ctx.adapter.send_text(chat_id, msg)
        logger.info(f"Removed mirroring for chat {chat_id}")
        return

    # Set mirror target
    try:
        leader_id = int(ctx.args[0])
    except ValueError:
        msg = translation_manager.get("commands.mirror.error_invalid_id", chat_id)
        await ctx.adapter.send_text(chat_id, msg)
        return

    if leader_id == chat_id:
        msg = translation_manager.get("commands.mirror.error_target_is_self", chat_id)
        await ctx.adapter.send_text(chat_id, msg)
        return

    # Validate: leader must exist
    leader_config = state_manager.load_chat_config(leader_id)
    if leader_config is None:
        msg = translation_manager.get("commands.mirror.error_leader_not_found", chat_id, leader_id=leader_id)
        await ctx.adapter.send_text(chat_id, msg)
        return

    # Validate: leader must not itself be a mirror
    if leader_config.mirrors_chat_id is not None:
        msg = translation_manager.get("commands.mirror.error_target_is_mirror", chat_id)
        await ctx.adapter.send_text(chat_id, msg)
        return

    # Validate: current chat must have no mirrors pointing to it
    current_mirrors = state_manager.get_mirror_chat_ids(chat_id)
    if current_mirrors:
        msg = translation_manager.get("commands.mirror.error_current_has_mirrors", chat_id)
        await ctx.adapter.send_text(chat_id, msg)
        return

    config = state_manager.get_or_create_chat_config(chat_id)
    config.mirrors_chat_id = leader_id
    state_manager.save_chat_config(config)

    msg = translation_manager.get("commands.mirror.set_success", chat_id, leader_id=leader_id)
    await ctx.adapter.send_text(chat_id, msg)
    logger.info(f"Chat {chat_id} now mirrors chat {leader_id}")


async def unknown_command(ctx: CommandContext) -> None:
    """Handle unknown commands."""
    chat_id = ctx.chat_id
    unknown_msg = translation_manager.get("commands.unknown", chat_id)
    await ctx.adapter.send_text(chat_id, unknown_msg)


async def message_command(ctx: CommandContext) -> None:
    """Handle /m command.

    Sets or clears the custom message base text for game messages.
    """
    is_allowed, error_msg = await check_admin_permission(ctx)
    if not is_allowed:
        await ctx.adapter.send_text(ctx.chat_id, error_msg)
        return

    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    if leader_id != chat_id:
        await ctx.adapter.send_text(chat_id, translation_manager.get("commands.error_mirror_only_leader", chat_id))
        return

    config = state_manager.get_or_create_chat_config(chat_id)

    if not ctx.args:
        config.message_base_text = None
        state_manager.save_chat_config(config)
        cleared_msg = translation_manager.get("commands.message.cleared", chat_id)
        await ctx.adapter.send_text(chat_id, cleared_msg)
        logger.info(f"Cleared custom message base text for chat {chat_id}")
        return

    custom_text = " ".join(ctx.args)

    if len(custom_text) > 240:
        error_msg = translation_manager.get("commands.message.too_long", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)
        return

    config.message_base_text = custom_text
    state_manager.save_chat_config(config)

    success_msg = translation_manager.get("commands.message.success", chat_id, text=custom_text)
    await ctx.adapter.send_text(chat_id, success_msg)
    logger.info(f"Set custom message base text for chat {chat_id}: {custom_text}")


async def language_command(ctx: CommandContext) -> None:
    """Handle /language command.

    Language is stored on the leader config; response goes to the requesting chat.
    """
    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    if not ctx.args:
        config = state_manager.get_or_create_chat_config(chat_id)
        current_lang = config.language or settings.default_language
        available_langs = ", ".join(SUPPORTED_LANGUAGES)

        current_msg = translation_manager.get("commands.language.current", chat_id, language=current_lang)
        available_msg = translation_manager.get("commands.language.available", chat_id, languages=available_langs)
        usage_msg = translation_manager.get("commands.language.usage", chat_id)

        await ctx.adapter.send_text(chat_id, f"{current_msg}\n{available_msg}\n{usage_msg}")
        return

    is_allowed, error_msg = await check_admin_permission(ctx)
    if not is_allowed:
        await ctx.adapter.send_text(chat_id, error_msg)
        return

    if leader_id != chat_id:
        await ctx.adapter.send_text(chat_id, translation_manager.get("commands.error_mirror_only_leader", chat_id))
        return

    new_lang = ctx.args[0]
    if new_lang not in SUPPORTED_LANGUAGES:
        available_langs = ", ".join(SUPPORTED_LANGUAGES)
        error_msg = translation_manager.get(
            "commands.language.invalid",
            chat_id,
            languages=available_langs
        )
        await ctx.adapter.send_text(chat_id, error_msg)
        return

    config = state_manager.get_or_create_chat_config(chat_id)
    config.language = new_lang
    state_manager.save_chat_config(config)

    translation_manager.invalidate_cache(chat_id)

    success_msg = translation_manager.get(
        "commands.language.changed",
        chat_id,
        language=new_lang
    )
    await ctx.adapter.send_text(chat_id, success_msg)

    logger.info(f"Language changed to {new_lang} for chat {chat_id}")


async def maintenance_command(ctx: CommandContext) -> None:
    """Handle /maintenance command.

    Toggles maintenance mode for the leader chat and broadcasts to all mirrors.
    """
    is_allowed, error_msg = await check_admin_permission(ctx)
    if not is_allowed:
        await ctx.adapter.send_text(ctx.chat_id, error_msg)
        return

    chat_id = ctx.chat_id
    leader_id = get_leader_chat_id(chat_id)

    if not ctx.args:
        config = state_manager.get_or_create_chat_config(chat_id)
        status_key = "commands.maintenance.enabled" if config.maintenance_mode else "commands.maintenance.disabled"
        status = translation_manager.get(status_key, chat_id)
        status_msg = translation_manager.get("commands.maintenance.status", chat_id, status=status)
        await ctx.adapter.send_text(chat_id, status_msg)
        return

    if leader_id != chat_id:
        await ctx.adapter.send_text(chat_id, translation_manager.get("commands.error_mirror_only_leader", chat_id))
        return

    arg = ctx.args[0].lower()
    if arg not in ("on", "off"):
        error_msg = translation_manager.get("commands.maintenance.invalid_arg", chat_id)
        await ctx.adapter.send_text(chat_id, error_msg)
        return

    config = state_manager.get_or_create_chat_config(chat_id)
    config.maintenance_mode = (arg == "on")
    state_manager.save_chat_config(config)

    status_key = "commands.maintenance.enabled" if config.maintenance_mode else "commands.maintenance.disabled"
    status_text = translation_manager.get(status_key, chat_id)

    message_key = "commands.maintenance.enabled_message" if config.maintenance_mode else "commands.maintenance.disabled_message"
    extra_msg = translation_manager.get(message_key, chat_id)

    changed_msg = translation_manager.get("commands.maintenance.changed", chat_id, status=status_text, message=extra_msg)
    await broadcast_text(chat_id, changed_msg)

    logger.info(f"Maintenance mode {arg} for chat {chat_id}")


# Command handlers dictionary
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
    "mirror": mirror_command,
}
