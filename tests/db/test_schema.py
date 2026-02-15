"""Tests for database schema."""
import sqlite3
import pytest
from src.db.schema import get_schema_sql, SCHEMA_VERSION


def test_schema_creates_all_tables(tmp_path):
    """Verify schema creates all expected tables."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    conn.executescript(get_schema_sql())
    
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    
    expected = {
        'chat_configs', 'game_states', 'user_input_counts',
        'recent_inputs', 'input_queue_items', 'input_queue_buttons',
        'save_slots', 'schema_version'
    }
    assert expected.issubset(tables)
    conn.close()


def test_schema_creates_indexes(tmp_path):
    """Verify schema creates expected indexes."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    conn.executescript(get_schema_sql())
    
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index';")
    indexes = {row[0] for row in cursor.fetchall()}
    
    assert 'idx_user_counts_chat' in indexes
    assert 'idx_recent_inputs_chat' in indexes
    conn.close()


def test_foreign_keys_enabled(tmp_path):
    """Verify foreign key constraints are enforced."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(get_schema_sql())
    
    # Should fail due to foreign key constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO user_input_counts (chat_id, user_id, input_count) VALUES (999, 1, 5);"
        )
    conn.close()
