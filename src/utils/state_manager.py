"""State management using SQLite database persistence.

This module provides functionality for saving and loading game state,
including rotating save slots, chat-specific configuration, and poll state.

NOTE: This module now uses DatabaseManager (SQLite) instead of file-based storage.
The migration from JSON files to SQLite was performed by migrate_to_sqlite.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src.config import settings
from src.db import DatabaseManager
from src.models.game_state import SaveSlotInfo

logger = logging.getLogger(__name__)


class StateManager(DatabaseManager):
    """Manages SQLite-based persistence for game state.
    
    This class extends DatabaseManager for backward compatibility.
    All data is stored in SQLite database at data/bot.db.
    
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
        if data_dir is None:
            data_dir = settings.data_dir
        
        self.data_dir = Path(data_dir)
        db_path = self.data_dir / "bot.db"
        super().__init__(db_path)
        self.initialize()
    
    # ==================== Backward Compatibility ====================
    
    def get_save_slot_path(self, chat_id: int, slot_number: int) -> Path:
        """Get the file path for a save slot (backward compatibility).
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number
            
        Returns:
            Path to the save slot file
        """
        return self.data_dir / "saves" / str(chat_id) / f"slot_{slot_number}.state"
    
    def get_save_info_path(self, chat_id: int, slot_number: int) -> Path:
        """Get the file path for save slot metadata (backward compatibility).
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number
            
        Returns:
            Path to the save info JSON file
        """
        return self.data_dir / "saves" / str(chat_id) / f"slot_{slot_number}.json"
    
    def save_to_slot(
        self,
        chat_id: int,
        slot_number: int,
        state_data: bytes,
        description: Optional[str] = None,
        is_auto_save: bool = False,
    ) -> SaveSlotInfo:
        """Save game state to a specific slot (backward compatible signature).
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number to save to
            state_data: The raw save state bytes from PyBoy
            description: Optional description of the save
            is_auto_save: Whether this is an auto-save
            
        Returns:
            SaveSlotInfo with metadata about the save
        """
        state_path = self.get_save_slot_path(chat_id, slot_number)
        return super().save_to_slot(
            chat_id=chat_id,
            slot_number=slot_number,
            state_data=state_data,
            state_file_path=state_path,
            description=description,
            is_auto_save=is_auto_save,
        )
    
    def find_next_auto_save_slot(self, chat_id: int, num_slots: int | None = None) -> int:
        """Find the next slot for auto-save using round-robin (backward compatible).
        
        Args:
            chat_id: The Telegram chat ID
            num_slots: Total number of slots (default: settings.save_slots)
            
        Returns:
            Slot number for next auto-save
        """
        max_slots = num_slots if num_slots is not None else getattr(settings, 'save_slots', 5)
        
        sql = """SELECT slot_number FROM save_slots 
                 WHERE chat_id = ? AND is_auto_save = 1
                 ORDER BY slot_number;"""
        cursor = self.connection.execute(sql, (chat_id,))
        auto_saves = [row['slot_number'] for row in cursor.fetchall()]
        
        if not auto_saves:
            return 0
        
        max_slot = max(auto_saves)
        return (max_slot + 1) % max_slots


# Singleton instance for convenience (lazy-loaded)
_state_manager: 'StateManager | None' = None


def get_state_manager() -> 'StateManager':
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
state_manager = get_state_manager()
