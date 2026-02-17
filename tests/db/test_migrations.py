"""Tests for database migration system."""
import sqlite3
import pytest
from datetime import datetime
from pathlib import Path


class TestMigrationHistoryTable:
    """Test migration_history table structure."""
    
    def test_migration_history_table_created(self, tmp_path):
        """Verify migration_history table is created."""
        from src.db.connection import DatabaseConnection
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        conn.initialize()
        
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_history';"
        )
        assert cursor.fetchone() is not None
        conn.close()
