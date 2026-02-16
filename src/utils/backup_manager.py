"""Backup manager for automatic daily game state backups.

Stores binary .state files at data/backups/{chat_id}/backup_{YYYYMMDD}.state.
No new DB table is used; active-chat detection queries the existing recent_inputs table.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class BackupManager:
    """Manages daily automatic backups of game states.

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
        """Save current game state for chat_id to today's backup file.

        Skips (returns True) if today's backup already exists.
        Returns False if no game controller is available.
        """
        date_str = datetime.utcnow().strftime("%Y%m%d")
        path = self._settings.get_chat_backup_dir(chat_id) / f"backup_{date_str}.state"

        if path.exists():
            logger.debug(f"Backup already exists for chat {chat_id} date {date_str}")
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
        """Load backup bytes for the given YYYYMMDD date string.

        Returns None if the backup file does not exist.
        """
        path = self._settings.get_chat_backup_dir(chat_id) / f"backup_{date_str}.state"
        if not path.exists():
            return None
        return path.read_bytes()

    def list_backups(self, chat_id: int) -> list[str]:
        """Return a sorted list of YYYYMMDD strings for existing backups."""
        backup_dir = self._settings.data_dir / "backups" / str(chat_id)
        if not backup_dir.exists():
            return []
        dates = []
        for f in backup_dir.glob("backup_????????.state"):
            dates.append(f.stem.replace("backup_", ""))
        return sorted(dates)

    def purge_old_backups(self, chat_id: int) -> int:
        """Delete backups older than backup_retention_days.

        Returns the number of files deleted.
        """
        cutoff = datetime.utcnow() - timedelta(days=self._settings.backup_retention_days)
        cutoff_str = cutoff.strftime("%Y%m%d")
        backup_dir = self._settings.data_dir / "backups" / str(chat_id)
        if not backup_dir.exists():
            return 0
        deleted = 0
        for f in backup_dir.glob("backup_????????.state"):
            date_str = f.stem.replace("backup_", "")
            if date_str < cutoff_str:
                f.unlink()
                deleted += 1
                logger.debug(f"Purged old backup {f.name} for chat {chat_id}")
        return deleted
