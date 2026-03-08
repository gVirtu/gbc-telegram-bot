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


async def broadcast_game_update(
    leader_chat_id: int,
    caption: str,
    media_buffer: BytesIO,
    media_type: str,
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
        media_buffer: BytesIO containing animation/photo data (seekable)
        media_type: "animation", "avif", or "photo"
        modifier_specs: List of ModifierButtonSpec for keyboard building
    """
    from src.models.game_state import ChatGameState

    mirror_ids = state_manager.get_mirror_chat_ids(leader_chat_id)
    all_targets = [leader_chat_id] + mirror_ids

    for target_id in all_targets:
        config = state_manager.get_or_create_chat_config(target_id)
        adapter = get_adapter(config.platform)
        if adapter is None:
            logger.warning(f"No adapter registered for platform '{config.platform}' (chat {target_id})")
            continue

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
