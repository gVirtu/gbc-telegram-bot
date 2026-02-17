"""Game controller for managing PyBoy emulator instances.

This module provides a high-level interface for controlling the GameBoy emulator,
including frame capture, input injection, and save state management.
"""

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np
from pyboy import PyBoy
from pyboy.utils import WindowEvent

from src.config import settings
from src.models.game_state import GameButton
from src.utils.state_manager import state_manager
from src.utils.frame_utils import frame_to_png, hash_frame

logger = logging.getLogger(__name__)

# Map GameButton to PyBoy WindowEvent
BUTTON_EVENTS = {
    GameButton.UP: (WindowEvent.PRESS_ARROW_UP, WindowEvent.RELEASE_ARROW_UP),
    GameButton.DOWN: (WindowEvent.PRESS_ARROW_DOWN, WindowEvent.RELEASE_ARROW_DOWN),
    GameButton.LEFT: (WindowEvent.PRESS_ARROW_LEFT, WindowEvent.RELEASE_ARROW_LEFT),
    GameButton.RIGHT: (WindowEvent.PRESS_ARROW_RIGHT, WindowEvent.RELEASE_ARROW_RIGHT),
    GameButton.A: (WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A),
    GameButton.B: (WindowEvent.PRESS_BUTTON_B, WindowEvent.RELEASE_BUTTON_B),
    GameButton.START: (WindowEvent.PRESS_BUTTON_START, WindowEvent.RELEASE_BUTTON_START),
    GameButton.SELECT: (WindowEvent.PRESS_BUTTON_SELECT, WindowEvent.RELEASE_BUTTON_SELECT),
}


