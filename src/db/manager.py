"""Database manager for SQLite persistence.

This module provides a DatabaseManager class that replaces file-based
JSON storage with SQLite, maintaining the same public API as StateManager.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.db.connection import DatabaseConnection
from src.models.game_state import ChatConfig, ChatGameState, SaveSlotInfo, GameButton
from src.models.input_queue import InputQueue, QueueItem

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite persistence for game state.
    
    This class provides the same interface as the original StateManager
    but uses SQLite instead of JSON files for structured data.
    Binary save state files remain on the filesystem.
    
    Example:
        >>> manager = DatabaseManager()
        >>> manager.initialize()
        >>> manager.save_chat_config(ChatConfig(chat_id=123))
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """Initialize the database manager.
        
        Args:
            db_path: Path to SQLite database. If None, uses settings.
        """
        if db_path is None:
            from src.config import settings
            db_path = Path(settings.data_dir) / "bot.db"
        
        self.connection = DatabaseConnection(db_path)
    
    def initialize(self) -> None:
        """Initialize database schema.
        
        Safe to call multiple times. Creates tables if they don't exist.
        """
        self.connection.initialize()
    
    def close(self) -> None:
        """Close database connection."""
        self.connection.close()
    
    # ==================== Chat Config ====================
    
    def save_chat_config(self, config: ChatConfig) -> None:
        """Save chat configuration to database.
        
        Args:
            config: The chat configuration to save
        """
        sql = """
        INSERT INTO chat_configs 
            (chat_id, input_hold_frames, animation_duration, auto_save_enabled, running_mode, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            input_hold_frames = excluded.input_hold_frames,
            animation_duration = excluded.animation_duration,
            auto_save_enabled = excluded.auto_save_enabled,
            running_mode = excluded.running_mode,
            updated_at = excluded.updated_at;
        """
        
        self.connection.execute(sql, (
            config.chat_id,
            config.input_hold_frames,
            config.animation_duration,
            1 if config.auto_save_enabled else 0,
            1 if config.running_mode else 0,
            config.created_at.isoformat() if config.created_at else datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat()
        ))
        self.connection.commit()
        logger.debug(f"Saved chat config for chat {config.chat_id}")
    
    def load_chat_config(self, chat_id: int) -> Optional[ChatConfig]:
        """Load chat configuration from database.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            The saved configuration, or None if not found
        """
        sql = "SELECT * FROM chat_configs WHERE chat_id = ?;"
        cursor = self.connection.execute(sql, (chat_id,))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        config = ChatConfig(
            chat_id=row['chat_id'],
            input_hold_frames=row['input_hold_frames'],
            animation_duration=row['animation_duration'],
            auto_save_enabled=bool(row['auto_save_enabled']),
            running_mode=bool(row['running_mode']),
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at'])
        )
        
        logger.debug(f"Loaded chat config for chat {chat_id}")
        return config
    
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
