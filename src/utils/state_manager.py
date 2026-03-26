"""State management using SQLite database persistence.

This module provides functionality for saving and loading game state,
including rotating save slots, chat-specific configuration, and poll state.

NOTE: This module now uses DatabaseManager (SQLite) instead of file-based storage.
The migration from JSON files to SQLite was performed by migrate_to_sqlite.py.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.config import settings
from src.db import DatabaseManager
from src.models.game_state import SaveSlotInfo, TimelapseJobRow

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


    # ==================== Timelapse Jobs ====================

    def insert_timelapse_job(
        self,
        chat_id: str,
        folder_path: str,
        timestamp: str,
        fps: int,
        compositing_context: dict,
    ) -> int:
        """Insert a new pending timelapse job and return its ID.

        Args:
            chat_id: Chat ID as string.
            folder_path: Absolute path to the folder containing .npy frame files.
            timestamp: ISO8601 timestamp of the batch capture.
            fps: Output FPS for the timelapse video.
            compositing_context: Dict with frame/sidebar/reaction data.

        Returns:
            The new row's ID.
        """
        now = datetime.utcnow().isoformat()
        sql = """
            INSERT INTO timelapse_jobs
                (chat_id, folder_path, timestamp, fps, compositing_context, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """
        cursor = self.connection.execute(
            sql, (str(chat_id), folder_path, timestamp, fps, json.dumps(compositing_context), now, now)
        )
        self.connection.commit()
        return cursor.lastrowid

    def fetch_next_pending_job(self, chat_id: str) -> Optional[TimelapseJobRow]:
        """Fetch the oldest pending timelapse job for a chat, or None.

        Args:
            chat_id: Chat ID as string.

        Returns:
            TimelapseJobRow or None if no pending jobs exist.
        """
        sql = """
            SELECT * FROM timelapse_jobs
            WHERE chat_id = ? AND status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
        """
        cursor = self.connection.execute(sql, (str(chat_id),))
        row = cursor.fetchone()
        if row is None:
            return None
        ctx = json.loads(row['compositing_context'])
        return TimelapseJobRow(
            id=row['id'],
            chat_id=row['chat_id'],
            folder_path=row['folder_path'],
            timestamp=row['timestamp'],
            fps=row['fps'],
            compositing_context=ctx,
            frame_count=ctx.get('frame_count', 0),
            status=row['status'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )

    def update_job_status(self, job_id: int, status: str) -> None:
        """Update the status of a timelapse job.

        Args:
            job_id: DB row ID.
            status: New status string ('pending', 'processing', 'done', 'failed').
        """
        now = datetime.utcnow().isoformat()
        self.connection.execute(
            "UPDATE timelapse_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, job_id),
        )
        self.connection.commit()

    def reset_stuck_jobs(self) -> int:
        """Reset all 'processing' jobs back to 'pending' (crash recovery).

        Returns:
            Number of rows reset.
        """
        now = datetime.utcnow().isoformat()
        cursor = self.connection.execute(
            "UPDATE timelapse_jobs SET status = 'pending', updated_at = ? WHERE status = 'processing'",
            (now,),
        )
        self.connection.commit()
        count = cursor.rowcount
        if count > 0:
            logger.info(f"reset_stuck_jobs: reset {count} stuck timelapse job(s) to pending")
        return count

    def prune_done_jobs(self, older_than_days: int) -> int:
        """Delete 'done' timelapse jobs whose updated_at is older than the threshold.

        Returns:
            Number of rows deleted.
        """
        if older_than_days <= 0:
            return 0
        cutoff = (datetime.utcnow() - timedelta(days=older_than_days)).isoformat()
        cursor = self.connection.execute(
            "DELETE FROM timelapse_jobs WHERE status = 'done' AND updated_at < ?",
            (cutoff,),
        )
        self.connection.commit()
        count = cursor.rowcount
        if count > 0:
            logger.info(f"prune_done_jobs: deleted {count} done timelapse job(s) older than {older_than_days}d")
        return count

    def get_chats_with_pending_jobs(self) -> list:
        """Return a list of distinct chat_ids that have pending timelapse jobs."""
        cursor = self.connection.execute(
            "SELECT DISTINCT chat_id FROM timelapse_jobs WHERE status = 'pending'"
        )
        return [row['chat_id'] for row in cursor.fetchall()]

    def cleanup_orphaned_folders(self) -> int:
        """Delete frame folders under data/frames/ that have no DB row.

        A folder is considered orphaned when it was written during a crash
        before the DB row could be inserted, making it unrecoverable.

        Returns:
            Number of folders deleted.
        """
        frames_root = settings.data_dir / "frames"
        if not frames_root.exists():
            return 0

        # Collect all known folder paths from DB
        cursor = self.connection.execute("SELECT folder_path FROM timelapse_jobs")
        known_paths = {row['folder_path'] for row in cursor.fetchall()}

        deleted = 0
        for chat_dir in frames_root.iterdir():
            if not chat_dir.is_dir():
                continue
            for job_dir in chat_dir.iterdir():
                if not job_dir.is_dir():
                    continue
                if str(job_dir) not in known_paths:
                    try:
                        shutil.rmtree(job_dir)
                        deleted += 1
                        logger.info(f"cleanup_orphaned_folders: removed {job_dir}")
                    except Exception as e:
                        logger.warning(f"cleanup_orphaned_folders: failed to remove {job_dir}: {e}")

        return deleted


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
