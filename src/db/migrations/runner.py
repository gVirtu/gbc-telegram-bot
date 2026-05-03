"""Migration runner for executing database migrations."""

import logging
import sqlite3
from typing import List, Dict, Any
from datetime import datetime

from src.db.connection import DatabaseConnection
from src.db.migrations import discover_migrations
from src.db.migrations.base import Migration

logger = logging.getLogger(__name__)


class MigrationRunner:
    """Runs database migrations.
    
    Handles migration discovery, execution, and tracking.
    Each migration runs in a transaction - if it fails, it's rolled back.
    
    Example:
        >>> runner = MigrationRunner(connection)
        >>> runner.run_migrations()  # Run all pending migrations
        >>> runner.rollback_migration(2)  # Rollback version 2
    """
    
    def __init__(self, connection: DatabaseConnection):
        """Initialize the migration runner.
        
        Args:
            connection: DatabaseConnection to use for migrations.
        """
        self.connection = connection
    
    def _ensure_migration_history_table(self) -> None:
        """Ensure migration_history table exists."""
        sql = """
            CREATE TABLE IF NOT EXISTS migration_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER UNIQUE NOT NULL,
                name TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reverted_at TIMESTAMP,
                CHECK (version > 0)
            );
            CREATE INDEX IF NOT EXISTS idx_migration_history_version ON migration_history(version);
        """
        self.connection.executescript(sql)
    
    def _is_existing_database(self) -> bool:
        """Check if database existed before migrations were introduced.
        
        Detects existing database by checking for schema_version table
        or other application tables that would indicate the DB was in use.
        
        Returns:
            True if database has existing schema.
        """
        cursor = self.connection.execute(
            """SELECT name FROM sqlite_master 
               WHERE type='table' 
               AND name IN ('schema_version', 'chat_configs', 'game_states');"""
        )
        return cursor.fetchone() is not None
    
    def _mark_baseline_as_applied_if_needed(self) -> bool:
        """Mark baseline migration as applied for existing databases.
        
        If this is an existing database (created before migrations),
        mark the baseline migration as already applied without running it.
        
        Returns:
            True if baseline was marked as applied.
        """
        # Check if migration_history table exists
        cursor = self.connection.execute(
            """SELECT name FROM sqlite_master 
               WHERE type='table' AND name='migration_history';"""
        )
        if cursor.fetchone() is None:
            return False
        
        # Check if baseline (v1) is already applied
        if self.is_migration_applied(1):
            return False
        
        # Check if this is an existing database
        if not self._is_existing_database():
            return False
        
        # Mark baseline as applied
        logger.info("Detected existing database - marking baseline migration as applied")
        self._record_migration_applied(1, "001_baseline")
        return True
    
    def get_applied_migrations(self) -> List[Dict[str, Any]]:
        """Get list of applied migrations.
        
        Returns:
            List of dicts with version, name, applied_at, reverted_at.
        """
        cursor = self.connection.execute(
            """SELECT version, name, applied_at, reverted_at 
               FROM migration_history 
               WHERE reverted_at IS NULL
               ORDER BY version;"""
        )
        return [
            {
                "version": row["version"],
                "name": row["name"],
                "applied_at": row["applied_at"],
                "reverted_at": row["reverted_at"]
            }
            for row in cursor.fetchall()
        ]
    
    def is_migration_applied(self, version: int) -> bool:
        """Check if a migration version has been applied.
        
        Args:
            version: Migration version to check.
            
        Returns:
            True if migration has been applied and not reverted.
        """
        cursor = self.connection.execute(
            """SELECT 1 FROM migration_history 
               WHERE version = ? AND reverted_at IS NULL;""",
            (version,)
        )
        return cursor.fetchone() is not None
    
    def _record_migration_applied(self, version: int, name: str) -> None:
        """Record that a migration was applied.
        
        Args:
            version: Migration version.
            name: Migration name.
        """
        self.connection.execute(
            """INSERT INTO migration_history (version, name, applied_at)
               VALUES (?, ?, ?)
               ON CONFLICT(version) DO UPDATE SET
                   reverted_at = NULL,
                   applied_at = excluded.applied_at;""",
            (version, name, datetime.utcnow().isoformat())
        )
        self.connection.commit()
    
    def _record_migration_reverted(self, version: int) -> None:
        """Record that a migration was reverted.
        
        Args:
            version: Migration version.
        """
        self.connection.execute(
            """UPDATE migration_history 
               SET reverted_at = ?
               WHERE version = ? AND reverted_at IS NULL;""",
            (datetime.utcnow().isoformat(), version)
        )
        self.connection.commit()
    
    def run_migration(self, migration: Migration) -> None:
        """Run a single migration in a transaction.
        
        Args:
            migration: Migration to run.
            
        Raises:
            MigrationError: If migration fails.
        """
        if self.is_migration_applied(migration.version):
            logger.debug(f"Migration {migration.name} (v{migration.version}) already applied")
            return
        
        logger.info(f"Running migration {migration.name} (v{migration.version})...")
        
        try:
            # Get raw connection for transaction control
            conn = self.connection.get_connection()
            
            # Run migration
            migration.upgrade(conn)
            
            # Record migration as applied
            self._record_migration_applied(migration.version, migration.name)
            
            logger.info(f"Migration {migration.name} (v{migration.version}) completed successfully")
            
        except Exception as e:
            # Rollback is handled by context manager or explicit rollback
            if hasattr(self.connection, '_connection') and self.connection._connection:
                self.connection._connection.rollback()
            raise MigrationError(
                f"Migration {migration.name} (v{migration.version}) failed: {e}"
            ) from e
    
    def run_migrations(self) -> None:
        """Run all pending migrations.
        
        Discovers all migrations, then runs each one that hasn't been applied.
        If any migration fails, raises MigrationError and stops.
        For existing databases, marks baseline as applied without running it.
        """
        self._ensure_migration_history_table()
        
        # Handle existing databases (created before migrations existed)
        self._mark_baseline_as_applied_if_needed()
        
        migrations = discover_migrations()
        if not migrations:
            logger.info("No migrations found")
            return
        
        applied_count = 0
        for migration in migrations:
            if not self.is_migration_applied(migration.version):
                self.run_migration(migration)
                applied_count += 1
        
        if applied_count > 0:
            logger.info(f"Applied {applied_count} migration(s)")
        else:
            logger.info("No pending migrations")
    
    def rollback_migration(self, version: int) -> None:
        """Rollback a specific migration.
        
        Args:
            version: Version to rollback.
            
        Raises:
            MigrationError: If migration not found or has no downgrade.
        """
        if not self.is_migration_applied(version):
            raise MigrationError(f"Migration v{version} is not applied")
        
        # Find the migration
        migrations = discover_migrations()
        migration = next((m for m in migrations if m.version == version), None)
        
        if migration is None:
            raise MigrationError(f"Migration v{version} not found")
        
        if migration.downgrade is None:
            raise MigrationError(f"Migration v{version} has no downgrade function")
        
        logger.info(f"Rolling back migration {migration.name} (v{version})...")
        
        try:
            conn = self.connection.get_connection()
            migration.downgrade(conn)
            self._record_migration_reverted(version)
            logger.info(f"Migration {migration.name} (v{version}) rolled back successfully")
            
        except Exception as e:
            if hasattr(self.connection, '_connection') and self.connection._connection:
                self.connection._connection.rollback()
            raise MigrationError(
                f"Rollback of {migration.name} (v{version}) failed: {e}"
            ) from e
    
    def get_pending_migrations(self) -> List[Migration]:
        """Get list of migrations that haven't been applied.
        
        Returns:
            List of pending Migration objects.
        """
        self._ensure_migration_history_table()
        all_migrations = discover_migrations()
        return [m for m in all_migrations if not self.is_migration_applied(m.version)]
    
    def get_status(self) -> Dict[str, Any]:
        """Get current migration status.
        
        Returns:
            Dict with keys:
                - current_version: highest applied version
                - pending_count: number of pending migrations
                - applied_count: number of applied migrations
                - total_count: total number of migrations
                - migrations: list of dicts with version, name, applied status
        """
        self._ensure_migration_history_table()
        
        all_migrations = discover_migrations()
        applied = self.get_applied_migrations()
        applied_versions = {m["version"] for m in applied}
        
        current_version = max(applied_versions) if applied_versions else 0
        pending = [m for m in all_migrations if m.version not in applied_versions]
        
        migrations_info = []
        for m in all_migrations:
            migrations_info.append({
                "version": m.version,
                "name": m.name,
                "applied": m.version in applied_versions,
                "has_downgrade": m.downgrade is not None
            })
        
        return {
            "current_version": current_version,
            "pending_count": len(pending),
            "applied_count": len(applied),
            "total_count": len(all_migrations),
            "migrations": migrations_info
        }


class MigrationError(Exception):
    """Raised when a migration fails."""
    pass