class GameController:
    """Manages a PyBoy emulator instance for a chat.
    
    This class provides a high-level interface for:
    - Initializing and running the emulator
    - Capturing frames from the screen
    - Injecting button inputs
    - Managing save states
    
    Example:
        >>> controller = GameController(123456)
        >>> await controller.initialize()
        >>> frame = controller.get_frame()
        >>> controller.send_input(GameButton.A, frames=30)
    """
    
    def __init__(
        self,
        chat_id: int,
        rom_path: Optional[Path] = None,
        sym_path: Optional[Path] = None,
    ):
        """Initialize the game controller.
        
        Args:
            chat_id: Telegram chat ID for this game instance
            rom_path: Path to the ROM file (default: from settings)
            sym_path: Path to the SYM file (default: from settings)
        """
        self.chat_id = chat_id
        self.rom_path = rom_path or settings.rom_path
        self.sym_path = sym_path or settings.sym_path
        self.pyboy: Optional[PyBoy] = None
        self.last_frame_hash: Optional[str] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize the PyBoy emulator.
        
        This must be called before using the controller.
        Runs the emulator for a few frames to get it ready.
        
        Raises:
            FileNotFoundError: If ROM file doesn't exist
            RuntimeError: If emulator fails to initialize
        """
        if self._initialized:
            logger.debug(f"GameController for chat {self.chat_id} already initialized")
            return
        
        if not self.rom_path.exists():
            raise FileNotFoundError(f"ROM file not found: {self.rom_path}")
        
        if self.sym_path is not None and not self.sym_path.exists():
            raise FileNotFoundError(f"SYM file not found: {self.sym_path}")
        
        try:
            logger.info(f"Initializing PyBoy for chat {self.chat_id}")
            
            # Initialize PyBoy with no window (headless)
            self.pyboy = PyBoy(
                str(self.rom_path),
                window="null",
                sound_emulated=False,
                symbols=str(self.sym_path)
            )
            
            # Run a few frames to get past boot screen
            for _ in range(100):
                self.pyboy.tick()
            
            self._initialized = True
            logger.info(f"PyBoy initialized successfully for chat {self.chat_id}")
            
        except Exception as e:
            logger.error(f"Failed to initialize PyBoy for chat {self.chat_id}: {e}")
            self.pyboy = None
            raise RuntimeError(f"Failed to initialize emulator: {e}") from e
    
    def is_initialized(self) -> bool:
        """Check if the emulator is initialized and ready.
        
        Returns:
            True if initialized, False otherwise
        """
        return self._initialized and self.pyboy is not None
    
    def get_frame(self) -> np.ndarray:
        """Get the current screen frame as a numpy array.
        
        Returns:
            RGB frame array with shape (height, width, 3)
            
        Raises:
            RuntimeError: If emulator not initialized
        """
        if not self.is_initialized():
            raise RuntimeError("Emulator not initialized. Call initialize() first.")
        
        # Get screen from PyBoy - use screen_ndarray() directly
        # This works with newer PyBoy versions (2.x+)
        try:
            # Try the newer API first (direct method on PyBoy)
            frame = self.pyboy.screen.ndarray
        except AttributeError:
            # Fallback to older API
            try:
                frame = self.pyboy.botsupport_manager().screen().screen_ndarray()
            except AttributeError:
                # Last resort - try screen_ndarray directly
                frame = self.pyboy.screen_ndarray()
        
        # Handle RGBA (4 channels) by dropping the alpha channel
        if frame.ndim == 3 and frame.shape[2] == 4:
            # Drop the alpha channel to get RGB
            frame = frame[:, :, :3]
        
        return frame
    
    def get_frame_as_png(self) -> BytesIO:
        """Get the current frame as PNG bytes.
        
        Returns:
            BytesIO containing PNG image data
        """
        frame = self.get_frame()
        return frame_to_png(frame)
    
    def tick(self, frames: int = 1) -> np.ndarray:
        """Advance the emulator by a number of frames.
        
        Args:
            frames: Number of frames to advance (default: 1)
            
        Returns:
            The frame after ticking
        """
        if not self.is_initialized():
            raise RuntimeError("Emulator not initialized. Call initialize() first.")
        
        for _ in range(frames):
            self.pyboy.tick()
        
        return self.get_frame()
    
    def send_input(self, button: GameButton, frames: int) -> np.ndarray:
        """Press and hold a button for a number of frames.
        
        This is the main method for executing game inputs.
        
        Args:
            button: The button to press
            frames: Number of frames to hold the button
            
        Returns:
            The frame after releasing the button
            
        Example:
            >>> # Press A for 30 frames (0.5 seconds @ 60fps)
            >>> frame = controller.send_input(GameButton.A, frames=30)
        """
        if not self.is_initialized():
            raise RuntimeError("Emulator not initialized. Call initialize() first.")
        
        if button not in BUTTON_EVENTS:
            raise ValueError(f"Invalid button: {button}")
        
        press_event, release_event = BUTTON_EVENTS[button]
        
        logger.debug(f"Sending input {button.value} for {frames} frames to chat {self.chat_id}")
        
        # Press button
        self.pyboy.send_input(press_event)
        
        # Hold for specified frames
        for _ in range(frames):
            self.pyboy.tick()
        
        # Release button
        self.pyboy.send_input(release_event)
        
        # One more tick to process release
        self.pyboy.tick()
        
        return self.get_frame()
    
    def send_input_with_modifier(
        self,
        button: GameButton,
        modifier: GameButton,
        frames: int
    ) -> np.ndarray:
        """Press and hold a button with a modifier button held throughout.
        
        Used for running mode where B button is held during directional inputs.
        
        Args:
            button: The primary button to press (e.g., UP, DOWN, LEFT, RIGHT)
            modifier: The modifier button to hold throughout (e.g., B)
            frames: Number of frames to hold both buttons
            
        Returns:
            The frame after releasing both buttons
            
        Example:
            >>> # Press UP while holding B for 30 frames (running)
            >>> frame = controller.send_input_with_modifier(GameButton.UP, GameButton.B, frames=30)
        """
        if not self.is_initialized():
            raise RuntimeError("Emulator not initialized. Call initialize() first.")
        
        if button not in BUTTON_EVENTS:
            raise ValueError(f"Invalid button: {button}")
        if modifier not in BUTTON_EVENTS:
            raise ValueError(f"Invalid modifier: {modifier}")
        
        button_press, button_release = BUTTON_EVENTS[button]
        modifier_press, modifier_release = BUTTON_EVENTS[modifier]
        
        logger.debug(
            f"Sending input {button.value} with {modifier.value} modifier for {frames} frames "
            f"to chat {self.chat_id}"
        )
        
        # Press modifier first
        self.pyboy.send_input(modifier_press)
        
        # Press primary button
        self.pyboy.send_input(button_press)
        
        # Hold both for specified frames
        for _ in range(frames):
            self.pyboy.tick()
        
        # Release primary button
        self.pyboy.send_input(button_release)
        
        # Release modifier button
        self.pyboy.send_input(modifier_release)
        
        # One more tick to process releases
        self.pyboy.tick()
        
        return self.get_frame()
    
    def save_state(self) -> bytes:
        """Save the current emulator state to bytes.
        
        Returns:
            Raw save state bytes that can be loaded later
        """
        if not self.is_initialized():
            raise RuntimeError("Emulator not initialized. Call initialize() first.")
        
        import io
        buffer = io.BytesIO()
        self.pyboy.save_state(buffer)
        buffer.seek(0)
        
        return buffer.read()
    
    def load_state(self, state_data: bytes) -> None:
        """Load emulator state from bytes.
        
        Args:
            state_data: Raw save state bytes from save_state()
        """
        if not self.is_initialized():
            raise RuntimeError("Emulator not initialized. Call initialize() first.")
        
        import io
        buffer = io.BytesIO(state_data)
        self.pyboy.load_state(buffer)
        
        logger.info(f"Loaded save state for chat {self.chat_id}")
    
    def should_update_frame(self, current_frame: Optional[np.ndarray] = None) -> tuple[bool, str]:
        """Check if the frame has changed and should be sent.
        
        Args:
            current_frame: The current frame (if None, captures new frame)
            
        Returns:
            Tuple of (should_update, current_hash)
        """
        if current_frame is None:
            current_frame = self.get_frame()
        
        current_hash = hash_frame(current_frame)
        
        if self.last_frame_hash is None:
            # First frame always updates
            return True, current_hash
        
        if current_hash == self.last_frame_hash:
            # No change
            return False, current_hash
        
        return True, current_hash
    
    def update_frame_hash(self, frame_hash: str) -> None:
        """Update the stored frame hash.
        
        Call this after sending a frame to track changes.
        
        Args:
            frame_hash: The hash of the sent frame
        """
        self.last_frame_hash = frame_hash
        
    def begin_polished_crystal_hooks(self):
        context = {
            "dangerousActions": {
                "TossMenu": 0,
                "BillsPC_Release": 0,
                "BillsPC_ReleaseAll": 0,
                "_total": 0
            },
            "inputWaitCalls": {
                "DoPlayerMovement.GetAction": 0,
                "JoyWaitAorB": 0,
                "WaitButton": 0,
                "WaitPressAorB_BlinkCursor": 0,
                "ButtonSound.input_wait_loop": 0,
                "Do2DMenuRTCJoypad_loop": 0,
                "SummaryScreenLoop": 0,
                "_total": 0
            }
        }
        
        def increment_context_counter(ctx, path):
            target = ctx
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] += 1
            target["_total"] += 1
            return None
        
        def make_hook(category, action):
            return lambda ctx: increment_context_counter(ctx, [category, action])

        for action in context["dangerousActions"].keys():
            if action.startswith("_"):
                continue
            self.pyboy.hook_register(None, action, make_hook("dangerousActions", action), context)
        
        for action in context["inputWaitCalls"].keys():
            if action.startswith("_"):
                continue
            self.pyboy.hook_register(None, action, make_hook("inputWaitCalls", action), context)
        
        return context


    def end_polished_crystal_hooks(self, context: dict):
        for action in context["dangerousActions"].keys():
            if action.startswith("_"):
                continue
            self.pyboy.hook_deregister(None, action)
        for action in context["inputWaitCalls"].keys():
            if action.startswith("_"):
                continue
            self.pyboy.hook_deregister(None, action)
        
    def stop(self) -> None:
        """Stop the emulator and clean up resources."""
        if self.pyboy is not None:
            logger.info(f"Stopping emulator for chat {self.chat_id}")
            self.pyboy.stop()
            self.pyboy = None
            self._initialized = False
    
    def __del__(self):
        """Destructor to ensure emulator is stopped."""
        if self.pyboy is not None:
            try:
                self.stop()
            except Exception:
                pass  # Ignore errors during cleanup
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False


class GameControllerManager:
    """Manages multiple GameController instances for different chats.
    
    This is a singleton-like manager that tracks active game sessions
    and provides cleanup for idle sessions.
    
    Example:
        >>> manager = GameControllerManager()
        >>> controller = await manager.get_or_create_controller(123456)
        >>> frame = controller.get_frame()
    """
    
    def __init__(self):
        """Initialize the manager."""
        self._controllers: dict[int, GameController] = {}
    
    async def get_or_create_controller(self, chat_id: int) -> GameController:
        """Get existing controller or create new one.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            GameController instance (initialized)
        """
        if chat_id not in self._controllers:
            logger.info(f"Creating new GameController for chat {chat_id}")
            controller = GameController(chat_id)
            await controller.initialize()
            self._controllers[chat_id] = controller
            
            # Try to load the most recent auto-save if it exists
            slots = state_manager.list_save_slots(chat_id)
            auto_saves = [s for s in slots if s.is_auto_save]
            
            target_slot = None
            
            if auto_saves:
                # Sort by updated_at descending
                auto_saves.sort(key=lambda x: x.updated_at or x.created_at, reverse=True)
                target_slot = auto_saves[0].slot_number
                logger.info(f"Found auto-save in slot {target_slot} for chat {chat_id}")
            elif slots:
                # Fallback to slot 1 if it exists (legacy support)
                if any(s.slot_number == 1 for s in slots):
                    target_slot = 1
                    logger.info(f"No auto-save found, falling back to slot 1 for chat {chat_id}")
            
            if target_slot is not None:
                state_data = state_manager.load_from_slot(chat_id, target_slot)
                if state_data is not None:
                    try:
                        controller.load_state(state_data)
                        logger.info(f"Auto-started game for chat {chat_id} from slot {target_slot}")
                    except Exception as e:
                        logger.error(f"Game restarting due to failed to load slot {target_slot} for chat {chat_id}: {e}")
        
        return self._controllers[chat_id]
    
    def get_controller(self, chat_id: int) -> Optional[GameController]:
        """Get existing controller without creating.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            GameController if exists, None otherwise
        """
        return self._controllers.get(chat_id)
    
    def remove_controller(self, chat_id: int) -> bool:
        """Remove and stop a controller.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            True if removed, False if didn't exist
        """
        controller = self._controllers.pop(chat_id, None)
        if controller:
            controller.stop()
            logger.info(f"Removed GameController for chat {chat_id}")
            return True
        return False
    
    def stop_all(self) -> None:
        """Stop all controllers and clear the manager."""
        logger.info(f"Stopping all {len(self._controllers)} controllers")
        
        for chat_id, controller in list(self._controllers.items()):
            try:
                controller.stop()
            except Exception as e:
                logger.error(f"Error stopping controller for chat {chat_id}: {e}")
        
        self._controllers.clear()

# Global manager instance
game_controller_manager = GameControllerManager()
