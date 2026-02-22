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
            (chat_id, input_hold_frames, animation_duration, auto_save_enabled, running_mode, message_base_text, maintenance_mode, language, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            input_hold_frames = excluded.input_hold_frames,
            animation_duration = excluded.animation_duration,
            auto_save_enabled = excluded.auto_save_enabled,
            running_mode = excluded.running_mode,
            message_base_text = excluded.message_base_text,
            maintenance_mode = excluded.maintenance_mode,
            language = excluded.language,
            updated_at = excluded.updated_at;
        """

        self.connection.execute(sql, (
            config.chat_id,
            config.input_hold_frames,
            config.animation_duration,
            1 if config.auto_save_enabled else 0,
            1 if config.running_mode else 0,
            config.message_base_text,
            1 if config.maintenance_mode else 0,
            config.language,
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
            message_base_text=row['message_base_text'] if 'message_base_text' in row.keys() else None,
            maintenance_mode=bool(row['maintenance_mode']) if 'maintenance_mode' in row.keys() else False,
            language=row['language'] if 'language' in row.keys() else None,
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
            (chat_id, message_id, input_in_progress, last_input, last_input_time, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            message_id = excluded.message_id,
            input_in_progress = excluded.input_in_progress,
            last_input = excluded.last_input,
            last_input_time = excluded.last_input_time,
            updated_at = excluded.updated_at;
        """
        
        self.connection.execute(sql, (
            state.chat_id,
            state.message_id,
            1 if state.input_in_progress else 0,
            state.last_input.value if state.last_input else None,
            state.last_input_time.isoformat() if state.last_input_time else None,
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
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
            user_input_counts=self._load_user_input_counts(chat_id),
            recent_inputs=self._load_recent_inputs(chat_id),
            input_queue=self._load_input_queue(chat_id)
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
    
    # ==================== Input Queue ====================
    
    def _save_input_queue(self, chat_id: int, queue: InputQueue) -> None:
        """Save input queue to database."""
        # Delete existing queue items (cascade deletes buttons)
        self.connection.execute(
            "DELETE FROM input_queue_items WHERE chat_id = ?;",
            (chat_id,)
        )
        
        # Insert queue items
        for position, item in enumerate(queue.items):
            cursor = self.connection.execute(
                """INSERT INTO input_queue_items 
                    (chat_id, position, user_id, user_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?);""",
                (chat_id, position, item.user_id, item.user_name, 
                 item.created_at.isoformat(), item.updated_at.isoformat())
            )
            item_id = cursor.lastrowid
            
            # Insert buttons for this item
            for btn_position, button in enumerate(item.buttons):
                self.connection.execute(
                    """INSERT INTO input_queue_buttons 
                        (queue_item_id, button, position)
                       VALUES (?, ?, ?);""",
                    (item_id, button.value, btn_position)
                )
    
    def _load_input_queue(self, chat_id: int) -> Optional[InputQueue]:
        """Load input queue from database."""
        cursor = self.connection.execute(
            """SELECT id, position, user_id, user_name, created_at, updated_at
               FROM input_queue_items
               WHERE chat_id = ?
               ORDER BY position;""",
            (chat_id,)
        )
        
        items = []
        for row in cursor.fetchall():
            # Load buttons for this item
            btn_cursor = self.connection.execute(
                """SELECT button FROM input_queue_buttons
                   WHERE queue_item_id = ?
                   ORDER BY position;""",
                (row['id'],)
            )
            buttons = [GameButton(btn_row['button']) for btn_row in btn_cursor.fetchall()]
            
            item = QueueItem(
                user_id=row['user_id'],
                user_name=row['user_name'],
                buttons=buttons,
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at'])
            )
            items.append(item)
        
        if not items:
            return None
        
        queue = InputQueue()
        queue.items = items
        return queue
    
    # ==================== Save Slots ====================
    
    def save_to_slot(
        self,
        chat_id: int,
        slot_number: int,
        state_data: bytes,
        state_file_path: Path,
        description: Optional[str] = None,
        is_auto_save: bool = False,
    ) -> SaveSlotInfo:
        """Save game state to a specific slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number to save to
            state_data: The raw save state bytes from PyBoy
            state_file_path: Path where to save the binary state file
            description: Optional description of the save
            is_auto_save: Whether this is an auto-save
            
        Returns:
            SaveSlotInfo with metadata about the save
        """
        # Ensure parent directory exists
        state_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save binary state data to file
        with open(state_file_path, "wb") as f:
            f.write(state_data)
        
        # Save metadata to database
        now = datetime.utcnow()
        sql = """
        INSERT INTO save_slots 
            (chat_id, slot_number, is_auto_save, description, created_at, updated_at, state_file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, slot_number) DO UPDATE SET
            is_auto_save = excluded.is_auto_save,
            description = excluded.description,
            updated_at = excluded.updated_at,
            state_file_path = excluded.state_file_path;
        """
        
        self.connection.execute(sql, (
            chat_id, slot_number, 1 if is_auto_save else 0, description,
            now.isoformat(), now.isoformat(), str(state_file_path)
        ))
        self.connection.commit()
        
        info = SaveSlotInfo(
            slot_number=slot_number,
            created_at=now,
            updated_at=now,
            is_auto_save=is_auto_save,
            description=description
        )
        
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
        sql = "SELECT state_file_path FROM save_slots WHERE chat_id = ? AND slot_number = ?;"
        cursor = self.connection.execute(sql, (chat_id, slot_number))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        state_file_path = Path(row['state_file_path'])
        
        if not state_file_path.exists():
            logger.error(f"State file missing for chat {chat_id}, slot {slot_number}")
            return None
        
        try:
            with open(state_file_path, "rb") as f:
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
        sql = "SELECT * FROM save_slots WHERE chat_id = ? AND slot_number = ?;"
        cursor = self.connection.execute(sql, (chat_id, slot_number))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        return SaveSlotInfo(
            slot_number=row['slot_number'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
            is_auto_save=bool(row['is_auto_save']),
            description=row['description']
        )
    
    def list_save_slots(self, chat_id: int, max_slots: int | None = None) -> list[SaveSlotInfo]:
        """List all save slots for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            max_slots: Maximum number of slots to check (ignored, kept for compatibility)
            
        Returns:
            List of SaveSlotInfo for existing slots
        """
        sql = "SELECT * FROM save_slots WHERE chat_id = ? ORDER BY slot_number;"
        cursor = self.connection.execute(sql, (chat_id,))
        
        slots = []
        for row in cursor.fetchall():
            slots.append(SaveSlotInfo(
                slot_number=row['slot_number'],
                created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
                updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
                is_auto_save=bool(row['is_auto_save']),
                description=row['description']
            ))
        
        return slots
    
    def delete_slot(self, chat_id: int, slot_number: int) -> bool:
        """Delete a save slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number to delete
            
        Returns:
            True if deleted, False if didn't exist
        """
        # Get file path before deleting
        sql = "SELECT state_file_path FROM save_slots WHERE chat_id = ? AND slot_number = ?;"
        cursor = self.connection.execute(sql, (chat_id, slot_number))
        row = cursor.fetchone()
        
        if row is None:
            return False
        
        # Delete file
        state_file_path = Path(row['state_file_path'])
        if state_file_path.exists():
            state_file_path.unlink()
        
        # Delete from database
        sql = "DELETE FROM save_slots WHERE chat_id = ? AND slot_number = ?;"
        self.connection.execute(sql, (chat_id, slot_number))
        self.connection.commit()
        
        logger.info(f"Deleted slot {slot_number} for chat {chat_id}")
        return True
    
    def find_next_auto_save_slot(self, chat_id: int, num_slots: int | None = None) -> int:
        """Find the next slot for auto-save using round-robin.
        
        Args:
            chat_id: The Telegram chat ID
            num_slots: Total number of slots (default: 5)
            
        Returns:
            Slot number for next auto-save
        """
        max_slots = num_slots if num_slots is not None else 5
        
        sql = """SELECT slot_number FROM save_slots 
                 WHERE chat_id = ? AND is_auto_save = 1
                 ORDER BY slot_number;"""
        cursor = self.connection.execute(sql, (chat_id,))
        auto_saves = [row['slot_number'] for row in cursor.fetchall()]
        
        if not auto_saves:
            return 0
        
        max_slot = max(auto_saves)
        return (max_slot + 1) % max_slots
    
    # ==================== Utility Methods ====================
    
    def chat_exists(self, chat_id: int) -> bool:
        """Check if any data exists for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            True if chat has any saved data
        """
        # Check for game state
        cursor = self.connection.execute(
            "SELECT 1 FROM game_states WHERE chat_id = ? LIMIT 1;",
            (chat_id,)
        )
        if cursor.fetchone():
            return True
        
        # Check for config
        cursor = self.connection.execute(
            "SELECT 1 FROM chat_configs WHERE chat_id = ? LIMIT 1;",
            (chat_id,)
        )
        if cursor.fetchone():
            return True
        
        # Check for saves
        cursor = self.connection.execute(
            "SELECT 1 FROM save_slots WHERE chat_id = ? LIMIT 1;",
            (chat_id,)
        )
        if cursor.fetchone():
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
        
        # Delete game state (cascade deletes user_input_counts, recent_inputs, queue)
        if self.delete_game_state(chat_id):
            deleted = True
        
        # Delete config
        cursor = self.connection.execute(
            "DELETE FROM chat_configs WHERE chat_id = ?;",
            (chat_id,)
        )
        if cursor.rowcount > 0:
            deleted = True
        
        # Delete saves (delete files first)
        cursor = self.connection.execute(
            "SELECT state_file_path FROM save_slots WHERE chat_id = ?;",
            (chat_id,)
        )
        for row in cursor.fetchall():
            state_file_path = Path(row['state_file_path'])
            if state_file_path.exists():
                state_file_path.unlink()
        
        cursor = self.connection.execute(
            "DELETE FROM save_slots WHERE chat_id = ?;",
            (chat_id,)
        )
        if cursor.rowcount > 0:
            deleted = True
        
        self.connection.commit()
        
        if deleted:
            logger.info(f"Deleted all data for chat {chat_id}")

        return deleted

    # ==================== Recap Files ====================

    async def get_recap_file(self, chat_id: int, date: str) -> Optional["RecapFileRecord"]:
        """Get recap file metadata for a specific date.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format

        Returns:
            RecapFileRecord if found, None otherwise
        """
        from src.models.game_state import RecapFileRecord

        sql = "SELECT * FROM recap_files WHERE chat_id = ? AND date = ?;"
        cursor = self.connection.execute(sql, (chat_id, date))
        row = cursor.fetchone()

        if row is None:
            return None

        return RecapFileRecord(
            chat_id=row['chat_id'],
            date=row['date'],
            file_id=row['file_id'],
            frame_count=row['frame_count'],
            duration_sec=row['duration_sec'],
            file_size_bytes=row['file_size_bytes'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None
        )

    async def upsert_recap_metadata(
        self,
        chat_id: int,
        date: str,
        added_frame_count: int,
        added_duration_sec: float,
        file_size_bytes: int
    ) -> None:
        """Upsert recap file metadata, invalidating file_id.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format
            added_frame_count: Added frames in timelapse
            duration_sec: Duration in seconds
            file_size_bytes: File size in bytes
        """
        now = datetime.utcnow()
        sql = """
        INSERT INTO recap_files
            (chat_id, date, file_id, frame_count, duration_sec, file_size_bytes, created_at, updated_at)
        VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, date) DO UPDATE SET
            file_id = NULL,
            frame_count = frame_count + excluded.frame_count,
            duration_sec = duration_sec + excluded.duration_sec,
            file_size_bytes = excluded.file_size_bytes,
            updated_at = excluded.updated_at;
        """

        self.connection.execute(sql, (
            chat_id, date, added_frame_count, added_duration_sec, file_size_bytes,
            now.isoformat(), now.isoformat()
        ))
        self.connection.commit()
        logger.debug(f"Upserted recap metadata for chat {chat_id}, date {date}")

    async def update_recap_file_id(self, chat_id: int, date: str, file_id: str) -> None:
        """Update the Telegram file_id for a recap file.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format
            file_id: Telegram file ID
        """
        sql = """
        UPDATE recap_files
        SET file_id = ?, updated_at = ?
        WHERE chat_id = ? AND date = ?;
        """

        self.connection.execute(sql, (
            file_id, datetime.utcnow().isoformat(), chat_id, date
        ))
        self.connection.commit()
        logger.debug(f"Updated recap file_id for chat {chat_id}, date {date}")

    async def get_nearest_recap_date(
        self,
        chat_id: int,
        date: str,
        direction: str
    ) -> Optional[str]:
        """Find the nearest recap date before or after a given date.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format
            direction: 'before' or 'after'

        Returns:
            Nearest date in YYYYMMDD format, or None if not found
        """
        if direction == 'before':
            sql = """
            SELECT date FROM recap_files
            WHERE chat_id = ? AND date < ?
            ORDER BY date DESC
            LIMIT 1;
            """
        elif direction == 'after':
            sql = """
            SELECT date FROM recap_files
            WHERE chat_id = ? AND date > ?
            ORDER BY date ASC
            LIMIT 1;
            """
        else:
            raise ValueError(f"Invalid direction: {direction}")

        cursor = self.connection.execute(sql, (chat_id, date))
        row = cursor.fetchone()

        if row is None:
            return None

        return row['date']
