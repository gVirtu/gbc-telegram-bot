"""Database connection management for SQLite."""

import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_db_path(settings) -> Path:
    """Get database file path from settings.
    
    Args:
        settings: Application settings with data_dir
        
    Returns:
        Path to SQLite database file
    """
    return settings.data_dir / "bot.db"


class DatabaseConnection:
    """Manages SQLite database connections.
    
    Handles connection lifecycle, schema initialization,
    and provides context manager support.
    
    Example:
        >>> conn = DatabaseConnection(Path("data/bot.db"))
        >>> conn.initialize()
        >>> conn.execute("SELECT 1;")
        >>> conn.close()
    """
    
    def __init__(self, db_path: Path):
        """Initialize database connection manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None
    
    def get_connection(self) -> sqlite3.Connection:
        """Get or create database connection.
        
        Returns:
            SQLite connection with foreign keys enabled
        """
        if self._connection is None:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            
            self._connection = sqlite3.connect(self.db_path)
            # Enable foreign keys
            self._connection.execute("PRAGMA foreign_keys = ON;")
            # Return rows as sqlite3.Row for dict-like access
            self._connection.row_factory = sqlite3.Row
            
            logger.debug(f"Opened database connection to {self.db_path}")
        
        return self._connection
    
    def initialize(self) -> None:
        """Initialize database with schema and migrations.
        
        Creates tables if they don't exist and runs pending migrations.
        Safe to call multiple times (idempotent).
        
        Raises:
            MigrationError: If any migration fails.
        """
        conn = self.get_connection()
        
        # Run migrations (handles both new and existing databases)
        # Lazy import to avoid circular dependency
        from src.db.migrations.runner import MigrationRunner, MigrationError
        runner = MigrationRunner(self)
        try:
            runner.run_migrations()
        except MigrationError:
            # Re-raise to abort initialization
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise MigrationError(f"Failed to run migrations: {e}") from e
        
        logger.info(f"Initialized database at {self.db_path}")
    
    def execute(self, sql: str, parameters: tuple = ()) -> sqlite3.Cursor:
        """Execute SQL statement.
        
        Args:
            sql: SQL statement to execute
            parameters: Query parameters
            
        Returns:
            Cursor object
        """
        conn = self.get_connection()
        return conn.execute(sql, parameters)
    
    def executescript(self, sql: str) -> sqlite3.Cursor:
        """Execute multiple SQL statements.
        
        Args:
            sql: SQL script to execute
            
        Returns:
            Cursor object
        """
        conn = self.get_connection()
        return conn.executescript(sql)
    
    def commit(self) -> None:
        """Commit current transaction."""
        if self._connection:
            self._connection.commit()
    
    def close(self) -> None:
        """Close database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.debug("Closed database connection")
    
    def __enter__(self):
        """Context manager entry."""
        self.get_connection()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type:
            # Exception occurred, rollback
            if self._connection:
                self._connection.rollback()
        else:
            # No exception, commit
            self.commit()
        self.close()
        return False  # Don't suppress exceptions
