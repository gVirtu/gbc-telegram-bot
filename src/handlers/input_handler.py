"""Input handler for managing game interactions.

This module handles button presses, input processing, and game flow using a
time-based buffer: inputs are collected for input_buffer_seconds (or until
maximum_inputs_per_animation buttons accumulate), then drained as a single
multi-user batch animation.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

# from src.utils import mem_trace

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
from src.models.input_queue import BufferedInput, PendingBuffer
from src.utils.frame_utils import (  # noqa: F401 (needed for test patching)
    _make_frame_transform,
    _make_reaction_frame_transform,
    apply_overlay_composite,
    apply_reaction_overlay,
    build_timelapse_transform,
    generate_tbc_frames,
    hex_to_rgb,
    render_status_bar,
)
from src.utils.mirror_utils import broadcast_game_update, get_leader_chat_id, is_media_only_mirror
from src.utils.priority_gate import mark_busy, mark_idle
from src.utils.scoring_manager import scoring_manager
from src.utils.state_manager import state_manager

logger = logging.getLogger(__name__)

AVATAR_UPDATE_INTERVAL = timedelta(hours=1)


def _should_update_avatar(config) -> bool:
    """Return True if the avatar cooldown has passed."""
    if config.last_avatar_update_at is None:
        return True
    return datetime.utcnow() - config.last_avatar_update_at >= AVATAR_UPDATE_INTERVAL


def _save_raw_frames_sync(
    frames: list,
    folder: Path,
    audio_chunks=None,
) -> None:
    """Write raw numpy frames and optional audio to disk (blocking, run in executor).

    Creates ``folder`` if needed, then writes ``frame_000000.npy``, …,
    ``frame_N.npy`` and, if ``audio_chunks`` is provided, ``audio.npz``.

    Args:
        frames: List of raw (unscaled) numpy arrays from ``controller.end_capture()``.
        folder: Destination directory path.
        audio_chunks: Optional list of int8 stereo audio ndarrays.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for i, frame in enumerate(frames):
        np.save(str(folder / f"frame_{i:06d}.npy"), frame)
    if audio_chunks:
        np.savez(str(folder / "audio.npz"), *audio_chunks)


class InputHandlerError(Exception):
    """Base exception for input handler errors."""
    pass


def _build_recent_inputs_grouped(
    pre_existing: list,
    new_inputs_with_offsets: list,
    group_limit: int = 3,
) -> list:
    """Build grouped recent-inputs list in memory, avoiding a DB reload.

    Replicates the grouping logic of StateManager._load_recent_inputs:
    consecutive inputs from the same user are collapsed into one group.

    Args:
        pre_existing: rows from get_recent_inputs_for_overlay (oldest-first dicts)
        new_inputs_with_offsets: list of (input_dict, frame_offset) from the current batch
        group_limit: maximum number of groups to return (tail of list)
    """
    all_rows = list(pre_existing) + [inp for inp, _ in new_inputs_with_offsets]
    groups: list = []
    for row in all_rows:
        if groups and groups[-1]["user_id"] == row["user_id"]:
            groups[-1]["buttons"].append(row["button"])
        else:
            groups.append({
                "user_id": row["user_id"],
                "user_name": row["user_name"],
                "buttons": [row["button"]] if row.get("button") else [],
                "timestamp": row.get("timestamp", ""),
            })
    return groups[-group_limit:] if len(groups) > group_limit else groups


