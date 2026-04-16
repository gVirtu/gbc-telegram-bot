"""Utilities for chat mirroring.

A mirror chat shares a game with a leader chat: all game updates broadcast
to the leader and all mirrors, while inputs from any mirror are proxied to
the leader's game controller.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from io import BytesIO
from itertools import chain
from typing import Callable, Optional

import numpy as np

from src.adapters.base import get_adapter
from src.game import game_controller_manager
from src.utils.state_manager import state_manager
from src.utils.frame_utils import (  # noqa: F401 (needed for test patching)
    save_frames_as_mp4,
    save_frames_as_avif,
    save_frames_as_mp4_streaming,
    save_frames_as_avif_streaming,
)
from src.utils.media_cache import save_last_animation

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
    raw_frames: list,
    tbc_frames: list,
    capture_fps: int,
    modifier_specs: list,
    animation_transform: Callable[[np.ndarray, int], np.ndarray],
) -> None:
    """Send/edit game message in leader + all mirrors.

    Encodes the needed animation formats (MP4 and/or AVIF) at most once each,
    reusing cached buffers for all targets that share the same format.

    Args:
        leader_chat_id: The leader chat ID (game state owner)
        caption: Message caption text
        raw_frames: Unscaled raw numpy frame arrays from the emulator
        tbc_frames: Pre-scaled "to be continued" numpy frame arrays
        capture_fps: Capture FPS
        modifier_specs: List of ModifierButtonSpec for keyboard building
        animation_transform: Callable ``(frame, index) -> composited_frame``
    """
    from src.models.game_state import ChatGameState

    mirror_ids = state_manager.get_mirror_chat_ids(leader_chat_id)
    all_targets = [leader_chat_id] + mirror_ids

    # 1. Pre-scan: which formats do active targets need?
    needed_formats: set[str] = set()
    for target_id in all_targets:
        if target_id != leader_chat_id and is_media_only_mirror(target_id):
            continue
        config = state_manager.get_or_create_chat_config(target_id)
        adapter = get_adapter(config.platform)
        if adapter is not None:
            needed_formats.add(adapter.preferred_animation_format)

    # 2. Encode each needed format once
    media_buffers_per_type: dict[str, Optional[BytesIO]] = {"mp4": None, "avif": None}

    if "mp4" in needed_formats and raw_frames:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_f:
                tmp_path = tmp_f.name
            frame_count = len(raw_frames) + len(tbc_frames)
            logger.info(f"MP4 encode start: chat={leader_chat_id} frames={frame_count} fps={capture_fps}")
            t0 = time.monotonic()
            await save_frames_as_mp4_streaming(
                chain(raw_frames, tbc_frames),
                animation_transform,
                tmp_path,
                fps=capture_fps,
                crf=32,
                preset="ultrafast",
            )
            elapsed = time.monotonic() - t0
            with open(tmp_path, "rb") as f:
                media_buffers_per_type["mp4"] = BytesIO(f.read())
            size_kb = media_buffers_per_type["mp4"].getbuffer().nbytes // 1024
            logger.info(f"MP4 encode done: chat={leader_chat_id} elapsed={elapsed:.2f}s size={size_kb}KB")
        except Exception as e:
            logger.error(f"MP4 encode failed for chat {leader_chat_id}: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    if "avif" in needed_formats and raw_frames:
        tmp_avif_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".avif", delete=False) as tmp_f:
                tmp_avif_path = tmp_f.name
            frame_count = len(raw_frames) + len(tbc_frames)
            logger.info(f"AVIF encode start: chat={leader_chat_id} frames={frame_count} fps={capture_fps}")
            t0 = time.monotonic()
            await save_frames_as_avif_streaming(
                chain(raw_frames, tbc_frames),
                animation_transform,
                tmp_avif_path,
                fps=capture_fps,
            )
            elapsed = time.monotonic() - t0
            with open(tmp_avif_path, "rb") as f:
                media_buffers_per_type["avif"] = BytesIO(f.read())
            size_kb = media_buffers_per_type["avif"].getbuffer().nbytes // 1024
            logger.info(f"AVIF encode done: chat={leader_chat_id} elapsed={elapsed:.2f}s size={size_kb}KB")
        except Exception as e:
            logger.error(f"AVIF encode failed for chat {leader_chat_id}: {e}")
        finally:
            if tmp_avif_path and os.path.exists(tmp_avif_path):
                os.remove(tmp_avif_path)

    # 3. Broadcast loop
    for target_id in all_targets:
        if target_id != leader_chat_id and is_media_only_mirror(target_id):
            logger.debug(f"Skipping media-only mirror {target_id} in broadcast_game_update")
            continue
        config = state_manager.get_or_create_chat_config(target_id)
        adapter = get_adapter(config.platform)
        if adapter is None:
            logger.warning(f"No adapter registered for platform '{config.platform}' (chat {target_id})")
            continue

        anim_format = adapter.preferred_animation_format
        media_buffer = media_buffers_per_type.get(anim_format)
        media_type = anim_format
        if media_buffer is None:
            logger.warning(f"No encoded buffer for format {anim_format!r}, skipping {target_id}")
            continue
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
                
    # All broadcasted media types are saved to the leader chat cache
    for media_type, media_buffer in media_buffers_per_type.items():
        if media_buffer is None:
            continue
        save_last_animation(leader_chat_id, media_buffer, media_type)


async def broadcast_text(leader_chat_id: int, text: str) -> None:
    """Send a text message to the leader and all its mirrors.

    Args:
        leader_chat_id: The leader chat ID
        text: Message text to broadcast
    """
    mirror_ids = state_manager.get_mirror_chat_ids(leader_chat_id)
    all_targets = [leader_chat_id] + mirror_ids

    for target_id in all_targets:
        if target_id != leader_chat_id and is_media_only_mirror(target_id):
            logger.debug(f"Skipping media-only mirror {target_id} in broadcast_text")
            continue
        config = state_manager.get_or_create_chat_config(target_id)
        adapter = get_adapter(config.platform)
        if adapter is None:
            logger.warning(f"No adapter registered for platform '{config.platform}' (chat {target_id})")
            continue
        try:
            await adapter.send_text(target_id, text)
        except Exception as e:
            logger.error(f"Failed to broadcast text to chat {target_id}: {e}")
