"""Backup manager for automatic hourly game state backups.

Stores binary .state files at data/backups/{chat_id}/backup_{YYYYMMDD}_{HH}.state.
No new DB table is used; active-chat detection queries the existing recent_inputs table.
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class BackupManager:
    """Manages hourly automatic backups of game states.

    Args:
        state_manager: StateManager (DatabaseManager) instance for DB queries.
        game_controller_manager: GameControllerManager for save_state().
        settings: Application settings object.
    """

    def __init__(self, state_manager, game_controller_manager, settings):
        self._state_manager = state_manager
        self._game_controller_manager = game_controller_manager
        self._settings = settings

    async def get_active_chat_ids(self) -> list[int]:
        """Return chat_ids with activity in the last 24 hours."""
        cursor = self._state_manager.connection.execute(
            """SELECT DISTINCT chat_id FROM recent_inputs
               WHERE timestamp >= datetime('now', '-24 hours');"""
        )
        return [row["chat_id"] for row in cursor.fetchall()]

    async def create_backup(self, chat_id: int) -> bool:
        """Save current game state for chat_id to this hour's backup file.

        Skips (returns True) if:
        - This hour's backup already exists, or
        - No recent_inputs rows found in the past 60 minutes (noop guard).

        Returns False if no game controller is available.
        """
        now = datetime.now(timezone.utc)
        hour_str = now.strftime("%Y%m%d_%H")
        path = self._settings.get_chat_backup_dir(chat_id) / f"backup_{hour_str}.state"

        if path.exists():
            logger.debug(f"Backup already exists for chat {chat_id} hour {hour_str}")
            return True

        # Noop guard: skip if no activity in the past 60 minutes
        cursor = self._state_manager.connection.execute(
            """SELECT COUNT(*) as cnt FROM recent_inputs
               WHERE chat_id = ? AND timestamp >= datetime('now', '-60 minutes');""",
            (chat_id,),
        )
        row = cursor.fetchone()
        if row["cnt"] == 0:
            logger.debug(f"No recent activity for chat {chat_id}; skipping backup")
            return True

        controller = await self._game_controller_manager.get_or_create_controller(chat_id)
        if controller is None:
            logger.warning(f"No controller available for chat {chat_id}; skipping backup")
            return False

        state_data = controller.save_state()
        path.write_bytes(state_data)
        logger.info(f"Created backup for chat {chat_id} at {path}")
        return True

    def load_backup(self, chat_id: int, date_str: str) -> bytes | None:
        """Load backup bytes for the given date string.

        Args:
            date_str: Either "YYYYMMDD" (loads highest HH for that day) or
                      "YYYYMMDD:HH" (loads exact hourly backup).

        Returns None if the backup file does not exist.
        """
        backup_dir = self._settings.get_chat_backup_dir(chat_id)

        if ":" in date_str:
            # Exact hourly lookup: YYYYMMDD:HH -> backup_YYYYMMDD_HH.state
            date_part, hour_part = date_str.split(":", 1)
            path = backup_dir / f"backup_{date_part}_{hour_part}.state"
            if not path.exists():
                return None
            return path.read_bytes()
        else:
            # Day lookup: find all backup_YYYYMMDD_*.state, return highest HH
            matches = sorted(backup_dir.glob(f"backup_{date_str}_??.state"))
            if not matches:
                return None
            return matches[-1].read_bytes()

    def list_backups(self, chat_id: int) -> list[str]:
        """Return a sorted list of YYYYMMDD:HH strings for existing backups."""
        backup_dir = self._settings.data_dir / "backups" / str(chat_id)
        if not backup_dir.exists():
            return []
        identifiers = []
        for f in backup_dir.glob("backup_????????_??.state"):
            stem = f.stem.replace("backup_", "")  # YYYYMMDD_HH
            date_part, hour_part = stem.split("_", 1)
            identifiers.append(f"{date_part}:{hour_part}")
        return sorted(identifiers)

    def purge_old_backups(self, chat_id: int) -> int:
        """Delete backups older than backup_retention_days.

        Returns the number of files deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._settings.backup_retention_days)
        cutoff_str = cutoff.strftime("%Y%m%d")
        backup_dir = self._settings.data_dir / "backups" / str(chat_id)
        if not backup_dir.exists():
            return 0
        deleted = 0
        for f in backup_dir.glob("backup_????????_??.state"):
            stem = f.stem.replace("backup_", "")  # YYYYMMDD_HH
            date_part = stem.split("_")[0]  # YYYYMMDD
            if date_part < cutoff_str:
                f.unlink()
                deleted += 1
                logger.debug(f"Purged old backup {f.name} for chat {chat_id}")
        return deleted