class InputHandler:
    """Handles game input processing with buffered queue system.

    Inputs are collected in a PendingBuffer per chat. A debounce timer fires
    after input_buffer_seconds of inactivity (or immediately when the buffer
    hits maximum_inputs_per_animation), signalling the processing loop to drain
    and animate a batch. A minimum gap of min_update_interval_seconds is
    enforced between message edits to avoid Telegram rate limits.
    """

    def __init__(self):
        """Initialize the input handler."""
        self._sessions: dict[int, GameSession] = {}
        self._processing: set[int] = set()
        self._pending_buffers: dict[int, PendingBuffer] = {}
        self._buffer_tasks: dict[int, asyncio.Task] = {}
        self._drain_events: dict[int, asyncio.Event] = {}

    # ==================== Session helpers ====================

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

    # ==================== Buffer helpers ====================

    def _get_or_create_buffer(self, chat_id: int) -> PendingBuffer:
        """Get or create the pending buffer for a chat."""
        if chat_id not in self._pending_buffers:
            self._pending_buffers[chat_id] = PendingBuffer(max_size=settings.max_queue_size)
        return self._pending_buffers[chat_id]

    def _get_or_create_drain_event(self, chat_id: int) -> asyncio.Event:
        """Get or create the drain event for a chat."""
        if chat_id not in self._drain_events:
            self._drain_events[chat_id] = asyncio.Event()
        return self._drain_events[chat_id]

    async def _run_buffer_timer(self, chat_id: int) -> None:
        """Sleep for input_buffer_seconds then signal the drain event."""
        await asyncio.sleep(settings.input_buffer_seconds)
        event = self._drain_events.get(chat_id)
        if event is not None:
            event.set()

    # ==================== Misc helpers ====================

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
        """Look up the platform adapter for a given chat."""
        from src.adapters.base import get_adapter
        config = state_manager.load_chat_config(chat_id)
        platform = config.platform if config else "telegram"
        return get_adapter(platform)

    def _tick_and_capture_animation_frames(
        self,
        controller,
        animation_frames: int,
        hook_context: dict,
        game_fps: int,
    ) -> int:
        """Tick the game controller for animation frames (capture handled by controller).

        Returns:
            Number of frames actually ticked.
        """
        wait_call_threshold = hook_context.get("inputWaitCalls", {}).get("_total", 0) + game_fps
        count = 0

        for _frame_num in range(animation_frames):
            controller.tick(1)
            count += 1
            if hook_context.get("inputWaitCalls", {}).get("_total", 0) > wait_call_threshold:
                input_wait_calls = hook_context.get("inputWaitCalls", {})
                relevant_wait_calls = {k: v for k, v in input_wait_calls.items() if v > 0}
                logger.debug(f"Input wait loop detected, finishing animation early ({relevant_wait_calls})")
                break

        return count

    # ==================== Button press entry point ====================

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
        """Handle a button press with buffered processing.

        Args:
            callback_data: The callback data string (button value)
            chat_id: Platform chat ID
            message_id: Message ID being interacted with
            user_id: User ID who pressed the button
            user_name: Display name of the user
            adapter: Platform adapter for sending responses
            raw: Platform-specific event object (for answering interactions)
        """
        if is_media_only_mirror(chat_id):
            return

        # Resolve leader: buffer and processing are keyed to the leader chat
        leader_id = get_leader_chat_id(chat_id)

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
            await self._handle_modifier_button_press(raw, chat_id, message_id, key, adapter, leader_id=leader_id)
            return

        if not is_valid_button_callback(callback_data):
            try:
                await adapter.answer_interaction(raw, "Invalid button")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        button = get_button_from_callback(callback_data)
        # Session validation uses the originating chat (ensures user clicked current message)
        session = self._get_session(chat_id)
        if not session or button is None:
            try:
                error_msg = translation_manager.get("game.no_active_game", chat_id)
                await adapter.answer_interaction(raw, error_msg)
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        # Validate message is current (uses originating chat's message_id)
        if session.state.message_id != message_id:
            try:
                error_msg = translation_manager.get("game.message_outdated", chat_id)
                await adapter.answer_interaction(raw, error_msg)
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        # Add input to buffer keyed to leader
        buffer = self._get_or_create_buffer(leader_id)
        success, (message_key, message_params) = buffer.add(user_id, user_name, button)

        if not success:
            try:
                await adapter.answer_interaction(raw, translation_manager.get(message_key, chat_id, **message_params))
            except Exception as e:
                logger.error(f"Error answering callback for chat {chat_id}: {e}")
            return

        # Signal drain or reset debounce timer (keyed to leader)
        drain_event = self._get_or_create_drain_event(leader_id)
        # Always cancel any existing debounce timer first
        existing_task = self._buffer_tasks.get(leader_id)
        if existing_task and not existing_task.done():
            existing_task.cancel()
        if (buffer.total_buttons() >= settings.max_sequence_length) or (button == GameButton.WAIT):
            drain_event.set()
        else:
            self._buffer_tasks[leader_id] = asyncio.create_task(
                self._run_buffer_timer(leader_id)
            )

        # Start processing loop if not already running (keyed to leader)
        if not self._is_processing(leader_id):
            try:
                if adapter.platform != "discord":
                    await adapter.answer_interaction(
                        raw,
                        translation_manager.get(
                            'game.input_processing',
                            chat_id,
                            input=translation_manager.get(f'keyboard.buttons.display_name.{button.value}', chat_id)
                        )
                    )
                leader_config = state_manager.get_or_create_chat_config(leader_id)
                leader_adapter = self._get_adapter_for_chat(leader_id)
                leader_session = self._get_session(leader_id)
                leader_msg_id = leader_session.state.message_id if leader_session else message_id
                asyncio.create_task(
                    self._process_queue_loop(leader_id, leader_msg_id, leader_adapter or adapter)
                )
            except Exception as e:
                logger.error(f"Error starting queue processing for chat {chat_id}: {e}")
                await self._send_error_message(chat_id, translation_manager.get('game.input_processing_error', chat_id), adapter)
        else:
            try:
                if adapter.platform != "discord":
                    await adapter.answer_interaction(raw, translation_manager.get(message_key, chat_id, **message_params))
            except Exception as e:
                logger.error(f"Error answering callback for chat {chat_id}: {e}")

    async def handle_sequence_input(
        self,
        buttons: list[GameButton],
        chat_id: int,
        message_id: int,
        user_id: int,
        user_name: str,
        adapter: "BotAdapter",
    ) -> tuple[bool, str]:
        """Enqueue a pre-validated sequence of buttons from a modal submission.

        Unlike handle_button_press, this method:
        - Accepts a list of buttons (not a callback string)
        - Pre-checks buffer capacity atomically before adding anything
        - Sets the drain event immediately (no debounce timer)
        - Does NOT send interaction acknowledgement (caller handles it)

        Args:
            buttons: Pre-validated list of GameButton values to enqueue
            chat_id: Originating chat ID (may be a mirror)
            message_id: Expected current message ID (validated against session)
            user_id: Platform user ID
            user_name: Display name
            adapter: Platform adapter

        Returns:
            (True, "") on success, (False, error_message) on failure.
        """
        if is_media_only_mirror(chat_id):
            return False, translation_manager.get("game.no_active_game", chat_id)

        leader_id = get_leader_chat_id(chat_id)

        session = self._get_session(chat_id)
        if not session:
            return False, translation_manager.get("game.no_active_game", chat_id)

        if session.state.message_id != message_id:
            return False, translation_manager.get("game.message_outdated", chat_id)

        buffer = self._get_or_create_buffer(leader_id)

        # Atomic pre-check: ensure ALL buttons fit before adding any.
        # Uses > (not >=) to guarantee every individual buffer.add() call succeeds,
        # since PendingBuffer.add() rejects when len(items) >= max_size.
        if len(buffer.items) + len(buttons) > buffer.max_size:
            return False, translation_manager.get("queue.error_queue_full", chat_id)

        for button in buttons:
            buffer.add(user_id, user_name, button)

        # Signal drain immediately — sequence is a complete, finalized input.
        drain_event = self._get_or_create_drain_event(leader_id)
        drain_event.set()

        # Start the processing loop if not already running.
        if not self._is_processing(leader_id):
            try:
                leader_config = state_manager.get_or_create_chat_config(leader_id)
                leader_adapter = self._get_adapter_for_chat(leader_id)
                leader_session = self._get_session(leader_id)
                leader_msg_id = leader_session.state.message_id if leader_session else message_id
                asyncio.create_task(
                    self._process_queue_loop(leader_id, leader_msg_id, leader_adapter or adapter)
                )
            except Exception as e:
                logger.error(f"Error starting queue processing for chat {chat_id}: {e}")

        return True, ""

    async def _handle_modifier_button_press(
        self, raw: object, chat_id: int, message_id: int, key: str, adapter: BotAdapter,
        leader_id: int | None = None
    ) -> None:
        """Handle a modifier button press to toggle modifier state.

        Modifier state is stored on the leader config; keyboard is updated on
        the originating chat only (mirrors will see it on next broadcast).
        """
        if leader_id is None:
            leader_id = get_leader_chat_id(chat_id)

        config = state_manager.get_or_create_chat_config(leader_id)
        config.modifier_states[key] = not config.modifier_states.get(key, False)
        state_manager.save_chat_config(config)

        controller = await game_controller_manager.get_or_create_controller(leader_id)
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
            if adapter.platform != "discord":
                await adapter.answer_interaction(raw, message)
        except Exception as e:
            logger.error(f"Error answering modifier callback for chat {chat_id}: {e}")

    # ==================== Processing loop ====================

    async def _process_queue_loop(self, chat_id: int, message_id: int, adapter: BotAdapter) -> None:
        """Process buffered inputs until the buffer is empty."""
        self._processing.add(chat_id)
        session = self._get_session(chat_id)

        if not session:
            self._processing.discard(chat_id)
            return

        mark_busy()
        try:
            while True:
                buffer = self._get_or_create_buffer(chat_id)
                if buffer.is_empty():
                    break

                drain_event = self._get_or_create_drain_event(chat_id)
                await drain_event.wait()
                drain_event.clear()

                buffer = self._get_or_create_buffer(chat_id)
                if buffer.is_empty():
                    break

                batch = buffer.pop_batch(settings.maximum_inputs_per_animation)

                try:
                    self._aggregate_to_recent_inputs(session.state, batch)
                    result = await self._process_batch(chat_id, message_id, batch, adapter)
                except Exception as e:
                    logger.error(f"Error processing batch for chat {chat_id}: {e}")
                    result = {"animation_duration": None}

                state_manager.save_game_state(session.state, save_user_input_counts=True)

                animation_duration = result.get("animation_duration") or 0
                wait_time = max(animation_duration, settings.min_update_interval_seconds)
                await asyncio.sleep(wait_time)

        finally:
            # Cancel any pending debounce timer and clear stale drain signal
            existing_task = self._buffer_tasks.get(chat_id)
            if existing_task and not existing_task.done():
                existing_task.cancel()
            drain_event = self._drain_events.get(chat_id)
            if drain_event:
                drain_event.clear()
            mark_idle()
            self._processing.discard(chat_id)
            if session:
                session.state.input_in_progress = False
                state_manager.save_game_state(session.state)

            logger.info(f"Queue processing completed for chat {chat_id}")

    # ==================== Batch processing ====================

    async def _process_batch(
        self, chat_id: int, message_id: int, batch: list[BufferedInput], adapter: BotAdapter
    ) -> dict:
        """Process a batch of buffered inputs as a single animation."""
        controller = await game_controller_manager.get_or_create_controller(chat_id)
        checkpoint = controller.save_state()
        session = self._get_session(chat_id)

        buttons = [bi.button for bi in batch]

        hook_context = controller.begin_hooks()

        config = state_manager.get_or_create_chat_config(chat_id)
        modifier_specs = controller.get_modifier_specs()
        modifier_states = config.modifier_states if config else {}

        input_keyboard = adapter.build_game_keyboard(chat_config=config, modifier_specs=modifier_specs)

        # Fetch pre-existing recent inputs for overlay (before this batch)
        pre_existing_inputs_for_overlay = []
        try:
            pre_existing_inputs_for_overlay = state_manager.get_recent_inputs_for_overlay(chat_id, limit=30)
        except Exception as e:
            logger.warning(f"Failed to get recent inputs for overlay for chat {chat_id}: {e}")

        logger.info(f"Executing batch of {len(buttons)} buttons for chat {chat_id} (modifier_states={modifier_states})")

        # Read game-specific status bar data before capture starts
        status_bar_data = controller.get_status_bar_data()

        # Animation capture settings - GameBoy runs at 60fps, capture at 15fps
        game_fps = 60
        capture_fps = 15
        capture_interval_frames = game_fps // capture_fps
        controller.begin_capture(capture_interval_frames)

        new_inputs_with_offsets = []  # list of (input_dict, frame_offset)
        cumulative_frames = 0  # tracks frames captured so far

        for i, button in enumerate(buttons):
            if button == GameButton.WAIT:
                logger.debug(f"WAIT button in batch for chat {chat_id}")
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
                    logger.debug(f"Executing {button.value} in batch for chat {chat_id}")
                    controller.send_input(button, frames=settings.input_hold_frames)

            # Record frame offset at time of button press
            frame_offset = cumulative_frames // capture_interval_frames  # convert game frames to capture frame index
            bi = batch[i]

            # Score input first so total_score can be included in input_dict
            # commit=False: all scoring writes are committed in a single batch after the loop
            input_total_score = None
            try:
                scored = scoring_manager.score_input(
                    platform=config.platform,
                    user_id=bi.user_id,
                    chat_id=chat_id,
                    button=bi.button.value,
                    timestamp=bi.received_at.isoformat(),
                    user_name=bi.user_name,
                    commit=False,
                )
                input_total_score = scored.total_score
                state_manager.append_recent_input(
                    chat_id=chat_id,
                    user_id=bi.user_id,
                    user_name=bi.user_name,
                    button=bi.button.value,
                    timestamp=bi.received_at.isoformat(),
                    base_score=scored.base_score,
                    streak_bonus=scored.streak_bonus,
                    total_score=scored.total_score,
                    commit=False,
                )
            except Exception as e:
                logger.warning(f"Failed to append recent input for chat {chat_id}: {e}")

            input_dict = {
                'user_id': bi.user_id,
                'user_name': bi.user_name,
                'button': bi.button.value,
                'timestamp': bi.received_at.isoformat(),
                'total_score': input_total_score,
                'current_streak': scored.current_streak if input_total_score is not None else 0,
            }
            new_inputs_with_offsets.append((input_dict, frame_offset))

            # Advance cumulative_frames count
            cumulative_frames += settings.input_hold_frames
            if i < len(buttons) - 1:
                delay_frames = int(settings.sequence_delay_seconds * game_fps)
                cumulative_frames += delay_frames
                for _frame_num in range(delay_frames):
                    controller.tick(1)

        # Commit all scoring and recent_inputs writes in one transaction
        try:
            state_manager.connection.commit()
        except Exception as e:
            logger.error(f"Failed to commit batch scoring writes for chat {chat_id}: {e}")

        # Continue animating after last button press
        animation_frames = int(settings.animation_duration * game_fps)
        auto_press_call_threshold = hook_context.get("autoPressA", {}).get("_total", 0) + game_fps

        actual_ticked = self._tick_and_capture_animation_frames(
            controller,
            animation_frames,
            hook_context,
            game_fps,
        )

        # Guarantee ≥2 second (2 * capture_fps capture frames) after last user input
        capture_frames_elapsed = actual_ticked // capture_interval_frames
        capture_frames_expected = 2 * capture_fps
        remaining_capture = capture_frames_expected - capture_frames_elapsed
        if remaining_capture > 0:
            controller.tick(remaining_capture * capture_interval_frames)

        # Auto press A and capture more frames ahead (e.g.: during NPC dialogue)
        MAX_AUTO_PRESS_ITERATIONS = 10
        auto_press_iterations = 0

        while (
            hook_context.get("autoPressA", {}).get("_total", 0) >= auto_press_call_threshold
            and auto_press_iterations < MAX_AUTO_PRESS_ITERATIONS
        ):
            logger.debug(f"Auto-pressing A (iteration {auto_press_iterations + 1}/{MAX_AUTO_PRESS_ITERATIONS})...")

            controller.send_input(GameButton.A, frames=settings.input_hold_frames)

            auto_press_call_threshold = hook_context.get("autoPressA", {}).get("_total", 0) + game_fps

            self._tick_and_capture_animation_frames(
                controller,
                animation_frames,
                hook_context,
                game_fps,
            )
            auto_press_iterations += 1

        if auto_press_iterations >= MAX_AUTO_PRESS_ITERATIONS:
            logger.warning(f"[MEM] autoPressA loop hit cap ({MAX_AUTO_PRESS_ITERATIONS}) for chat {chat_id}")

        logger.info(f"Animation completed for chat {chat_id} in {animation_frames} frames")

        raw_frames = controller.end_capture()
        logger.info(f"[MEM] raw_frames={len(raw_frames)}, approx_raw_MB={len(raw_frames)*69/1024:.1f}")
        audio_chunks = controller.get_last_captured_audio()
        controller.end_hooks(hook_context)

        if hook_context.get("dangerousActions", {}).get("_total", 0) > 0:
            logger.info(f"Dangerous action ({str(hook_context.get('dangerousActions', {}))}) blocked for chat {chat_id}")
            controller.load_state(checkpoint)
            error_msg = translation_manager.get("game.safe_mode_blocked", chat_id)
            await self._send_error_message(chat_id, error_msg, adapter)
            return {"animation_duration": None}

        # 1. Generate TBC from last raw frame (scaled 3x)
        last_raw = raw_frames[-1] if raw_frames else np.array(controller.get_frame())
        last_raw_h, last_raw_w = last_raw.shape[:2]
        last_scaled = np.array(Image.fromarray(last_raw).resize(
            (last_raw_w * 2, last_raw_h * 2), Image.Resampling.NEAREST
        ))
        tbc_frames = generate_tbc_frames(
            last_scaled,
            overlay_path=settings.tbc_overlay_path,
            duration_frames=settings.tbc_duration_frames,
            end_hold_frames=settings.tbc_duration_frames,
            max_width_percent=0.7,
        )
        num_tbc_frames = len(tbc_frames)
        num_raw_frames = len(raw_frames)

        # 2. Pop queued reactions (before building transforms so they can be stored)
        reactions = []
        num_windows = (num_raw_frames + num_tbc_frames) // (2 * capture_fps)
        if num_windows > 0:
            reactions = state_manager.pop_reactions(chat_id, limit=num_windows * 3)

        # 3. Pre-fetch user colors for sidebar rendering (single batch query)
        uid_to_uname: dict = {}
        for inp_dict, _ in new_inputs_with_offsets:
            uid = inp_dict.get("user_id")
            if uid:
                uid_to_uname.setdefault(uid, inp_dict.get("user_name", ""))
        for inp in pre_existing_inputs_for_overlay:
            uid = inp.get("user_id")
            if uid:
                uid_to_uname.setdefault(uid, inp.get("user_name", ""))
        profiles = scoring_manager.get_player_profiles_batch(config.platform, list(uid_to_uname))
        user_colors: dict = {
            uname: hex_to_rgb(profiles[uid].name_tag_color)
            for uid, uname in uid_to_uname.items()
            if uid in profiles and uname and profiles[uid].name_tag_color
        }

        # 4. Build streaming animation transform
        #    Raw frames (index < num_raw_frames): scale 3x + reactions + sidebar
        #    TBC frames (index >= num_raw_frames): already scaled, sidebar only
        reaction_transform_fn = (
            _make_reaction_frame_transform(reactions, capture_fps, scale=2, frame_skip=1)
            if reactions else None
        )
        sidebar_transform_fn = _make_frame_transform(
            pre_existing_inputs_for_overlay, new_inputs_with_offsets, capture_fps,
            user_colors=user_colors,
            scale=2
        )
        status_bar_render_fn = controller.get_status_bar_render_fn()
        _status_bar_cache: list[np.ndarray | None] = [None]

        def animation_transform(frame: np.ndarray, index: int) -> np.ndarray:
            if index < num_raw_frames:
                h, w = frame.shape[:2]
                scaled = np.array(Image.fromarray(frame).resize(
                    (w * 2, h * 2), Image.Resampling.NEAREST
                ))
                if reaction_transform_fn is not None:
                    scaled = reaction_transform_fn(scaled, index)
            else:
                scaled = frame  # TBC frames are already 2x-scaled
            composited = sidebar_transform_fn(scaled)
            if _status_bar_cache[0] is None:
                _status_bar_cache[0] = render_status_bar(status_bar_data, composited.shape[1], scale=2, render_fn=status_bar_render_fn)
            return np.vstack([composited, _status_bar_cache[0]])

        animation_duration_seconds = num_raw_frames / capture_fps

        recent = _build_recent_inputs_grouped(pre_existing_inputs_for_overlay, new_inputs_with_offsets)
        pending_count = self._get_or_create_buffer(chat_id).total_buttons()
        base_text = self._get_message_base_text(chat_id)
        caption = create_game_message_text(
            recent_inputs=recent,
            queue_length=pending_count,
            base_text_override=base_text,
            chat_id=chat_id,
        )

        if raw_frames:
            logger.info(f"Streaming animation encode: {num_raw_frames} raw + {num_tbc_frames} TBC frames for chat {chat_id}")

            try:
                # 5+6. Encode and broadcast animation to chat and mirrors
                try:
                    await broadcast_game_update(
                        chat_id, caption, raw_frames, tbc_frames,
                        capture_fps, modifier_specs, animation_transform,
                    )
                except Exception as e:
                    logger.warning(f"Failed to broadcast game update for chat {chat_id}: {e}")

                # Fire-and-forget avatar update if feature flag is enabled
                if config.feature_flags.get("update_group_avatar") and _should_update_avatar(config):
                    asyncio.create_task(
                        self._update_group_avatar(chat_id, controller, adapter, config)
                    )

                # 7. Persist raw frames to disk and enqueue DB timelapse job
                from src.tasks.timelapse_encoder import timelapse_queue

                if timelapse_queue is not None:
                    try:
                        if config.feature_flags.get("realtime_recaps"):
                            frame_skip = 1
                            timelapse_fps = 15
                            timelapse_audio = audio_chunks or None
                        else:
                            frame_skip = settings.timelapse_frame_skip
                            timelapse_fps = 10
                            timelapse_audio = None

                        compositing_context = {
                            "frame_count": num_raw_frames,
                            "frame_skip": frame_skip,
                            "capture_fps": capture_fps,
                            "timelapse_fps": timelapse_fps,
                            "pre_existing_inputs": pre_existing_inputs_for_overlay,
                            "new_inputs_with_offsets": [
                                [inp_d, off] for inp_d, off in new_inputs_with_offsets
                            ],
                            "reactions": list(reactions),
                            "user_colors": {k: list(v) for k, v in user_colors.items()},
                            "status_bar_data": status_bar_data,
                            "cartridge_title": controller.pyboy.cartridge_title if controller.pyboy else None,
                        }

                        ts_str = datetime.now().strftime('%Y%m%d_%H%M%S')
                        uid_str = uuid.uuid4().hex[:8]
                        folder = (
                            settings.data_dir / "frames" / str(chat_id) / f"{ts_str}_{uid_str}"
                        )

                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None, _save_raw_frames_sync, raw_frames, folder, timelapse_audio
                        )

                        timestamp = datetime.now().isoformat()
                        state_manager.insert_timelapse_job(
                            chat_id=str(chat_id),
                            folder_path=str(folder),
                            timestamp=timestamp,
                            fps=timelapse_fps,
                            compositing_context=compositing_context,
                        )
                        timelapse_queue.trigger_worker(str(chat_id))
                        logger.debug(
                            f"Timelapse job queued for chat {chat_id} "
                            f"({num_raw_frames} raw frames, skip={frame_skip})"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to queue timelapse for chat {chat_id}: {e}")

            except Exception as e:
                logger.error(f"Failed to generate animation for chat {chat_id}: {e}")
                try:
                    png_buffer = controller.get_frame_as_png()
                    await adapter.edit_game_message(chat_id, message_id, caption, input_keyboard, png_buffer, media_type="photo")
                except Exception as e2:
                    logger.error(f"Fallback failed for chat {chat_id}: {e2}")
            finally:
                # Explicit release: raw frames no longer needed after disk write
                del raw_frames
                del audio_chunks

        # Auto-save if enabled
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

        logger.info(f"Completed batch processing for chat {chat_id}")
        # mem_trace.snapshot(f"post-batch chat={chat_id} frames={len(buttons)}")
        return {"animation_duration": animation_duration_seconds}

    async def _update_group_avatar(self, chat_id: int, controller, adapter: BotAdapter, config) -> None:
        """Update the group avatar with the current game frame (fire-and-forget)."""
        try:
            png_bytes = controller.get_frame_as_png().getvalue()
            await adapter.update_chat_photo(chat_id, png_bytes)
            config.last_avatar_update_at = datetime.utcnow()
            state_manager.save_chat_config(config)
            logger.info(f"Updated group avatar for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to update group avatar for {chat_id}: {e}")
            try:
                await adapter.send_text(chat_id, translation_manager.get("game.avatar_update_failed", chat_id))
            except Exception:
                pass

    # ==================== Recent inputs aggregation ====================

    def _aggregate_to_recent_inputs(self, state: ChatGameState, batch: list[BufferedInput]) -> None:
        """Update per-user input counts from a processed batch.

        Args:
            state: The ChatGameState to update
            batch: The batch of BufferedInputs that were just processed
        """
        for bi in batch:
            state.user_input_counts[str(bi.user_id)] = (
                state.user_input_counts.get(str(bi.user_id), 0) + 1
            )

    # ==================== Backward-compat: _process_sequence ====================

    async def _process_sequence(
        self, chat_id: int, buttons: list[GameButton], message_id: int, adapter: BotAdapter
    ) -> None:
        """Process a sequence of buttons (backward compatibility alias)."""
        batch = [
            BufferedInput(user_id=0, user_name="System", button=b)
            for b in buttons
        ]
        await self._process_batch(chat_id, message_id, batch, adapter)

    # ==================== Edit helpers ====================

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

    # ==================== Game lifecycle ====================

    async def start_game(self, chat_id: int, adapter: BotAdapter) -> int:
        """Start a new game for a chat."""
        controller = await game_controller_manager.get_or_create_controller(chat_id)
        png_buffer = controller.get_frame_as_png()

        session = self._create_session(chat_id, 0)

        config = state_manager.get_or_create_chat_config(chat_id)
        modifier_specs = controller.get_modifier_specs()

        buffer = self._get_or_create_buffer(chat_id)

        recent = state_manager._load_recent_inputs(chat_id)
        base_text = self._get_message_base_text(chat_id)
        text = create_game_message_text(recent_inputs=recent, queue_length=buffer.total_buttons(), base_text_override=base_text, chat_id=chat_id)
        keyboard = adapter.build_game_keyboard(chat_config=config, modifier_specs=modifier_specs)

        message_id = await adapter.send_game_message(chat_id, text, keyboard, png_buffer)

        session.state.message_id = message_id
        state_manager.save_game_state(session.state)

        logger.info(f"Started game for chat {chat_id}, message {message_id}")

        return message_id

    async def show_current_frame(self, chat_id: int, adapter: BotAdapter) -> Optional[int]:
        """Show the current game frame."""
        session = self._get_session(chat_id)
        controller = game_controller_manager.get_controller(chat_id)

        if not controller or not controller.is_initialized():
            return None

        config = state_manager.get_or_create_chat_config(chat_id)
        modifier_specs = controller.get_modifier_specs()

        buffer = self._get_or_create_buffer(chat_id)

        png_buffer = controller.get_frame_as_png()
        recent = state_manager._load_recent_inputs(chat_id)
        base_text = self._get_message_base_text(chat_id)
        caption = create_game_message_text(recent_inputs=recent, queue_length=buffer.total_buttons(), base_text_override=base_text, chat_id=chat_id)
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
        """Resume the game by sending a new message with keyboard."""
        session = self._get_session(chat_id)
        leader_id = get_leader_chat_id(chat_id)
        leader_controller = game_controller_manager.get_controller(leader_id)
        leader_buffer = self._get_or_create_buffer(leader_id)

        if not leader_controller or not leader_controller.is_initialized():
            return None

        leader_config = state_manager.get_or_create_chat_config(leader_id)
        modifier_specs = leader_controller.get_modifier_specs()

        png_buffer = leader_controller.get_frame_as_png()

        # Remove keyboard from old message if it exists
        if session and session.state.message_id:
            try:
                await adapter.edit_game_keyboard(chat_id, session.state.message_id, None)
            except Exception:
                pass

        leader_session = self._get_session(leader_id)
        recent = state_manager._load_recent_inputs(leader_id)
        base_text = self._get_message_base_text(leader_id)
        text = create_game_message_text(recent_inputs=recent, queue_length=leader_buffer.total_buttons(), base_text_override=base_text, chat_id=leader_id)
        keyboard = adapter.build_game_keyboard(chat_config=leader_config, modifier_specs=modifier_specs)

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
            self._pending_buffers.pop(chat_id, None)
            self._buffer_tasks.pop(chat_id, None)
            self._drain_events.pop(chat_id, None)

            game_controller_manager.remove_controller(chat_id)

            logger.info(f"Cleaned up session for chat {chat_id}")
            return True

        return False


# Singleton instance
_input_handler: Optional[InputHandler] = None


def get_input_handler() -> InputHandler:
    """Get or create the singleton InputHandler instance."""
    global _input_handler
    if _input_handler is None:
        _input_handler = InputHandler()
    return _input_handler
