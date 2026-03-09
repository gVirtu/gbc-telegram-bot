"""Utilities for chat mirroring.

A mirror chat shares a game with a leader chat: all game updates broadcast
to the leader and all mirrors, while inputs from any mirror are proxied to
the leader's game controller.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

from src.adapters.base import get_adapter
from src.game import game_controller_manager
from src.utils.state_manager import state_manager
from src.utils.frame_utils import (  # noqa: F401 (needed for test patching)
    save_frames_as_mp4,
    save_frames_as_avif
)

logger = logging.getLogger(__name__)


def get_leader_chat_id(chat_id: int) -> int:
    """Return the leader chat ID for a given chat.

    If the chat is configured as a mirror, returns its mirrors_chat_id.
    Otherwise returns chat_id itself.

    Args:
        chat_id: The originating chat ID

    Returns:
        Leader chat ID (mirrors_chat_id if set, else chat_id)
    """
    config = state_manager.load_chat_config(chat_id)
    if config and config.mirrors_chat_id is not None:
        return config.mirrors_chat_id
    return chat_id


def is_media_only_mirror(chat_id: int) -> bool:
    """Return True if this chat is a mirror with media_only_mirror flag enabled.

    A media-only mirror never receives game frame broadcasts, text broadcasts,
    button inputs, or /resume. It may still use /print, /gif, /recap, /status.
    Has no effect on leader chats.

    Args:
        chat_id: The chat ID to check

    Returns:
        True if the chat is a mirror with media_only_mirror feature flag set
    """
    config = state_manager.load_chat_config(chat_id)
    if config is None:
        return False
    if config.mirrors_chat_id is None:
        return False
    return bool(config.feature_flags.get("media_only_mirror", False))


async def broadcast_game_update(
    leader_chat_id: int,
    caption: str,
    frames: list,
    capture_fps: int,
    modifier_specs: list,
) -> None:
    """Send/edit game message in leader + all mirrors.

    For each target chat:
    - If the chat already has a message_id, edits that message with the new
      animation/photo.
    - If the chat has no message_id yet (first broadcast), sends a new message
      seeded with the current game frame.

    Args:
        leader_chat_id: The leader chat ID (game state owner)
        caption: Message caption text
        frames: List of game frames
        capture_fps: Capture FPS
        modifier_specs: List of ModifierButtonSpec for keyboard building
    """
    from src.models.game_state import ChatGameState

    mirror_ids = state_manager.get_mirror_chat_ids(leader_chat_id)
    all_targets = [leader_chat_id] + mirror_ids
    media_buffers_per_type = {
        "animation": None,
        "avif": None
    }

    for target_id in all_targets:
        config = state_manager.get_or_create_chat_config(target_id)
        adapter = get_adapter(config.platform)
        if adapter is None:
            logger.warning(f"No adapter registered for platform '{config.platform}' (chat {target_id})")
            continue
        
        anim_format = adapter.preferred_animation_format
        
        if anim_format == "avif":
            media_buffer = media_buffers_per_type["avif"] or save_frames_as_avif(frames, fps=capture_fps)
            media_type = "avif"
        else:
            media_buffer = media_buffers_per_type["animation"] or save_frames_as_mp4(frames, fps=capture_fps)
            media_type = "animation"
        media_buffer.seek(0)

        logger.info(f"Broadcasting game update to chat {target_id} on platform {config.platform}")

        state = state_manager.load_game_state(target_id)
        keyboard = adapter.build_game_keyboard(chat_config=config, modifier_specs=modifier_specs)
        sent = False

        if state and state.message_id:
            try:
                media_buffer.seek(0)
                file_id = await adapter.edit_game_message(
                    target_id, state.message_id, caption, keyboard, media_buffer, media_type=media_type
                )
                if file_id and state:
                    state.last_animation_file_id = file_id
                    state_manager.save_game_state(state)
                sent = True
            except Exception as e:
                logger.error(f"Failed to broadcast game update to chat {target_id}: {e}")

        if not sent:
            # Seed initial message with current frame
            try:
                media_buffer.seek(0)
                new_msg_id = await adapter.send_game_message(target_id, caption, keyboard, media_buffer, media_type=media_type)
                new_state = state_manager.load_game_state(target_id) or ChatGameState(chat_id=target_id)
                new_state.message_id = new_msg_id
                state_manager.save_game_state(new_state)
                sent = True
            except Exception as e:
                logger.error(f"Failed to seed initial game message to chat {target_id}: {e}")


async def broadcast_text(leader_chat_id: int, text: str) -> None:
    """Send a text message to the leader and all its mirrors.

    Args:
        leader_chat_id: The leader chat ID
        text: Message text to broadcast
    """
    mirror_ids = state_manager.get_mirror_chat_ids(leader_chat_id)
    all_targets = [leader_chat_id] + mirror_ids

    for target_id in all_targets:
        config = state_manager.get_or_create_chat_config(target_id)
        adapter = get_adapter(config.platform)
        if adapter is None:
            logger.warning(f"No adapter registered for platform '{config.platform}' (chat {target_id})")
            continue
        try:
            await adapter.send_text(target_id, text)
        except Exception as e:
            logger.error(f"Failed to broadcast text to chat {target_id}: {e}")
