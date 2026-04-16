"""Database manager for SQLite persistence.

This module provides a DatabaseManager class that replaces file-based
JSON storage with SQLite, maintaining the same public API as StateManager.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.db.connection import DatabaseConnection
from src.models.game_state import ChatConfig, ChatGameState, SaveSlotInfo, GameButton

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
            (chat_id, input_hold_frames, animation_duration, auto_save_enabled, modifier_states, message_base_text, maintenance_mode, language, platform, mirrors_chat_id, feature_flags, last_avatar_update_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            input_hold_frames = excluded.input_hold_frames,
            animation_duration = excluded.animation_duration,
            auto_save_enabled = excluded.auto_save_enabled,
            modifier_states = excluded.modifier_states,
            message_base_text = excluded.message_base_text,
            maintenance_mode = excluded.maintenance_mode,
            language = excluded.language,
            platform = excluded.platform,
            mirrors_chat_id = excluded.mirrors_chat_id,
            feature_flags = excluded.feature_flags,
            last_avatar_update_at = excluded.last_avatar_update_at,
            updated_at = excluded.updated_at;
        """

        self.connection.execute(sql, (
            config.chat_id,
            config.input_hold_frames,
            config.animation_duration,
            1 if config.auto_save_enabled else 0,
            json.dumps(config.modifier_states),
            config.message_base_text,
            1 if config.maintenance_mode else 0,
            config.language,
            config.platform,
            config.mirrors_chat_id,
            json.dumps(config.feature_flags),
            config.last_avatar_update_at.isoformat() if config.last_avatar_update_at else None,
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
            modifier_states=json.loads(row['modifier_states']) if row['modifier_states'] is not None else {},
            message_base_text=row['message_base_text'] if 'message_base_text' in row.keys() else None,
            maintenance_mode=bool(row['maintenance_mode']) if 'maintenance_mode' in row.keys() else False,
            language=row['language'] if 'language' in row.keys() else None,
            platform=row['platform'] if 'platform' in row.keys() else 'telegram',
            mirrors_chat_id=row['mirrors_chat_id'] if 'mirrors_chat_id' in row.keys() else None,
            feature_flags=json.loads(row['feature_flags']) if 'feature_flags' in row.keys() and row['feature_flags'] else {},
            last_avatar_update_at=datetime.fromisoformat(row['last_avatar_update_at']) if 'last_avatar_update_at' in row.keys() and row['last_avatar_update_at'] else None,
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

    def get_leaders_with_flag(self, flag: str) -> list[int]:
        """Get all leader chat IDs with a specific feature flag enabled.

        Args:
            flag: Feature flag name to check

        Returns:
            List of chat IDs that are leaders (mirrors_chat_id IS NULL) with the flag set to true
        """
        sql = "SELECT chat_id FROM chat_configs WHERE mirrors_chat_id IS NULL AND json_extract(feature_flags, '$.' || ?) = 1"
        cursor = self.connection.execute(sql, (flag,))
        return [row['chat_id'] for row in cursor.fetchall()]

    def get_mirror_chat_ids(self, leader_chat_id: int) -> list[int]:
        """Get all chat IDs that mirror the given leader chat.

        Args:
            leader_chat_id: The leader chat ID

        Returns:
            List of chat IDs that have mirrors_chat_id = leader_chat_id
        """
        sql = "SELECT chat_id FROM chat_configs WHERE mirrors_chat_id = ?;"
        cursor = self.connection.execute(sql, (leader_chat_id,))
        return [row['chat_id'] for row in cursor.fetchall()]

    # ==================== User Preferences ====================

    def get_user_preference(self, platform: str, user_id: int, key: str) -> Optional[str]:
        """Get a per-user preference value.

        Args:
            platform: Platform identifier (e.g. "discord", "telegram")
            user_id: Platform user ID (64-bit integer)
            key: Preference key

        Returns:
            The stored string value, or None if not set.
        """
        cursor = self.connection.execute(
            "SELECT value FROM user_preferences WHERE platform = ? AND user_id = ? AND key = ?;",
            (platform, user_id, key),
        )
        row = cursor.fetchone()
        return row["value"] if row is not None else None

    def set_user_preference(self, platform: str, user_id: int, key: str, value: str) -> None:
        """Set a per-user preference value (upsert).

        Args:
            platform: Platform identifier (e.g. "discord", "telegram")
            user_id: Platform user ID (64-bit integer)
            key: Preference key
            value: String value to store
        """
        self.connection.execute(
            """INSERT INTO user_preferences (platform, user_id, key, value)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(platform, user_id, key) DO UPDATE SET value = excluded.value;""",
            (platform, user_id, key, value),
        )
        self.connection.commit()

    # ==================== Game State ====================
    
    def save_game_state(self, state: ChatGameState, save_user_input_counts: bool = False) -> None:
        """Save game state to database.
        
        Args:
            state: The game state to save
            save_user_input_counts: Whether to save user input counts
        """
        sql = """
        INSERT INTO game_states
            (chat_id, message_id, input_in_progress, last_input, last_input_time,
             last_animation_file_id, global_frame_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            message_id = excluded.message_id,
            input_in_progress = excluded.input_in_progress,
            last_input = excluded.last_input,
            last_input_time = excluded.last_input_time,
            last_animation_file_id = excluded.last_animation_file_id,
            global_frame_count = excluded.global_frame_count,
            updated_at = excluded.updated_at;
        """

        self.connection.execute(sql, (
            state.chat_id,
            state.message_id,
            1 if state.input_in_progress else 0,
            state.last_input.value if state.last_input else None,
            state.last_input_time.isoformat() if state.last_input_time else None,
            state.last_animation_file_id,
            state.global_frame_count,
            state.created_at.isoformat() if state.created_at else datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat()
        ))
        
        # Save user input counts
        if save_user_input_counts:
            self._save_user_input_counts(state.chat_id, state.user_input_counts)
        
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
            last_animation_file_id=row['last_animation_file_id'],
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
            user_input_counts=self._load_user_input_counts(chat_id),
            global_frame_count=row['global_frame_count'] if row['global_frame_count'] is not None else 0,
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
        """No-op: recent_inputs is now an append-only log.

        Rows are inserted individually via append_recent_input.
        This method is kept for compatibility with save_game_state callers.
        """
        pass
    
    def _load_recent_inputs(self, chat_id: int, limit: int = 30, group_limit: int = 3) -> list:
        """Load recent inputs from database, reconstructing grouped view."""
        cursor = self.connection.execute(
            """SELECT user_id, user_name, button, timestamp
               FROM recent_inputs WHERE chat_id = ? ORDER BY timestamp DESC
               LIMIT ?;""",
            (chat_id, limit)
        )
        rows = list(cursor.fetchall())
        rows.reverse()  # Oldest first

        # Collapse consecutive same-user inputs into groups
        groups = []
        for row in rows:
            if groups and groups[-1]['user_id'] == row['user_id']:
                groups[-1]['buttons'].append(row['button'])
            else:
                groups.append({
                    'user_id': row['user_id'],
                    'user_name': row['user_name'],
                    'buttons': [row['button']] if row['button'] else [],
                    'timestamp': row['timestamp'],
                })

        return groups[-group_limit:] if len(groups) > group_limit else groups
    
    def append_recent_input(
        self,
        chat_id: int,
        user_id: int,
        user_name: str,
        button: str,
        timestamp: str,
        base_score: int = 0,
        streak_bonus: int = 0,
        total_score: int = 0,
        modifier: str | None = None,
        commit: bool = True,
    ) -> None:
        """Append a single button press to the recent_inputs log.

        Args:
            modifier: The modifier button value pressed alongside this input (e.g. "b"),
                or None if no modifier was active.
            commit: Whether to commit after inserting. Pass False when the caller
                will issue a batched commit after processing multiple inputs.
        """
        self.connection.execute(
            """INSERT INTO recent_inputs
               (chat_id, user_id, user_name, button, timestamp, base_score, streak_bonus, total_score, modifier)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            (chat_id, user_id, user_name, button, timestamp, base_score, streak_bonus, total_score, modifier)
        )
        if commit:
            self.connection.commit()

    def get_recent_inputs_for_overlay(
        self, chat_id: int, limit: int = 30
    ) -> list:
        """Get the most recent N input rows for sidebar overlay rendering.

        Returns a list of dicts with keys: user_id, user_name, button, timestamp,
        current_streak, modifier. Ordered oldest-first (suitable for rendering bottom-up).
        """
        cursor = self.connection.execute(
            """SELECT ri.user_id, ri.user_name, ri.button, ri.timestamp,
                      COALESCE(up.current_streak, 0) AS current_streak,
                      ri.modifier
               FROM recent_inputs ri
               LEFT JOIN user_player_profiles up ON ri.user_id = up.user_id
               WHERE ri.chat_id = ?
               ORDER BY ri.timestamp DESC LIMIT ?;""",
            (chat_id, limit)
        )
        rows = list(cursor.fetchall())
        rows.reverse()  # Oldest first
        return [
            {
                'user_id': row['user_id'],
                'user_name': row['user_name'],
                'button': row['button'],
                'timestamp': row['timestamp'],
                'current_streak': row['current_streak'],
                'modifier': row['modifier'],
            }
            for row in rows
        ]

    def get_today_input_stats(self, chat_id: int) -> dict:
        """Return total input count and top-3 players for today (UTC) for a chat.

        Returns:
            {"total": int, "top_players": [{"user_name": str, "count": int}, ...]}
        """
        from datetime import datetime, timezone
        today_midnight = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        total_row = self.connection.execute(
            "SELECT COUNT(*) as cnt FROM recent_inputs WHERE chat_id = ? AND timestamp >= ?;",
            (chat_id, today_midnight),
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

        cursor = self.connection.execute(
            """SELECT user_id, user_name, COUNT(*) as cnt
               FROM recent_inputs
               WHERE chat_id = ? AND timestamp >= ?
               GROUP BY user_id
               ORDER BY cnt DESC
               LIMIT 3;""",
            (chat_id, today_midnight),
        )
        top_players = [
            {"user_name": row["user_name"] or "?", "count": row["cnt"]}
            for row in cursor.fetchall()
        ]
        return {"total": total, "top_players": top_players}

    def get_alltime_input_stats(self, chat_id: int) -> dict:
        """Return total all-time input count and top-3 players for a chat.

        Sources counts from user_input_counts, names from user_player_profiles.

        Returns:
            {"total": int, "top_players": [{"user_name": str, "count": int}, ...]}
        """
        total_row = self.connection.execute(
            "SELECT COALESCE(SUM(input_count), 0) as total FROM user_input_counts WHERE chat_id = ?;",
            (chat_id,),
        ).fetchone()
        total = int(total_row["total"]) if total_row else 0

        cursor = self.connection.execute(
            """SELECT uic.user_id, up.user_name, uic.input_count as cnt
               FROM user_input_counts uic
               LEFT JOIN user_player_profiles up ON uic.user_id = up.user_id
               WHERE uic.chat_id = ?
               ORDER BY uic.input_count DESC
               LIMIT 3;""",
            (chat_id,),
        )
        top_players = [
            {"user_name": row["user_name"] or "?", "count": row["cnt"]}
            for row in cursor.fetchall()
        ]
        return {"total": total, "top_players": top_players}

    def get_player_today_input_count(self, chat_id: int, user_id: int) -> int:
        """Count inputs from user_id in recent_inputs since UTC midnight for chat_id."""
        from datetime import datetime, timezone
        today_midnight = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        row = self.connection.execute(
            "SELECT COUNT(*) as cnt FROM recent_inputs WHERE chat_id = ? AND user_id = ? AND timestamp >= ?;",
            (chat_id, user_id, today_midnight),
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def get_player_alltime_input_count(self, chat_id: int, user_id: int) -> int:
        """Return total input count from user_input_counts for user_id in chat_id."""
        row = self.connection.execute(
            "SELECT input_count FROM user_input_counts WHERE chat_id = ? AND user_id = ?;",
            (chat_id, user_id),
        ).fetchone()
        return int(row["input_count"]) if row else 0

    def purge_old_recent_inputs(self, older_than_days: int) -> int:
        """Delete recent_inputs rows older than N days.

        Returns the number of rows deleted. No-op if older_than_days == 0.
        """
        if older_than_days == 0:
            return 0

        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=older_than_days)).isoformat()
        cursor = self.connection.execute(
            "DELETE FROM recent_inputs WHERE timestamp < ?;",
            (cutoff,)
        )
        self.connection.commit()
        return cursor.rowcount

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
        """Get recap file metadata for a specific date (latest part).

        Returns the row with the highest part_number for (chat_id, date, is_rt=False).

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format

        Returns:
            RecapFileRecord if found, None otherwise
        """
        from src.models.game_state import RecapFileRecord

        sql = """
        SELECT * FROM recap_files
        WHERE chat_id = ? AND date = ?
        ORDER BY part_number DESC
        LIMIT 1;
        """
        cursor = self.connection.execute(sql, (chat_id, date))
        row = cursor.fetchone()

        if row is None:
            return None

        return RecapFileRecord(
            chat_id=row['chat_id'],
            date=row['date'],
            part_number=row['part_number'],
            is_rt=bool(row['is_rt']),
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
        file_size_bytes: int,
        part_number: int = 1,
        is_rt: bool = False,
    ) -> None:
        """Upsert recap file metadata, invalidating file_id.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format
            added_frame_count: Added frames in timelapse
            added_duration_sec: Duration in seconds
            file_size_bytes: File size in bytes
            part_number: Part number (1-based) for split recaps
            is_rt: Whether this is a realtime recap
        """
        now = datetime.utcnow()
        sql = """
        INSERT INTO recap_files
            (chat_id, date, part_number, is_rt, file_id, frame_count, duration_sec, file_size_bytes, created_at, updated_at)
        VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, date, part_number, is_rt) DO UPDATE SET
            file_id = NULL,
            frame_count = frame_count + excluded.frame_count,
            duration_sec = duration_sec + excluded.duration_sec,
            file_size_bytes = excluded.file_size_bytes,
            updated_at = excluded.updated_at;
        """

        self.connection.execute(sql, (
            chat_id, date, part_number, is_rt, added_frame_count, added_duration_sec, file_size_bytes,
            now.isoformat(), now.isoformat()
        ))
        self.connection.commit()
        logger.debug(f"Upserted recap metadata for chat {chat_id}, date {date}, part {part_number}, is_rt={is_rt}")

    async def update_recap_file_id(
        self,
        chat_id: int,
        date: str,
        part_number: int,
        is_rt: bool,
        file_id: str,
    ) -> None:
        """Update the Telegram file_id for a recap file part.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format
            part_number: Part number (1-based)
            is_rt: Whether this is a realtime recap
            file_id: Telegram file ID
        """
        sql = """
        UPDATE recap_files
        SET file_id = ?, updated_at = ?
        WHERE chat_id = ? AND date = ? AND part_number = ? AND is_rt = ?;
        """

        self.connection.execute(sql, (
            file_id, datetime.utcnow().isoformat(), chat_id, date, part_number, is_rt
        ))
        self.connection.commit()
        logger.debug(f"Updated recap file_id for chat {chat_id}, date {date}, part {part_number}, is_rt={is_rt}")

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
            SELECT DISTINCT date FROM recap_files
            WHERE chat_id = ? AND date < ?
            ORDER BY date DESC
            LIMIT 1;
            """
        elif direction == 'after':
            sql = """
            SELECT DISTINCT date FROM recap_files
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

    async def get_recap_parts(
        self,
        chat_id: int,
        date: str,
        is_rt: bool,
    ) -> list:
        """Get all recap file parts for a specific date, ordered by part_number.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format
            is_rt: Whether to fetch realtime recap parts

        Returns:
            List of RecapFileRecord ordered by part_number ascending
        """
        from src.models.game_state import RecapFileRecord

        sql = """
        SELECT * FROM recap_files
        WHERE chat_id = ? AND date = ? AND is_rt = ?
        ORDER BY part_number ASC;
        """
        cursor = self.connection.execute(sql, (chat_id, date, is_rt))
        rows = cursor.fetchall()

        return [
            RecapFileRecord(
                chat_id=row['chat_id'],
                date=row['date'],
                part_number=row['part_number'],
                is_rt=bool(row['is_rt']),
                file_id=row['file_id'],
                frame_count=row['frame_count'],
                duration_sec=row['duration_sec'],
                file_size_bytes=row['file_size_bytes'],
                created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
                updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
                auto_sent_at=datetime.fromisoformat(row['auto_sent_at']) if row['auto_sent_at'] else None,
            )
            for row in rows
        ]

    async def split_recap_part(
        self,
        chat_id: int,
        date: str,
        current_part_number: int,
        is_rt: bool,
    ) -> None:
        """Finalize current part and create a new empty next part.

        Nullifies file_id on the current part row and inserts a new row for
        part_number = current_part_number + 1.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format
            current_part_number: The part number being finalized
            is_rt: Whether this is a realtime recap
        """
        now = datetime.utcnow().isoformat()
        next_part = current_part_number + 1

        self.connection.execute(
            "UPDATE recap_files SET file_id = NULL WHERE chat_id = ? AND date = ? AND part_number = ? AND is_rt = ?;",
            (chat_id, date, current_part_number, is_rt),
        )
        self.connection.execute(
            """INSERT INTO recap_files
               (chat_id, date, part_number, is_rt, frame_count, duration_sec, file_size_bytes, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, 0.0, 0, ?, ?);""",
            (chat_id, date, next_part, is_rt, now, now),
        )
        self.connection.commit()
        logger.debug(f"Split recap for chat {chat_id}, date {date}: part {current_part_number} -> {next_part}, is_rt={is_rt}")

    async def mark_recap_part_auto_sent(
        self,
        chat_id: int,
        date: str,
        part_number: int,
        is_rt: bool,
    ) -> None:
        """Mark a recap part as auto-sent by setting auto_sent_at timestamp."""
        now = datetime.utcnow().isoformat()
        self.connection.execute(
            "UPDATE recap_files SET auto_sent_at = ? WHERE chat_id = ? AND date = ? AND part_number = ? AND is_rt = ?;",
            (now, chat_id, date, part_number, is_rt),
        )
        self.connection.commit()
        logger.debug(
            f"Marked recap part {part_number} as auto-sent for chat {chat_id}, date {date}, is_rt={is_rt}"
        )

    async def get_unsent_recap_parts(
        self,
        chat_id: int,
        date: str,
        is_rt: bool,
    ) -> list:
        """Get recap parts not yet auto-sent (auto_sent_at IS NULL), ordered by part_number."""
        from src.models.game_state import RecapFileRecord

        sql = """
        SELECT * FROM recap_files
        WHERE chat_id = ? AND date = ? AND is_rt = ? AND auto_sent_at IS NULL
        ORDER BY part_number ASC;
        """
        cursor = self.connection.execute(sql, (chat_id, date, is_rt))
        rows = cursor.fetchall()

        return [
            RecapFileRecord(
                chat_id=row['chat_id'],
                date=row['date'],
                part_number=row['part_number'],
                is_rt=bool(row['is_rt']),
                file_id=row['file_id'],
                frame_count=row['frame_count'],
                duration_sec=row['duration_sec'],
                file_size_bytes=row['file_size_bytes'],
                created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
                updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
                auto_sent_at=datetime.fromisoformat(row['auto_sent_at']) if row['auto_sent_at'] else None,
            )
            for row in rows
        ]

    # ==================== Reaction Queue ====================

    def enqueue_reaction(
        self, chat_id: int, user_id: int, user_name: str, reaction_type: str
    ) -> None:
        """Insert a reaction into the queue for a chat."""
        self.connection.execute(
            "INSERT INTO reaction_queue (chat_id, user_id, user_name, reaction_type) "
            "VALUES (?, ?, ?, ?);",
            (chat_id, user_id, user_name, reaction_type),
        )
        self.connection.commit()

    def list_next_reactions(self, chat_id: int, limit: int = 3) -> list[dict]:
        """List up to `limit` oldest reactions for a chat.

        Returns a list of dicts with keys: id, user_name, reaction_type.
        """
        rows = self.connection.execute(
            "SELECT id, user_name, reaction_type FROM reaction_queue "
            "WHERE chat_id = ? ORDER BY id ASC LIMIT ?;",
            (chat_id, limit),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "user_name": row["user_name"],
                "reaction_type": row["reaction_type"],
            }
            for row in rows
        ]

    def delete_reactions(self, ids: list[int]) -> None:
        """Delete queued reactions by row ID."""
        if not ids:
            return

        placeholders = ",".join("?" * len(ids))
        self.connection.execute(
            f"DELETE FROM reaction_queue WHERE id IN ({placeholders});",
            tuple(ids),
        )
        self.connection.commit()
