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
    
    # ==================== Game State ====================
    
    def save_game_state(self, state: ChatGameState) -> None:
        """Save game state to database.
        
        Args:
            state: The game state to save
        """
        sql = """
        INSERT INTO game_states 
            (chat_id, message_id, input_in_progress, last_input, last_input_time, frame_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            message_id = excluded.message_id,
            input_in_progress = excluded.input_in_progress,
            last_input = excluded.last_input,
            last_input_time = excluded.last_input_time,
            frame_hash = excluded.frame_hash,
            updated_at = excluded.updated_at;
        """
        
        self.connection.execute(sql, (
            state.chat_id,
            state.message_id,
            1 if state.input_in_progress else 0,
            state.last_input.value if state.last_input else None,
            state.last_input_time.isoformat() if state.last_input_time else None,
            state.frame_hash,
            state.created_at.isoformat() if state.created_at else datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat()
        ))
        
        # Save user input counts
        self._save_user_input_counts(state.chat_id, state.user_input_counts)
        
        # Save recent inputs
        self._save_recent_inputs(state.chat_id, state.recent_inputs)
        
        self.connection.commit()
        logger.debug(f"Saved game state for chat {state.chat_id}")
    
    def load_game_state(self, chat_id: int) -> Optional[ChatGameState]:
        """Load game state from database.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            The saved game state, or None if not found
        """
        sql = "SELECT * FROM game_states WHERE chat_id = ?;"
        cursor = self.connection.execute(sql, (chat_id,))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        state = ChatGameState(
            chat_id=row['chat_id'],
            message_id=row['message_id'],
            input_in_progress=bool(row['input_in_progress']),
            last_input=GameButton(row['last_input']) if row['last_input'] else None,
            last_input_time=datetime.fromisoformat(row['last_input_time']) if row['last_input_time'] else None,
            frame_hash=row['frame_hash'],
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
            user_input_counts=self._load_user_input_counts(chat_id),
            recent_inputs=self._load_recent_inputs(chat_id),
            input_queue=None  # Will be implemented in Task 5
        )
        
        logger.debug(f"Loaded game state for chat {chat_id}")
        return state
    
    def delete_game_state(self, chat_id: int) -> bool:
        """Delete game state for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            True if deleted, False if didn't exist
        """
        sql = "DELETE FROM game_states WHERE chat_id = ?;"
        cursor = self.connection.execute(sql, (chat_id,))
        self.connection.commit()
        
        if cursor.rowcount > 0:
            logger.debug(f"Deleted game state for chat {chat_id}")
            return True
        return False
    
    def _save_user_input_counts(self, chat_id: int, counts: dict) -> None:
        """Save user input counts to database."""
        # Delete existing counts
        self.connection.execute(
            "DELETE FROM user_input_counts WHERE chat_id = ?;", 
            (chat_id,)
        )
        
        # Insert new counts
        for user_id_str, count in counts.items():
            user_id = int(user_id_str)  # Convert from string to int
            self.connection.execute(
                "INSERT INTO user_input_counts (chat_id, user_id, input_count) VALUES (?, ?, ?);",
                (chat_id, user_id, count)
            )
    
    def _load_user_input_counts(self, chat_id: int) -> dict:
        """Load user input counts from database."""
        cursor = self.connection.execute(
            "SELECT user_id, input_count FROM user_input_counts WHERE chat_id = ?;",
            (chat_id,)
        )
        return {str(row['user_id']): row['input_count'] for row in cursor.fetchall()}
    
    def _save_recent_inputs(self, chat_id: int, inputs: list) -> None:
        """Save recent inputs to database."""
        # Delete existing inputs
        self.connection.execute(
            "DELETE FROM recent_inputs WHERE chat_id = ?;",
            (chat_id,)
        )
        
        # Insert new inputs
        for inp in inputs:
            self.connection.execute(
                """INSERT INTO recent_inputs 
                    (chat_id, user_id, user_name, button, timestamp) 
                   VALUES (?, ?, ?, ?, ?);""",
                (chat_id, inp['user_id'], inp['user_name'], inp['buttons'][0] if inp['buttons'] else None, inp['timestamp'])
            )
    
    def _load_recent_inputs(self, chat_id: int) -> list:
        """Load recent inputs from database."""
        cursor = self.connection.execute(
            """SELECT user_id, user_name, button, timestamp 
               FROM recent_inputs WHERE chat_id = ? ORDER BY timestamp;""",
            (chat_id,)
        )
        
        inputs = []
        for row in cursor.fetchall():
            inputs.append({
                'user_id': row['user_id'],
                'user_name': row['user_name'],
                'buttons': [row['button']] if row['button'] else [],
                'timestamp': row['timestamp']
            })
        return inputs
