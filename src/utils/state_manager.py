"""State management for file-based persistence.

This module provides functionality for saving and loading game state,
including rotating save slots, chat-specific configuration, and poll state.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from src.config import settings
from src.models.game_state import ChatConfig, ChatGameState, SaveSlotInfo

logger = logging.getLogger(__name__)


class StateManager:
    """Manages file-based persistence for game state.
    
    This class handles saving and loading of:
    - Chat game state (message ID, input status, etc.)
    - Chat-specific configuration
    - Save states with rotation
    
    All data is stored in the data directory with the following structure:
    ```
    data/
    ├── polls/
│   └── <chat_id>.json
    ├── saves/
    │   └── <chat_id>/
    │       ├── slot_0.state
    │       ├── slot_1.state
    │       └── ...
    └── config/
        └── <chat_id>.json
    ```
    
    Example:
        >>> manager = StateManager()
        >>> game_state = ChatGameState(chat_id=123)
        >>> manager.save_game_state(game_state)
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize the state manager.
        
        Args:
            data_dir: Directory for data storage. If None, uses settings.data_dir.
        """
        self.data_dir = data_dir or settings.data_dir
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """Create necessary directory structure if it doesn't exist."""
        (self.data_dir / "polls").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "config").mkdir(parents=True, exist_ok=True)
        # saves/<chat_id>/ directories are created on demand
    
    # ==================== Game State ====================
    
    def save_game_state(self, state: ChatGameState) -> None:
        """Save game state for a chat.
        
        Args:
            state: The game state to save
            
        Example:
            >>> state = ChatGameState(chat_id=123, message_id=456)
            >>> manager.save_game_state(state)
        """
        file_path = self._get_poll_file_path(state.chat_id)
        
        try:
            with open(file_path, "w") as f:
                json.dump(state.to_dict(), f, indent=2)
            logger.debug(f"Saved game state for chat {state.chat_id}")
        except Exception as e:
            logger.error(f"Failed to save game state for chat {state.chat_id}: {e}")
            raise
    
    def load_game_state(self, chat_id: int) -> Optional[ChatGameState]:
        """Load game state for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            The saved game state, or None if not found
            
        Example:
            >>> state = manager.load_game_state(123)
            >>> if state:
            ...     print(f"Message ID: {state.message_id}")
        """
        file_path = self._get_poll_file_path(chat_id)
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            
            state = ChatGameState.from_dict(data)
            logger.debug(f"Loaded game state for chat {chat_id}")
            return state
        except Exception as e:
            logger.error(f"Failed to load game state for chat {chat_id}: {e}")
            return None
    
    def delete_game_state(self, chat_id: int) -> bool:
        """Delete game state for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            True if deleted, False if didn't exist
        """
        file_path = self._get_poll_file_path(chat_id)
        
        if file_path.exists():
            file_path.unlink()
            logger.debug(f"Deleted game state for chat {chat_id}")
            return True
        
        return False
    
    # ==================== Configuration ====================
    
    def save_chat_config(self, config: ChatConfig) -> None:
        """Save configuration for a chat.
        
        Args:
            config: The chat configuration to save
        """
        file_path = self._get_config_file_path(config.chat_id)
        
        try:
            with open(file_path, "w") as f:
                json.dump(config.to_dict(), f, indent=2)
            logger.debug(f"Saved config for chat {config.chat_id}")
        except Exception as e:
            logger.error(f"Failed to save config for chat {config.chat_id}: {e}")
            raise
    
    def load_chat_config(self, chat_id: int) -> Optional[ChatConfig]:
        """Load configuration for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            The saved configuration, or None if not found
        """
        file_path = self._get_config_file_path(chat_id)
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            
            config = ChatConfig.from_dict(data)
            logger.debug(f"Loaded config for chat {chat_id}")
            return config
        except Exception as e:
            logger.error(f"Failed to load config for chat {chat_id}: {e}")
            return None
    
    def get_or_create_chat_config(self, chat_id: int) -> ChatConfig:
        """Get existing config or create default.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            Existing or new ChatConfig
        """
        config = self.load_chat_config(chat_id)
        if config is None:
            config = ChatConfig(chat_id=chat_id)
            self.save_chat_config(config)
        return config
    
    # ==================== Save Slots ====================
    
    def get_save_slot_path(self, chat_id: int, slot_number: int) -> Path:
        """Get the file path for a save slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number (0 to save_slots-1)
            
        Returns:
            Path to the save slot file
        """
        save_dir = self.data_dir / "saves" / str(chat_id)
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir / f"slot_{slot_number}.state"
    
    def get_save_info_path(self, chat_id: int, slot_number: int) -> Path:
        """Get the file path for save slot metadata.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number
            
        Returns:
            Path to the save info JSON file
        """
        save_dir = self.data_dir / "saves" / str(chat_id)
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir / f"slot_{slot_number}.json"
    
    def save_to_slot(
        self,
        chat_id: int,
        slot_number: int,
        state_data: bytes,
        description: Optional[str] = None,
        is_auto_save: bool = False,
    ) -> SaveSlotInfo:
        """Save game state to a specific slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number to save to
            state_data: The raw save state bytes from PyBoy
            description: Optional description of the save
            is_auto_save: Whether this is an auto-save
            
        Returns:
            SaveSlotInfo with metadata about the save
        """
        from datetime import datetime
        
        # Save the state data
        state_path = self.get_save_slot_path(chat_id, slot_number)
        try:
            with open(state_path, "wb") as f:
                f.write(state_data)
        except Exception as e:
            logger.error(f"Failed to save state to slot {slot_number} for chat {chat_id}: {e}")
            raise
        
        # Save metadata
        info = SaveSlotInfo(
            slot_number=slot_number,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            is_auto_save=is_auto_save,
            description=description,
        )
        
        info_path = self.get_save_info_path(chat_id, slot_number)
        try:
            with open(info_path, "w") as f:
                json.dump(info.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save slot info for chat {chat_id}: {e}")
            # Continue even if metadata save fails
        
        logger.info(f"Saved state to slot {slot_number} for chat {chat_id}")
        return info
    
    def load_from_slot(self, chat_id: int, slot_number: int) -> Optional[bytes]:
        """Load game state from a specific slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number to load from
            
        Returns:
            The raw save state bytes, or None if slot doesn't exist
        """
        state_path = self.get_save_slot_path(chat_id, slot_number)
        
        if not state_path.exists():
            return None
        
        try:
            with open(state_path, "rb") as f:
                data = f.read()
            logger.info(f"Loaded state from slot {slot_number} for chat {chat_id}")
            return data
        except Exception as e:
            logger.error(f"Failed to load state from slot {slot_number} for chat {chat_id}: {e}")
            return None
    
    def get_slot_info(self, chat_id: int, slot_number: int) -> Optional[SaveSlotInfo]:
        """Get metadata for a save slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number
            
        Returns:
            SaveSlotInfo if slot exists, None otherwise
        """
        info_path = self.get_save_info_path(chat_id, slot_number)
        
        if not info_path.exists():
            return None
        
        try:
            with open(info_path, "r") as f:
                data = json.load(f)
            return SaveSlotInfo.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load slot info for chat {chat_id}, slot {slot_number}: {e}")
            return None
    
    def list_save_slots(self, chat_id: int, max_slots: int | None = None) -> list[SaveSlotInfo]:
        """List all save slots for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            max_slots: Maximum number of slots to check (default: settings.save_slots)
            
        Returns:
            List of SaveSlotInfo for existing slots
        """
        slots = []
        num_slots = max_slots if max_slots is not None else getattr(settings, 'save_slots', 5)
        for slot_number in range(num_slots):
            info = self.get_slot_info(chat_id, slot_number)
            if info is not None:
                slots.append(info)
        
        return slots
    
    def delete_slot(self, chat_id: int, slot_number: int) -> bool:
        """Delete a save slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number to delete
            
        Returns:
            True if deleted, False if didn't exist
        """
        state_path = self.get_save_slot_path(chat_id, slot_number)
        info_path = self.get_save_info_path(chat_id, slot_number)
        
        deleted = False
        
        if state_path.exists():
            state_path.unlink()
            deleted = True
        
        if info_path.exists():
            info_path.unlink()
            deleted = True
        
        if deleted:
            logger.info(f"Deleted slot {slot_number} for chat {chat_id}")
        
        return deleted
    
    def find_next_auto_save_slot(self, chat_id: int, num_slots: int | None = None) -> int:
        """Find the next slot for auto-save using round-robin.
        
        Args:
            chat_id: The Telegram chat ID
            num_slots: Total number of slots (default: settings.save_slots)
            
        Returns:
            Slot number for next auto-save
        """
        max_slots = num_slots if num_slots is not None else getattr(settings, 'save_slots', 5)
        slots = self.list_save_slots(chat_id, max_slots=max_slots)
        
        # Filter auto-saves and sort by slot number
        auto_saves = [s for s in slots if s.is_auto_save]
        
        if not auto_saves:
            return 0
        
        # Find highest slot number used for auto-save
        max_slot = max(s.slot_number for s in auto_saves)
        
        # Return next slot (with wrap-around)
        return (max_slot + 1) % max_slots
    
    # ==================== Helper Methods ====================
    
    def _get_poll_file_path(self, chat_id: int) -> Path:
        """Get file path for poll/game state."""
        return self.data_dir / "polls" / f"{chat_id}.json"
    
    def _get_config_file_path(self, chat_id: int) -> Path:
        """Get file path for chat config."""
        return self.data_dir / "config" / f"{chat_id}.json"
    
    def chat_exists(self, chat_id: int) -> bool:
        """Check if any data exists for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            True if chat has any saved data
        """
        # Check for game state
        if self._get_poll_file_path(chat_id).exists():
            return True
        
        # Check for config
        if self._get_config_file_path(chat_id).exists():
            return True
        
        # Check for saves
        save_dir = self.data_dir / "saves" / str(chat_id)
        if save_dir.exists() and any(save_dir.iterdir()):
            return True
        
        return False
    
    def delete_all_chat_data(self, chat_id: int) -> bool:
        """Delete all data for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            True if any data was deleted
        """
        deleted = False
        
        # Delete game state
        if self.delete_game_state(chat_id):
            deleted = True
        
        # Delete config
        config_path = self._get_config_file_path(chat_id)
        if config_path.exists():
            config_path.unlink()
            deleted = True
        
        # Delete saves
        save_dir = self.data_dir / "saves" / str(chat_id)
        if save_dir.exists():
            import shutil
            shutil.rmtree(save_dir)
            deleted = True
        
        if deleted:
            logger.info(f"Deleted all data for chat {chat_id}")
        
        return deleted


# Singleton instance for convenience (lazy-loaded)
_state_manager: StateManager | None = None


def get_state_manager() -> StateManager:
    """Get the singleton StateManager instance.
    
    This is lazily loaded to avoid configuration errors at import time.
    
    Returns:
        StateManager singleton instance
    """
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager


# Module-level convenience reference
state_manager = get_state_manager
