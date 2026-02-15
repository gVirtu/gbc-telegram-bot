"""Tests for database connection management."""
import sqlite3
import pytest
from pathlib import Path
from src.db.connection import DatabaseConnection, get_db_path


def test_get_db_path_returns_path_in_data_dir(tmp_path):
    """Verify database path is in data directory."""
    from src.config import Settings
    
    settings = Settings(data_dir=tmp_path, rom_path=tmp_path / "test.gbc")
    db_path = get_db_path(settings)
    
    assert db_path.parent == tmp_path
    assert db_path.name == "bot.db"


def test_database_connection_initializes_schema(tmp_path):
    """Verify connection initializes database with schema."""
    db_path = tmp_path / "test.db"
    
    conn = DatabaseConnection(db_path)
    conn.initialize()
    
    # Verify tables exist
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert 'game_states' in tables
    assert 'chat_configs' in tables
    
    conn.close()


def test_database_connection_context_manager(tmp_path):
    """Verify context manager properly closes connection."""
    db_path = tmp_path / "test.db"
    
    with DatabaseConnection(db_path) as conn:
        conn.initialize()
        cursor = conn.execute("SELECT 1;")
        assert cursor.fetchone()[0] == 1
    
    # Connection should be closed after context manager exits
    assert conn._connection is None


def test_database_connection_foreign_keys_enabled(tmp_path):
    """Verify foreign keys are enabled by default."""
    db_path = tmp_path / "test.db"
    
    conn = DatabaseConnection(db_path)
    conn.initialize()
    
    cursor = conn.execute("PRAGMA foreign_keys;")
    assert cursor.fetchone()[0] == 1
    
    conn.close()


def test_get_connection_creates_if_none(tmp_path):
    """Verify get_connection creates connection if not exists."""
    db_path = tmp_path / "test.db"
    
    conn = DatabaseConnection(db_path)
    assert conn._connection is None
    
    connection = conn.get_connection()
    assert connection is not None
    assert conn._connection is connection
    
    conn.close()
