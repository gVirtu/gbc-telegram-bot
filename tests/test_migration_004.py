import sqlite3
import pytest
from pathlib import Path


def test_migration_004_adds_maintenance_mode_column():
    """Test that migration 004 adds maintenance_mode column."""
    # Create temporary database
    db_path = Path("/tmp/test_migration_004.db")
    if db_path.exists():
        db_path.unlink()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Create chat_configs table without maintenance_mode (baseline)
    conn.execute("""
        CREATE TABLE chat_configs (
            chat_id INTEGER PRIMARY KEY,
            input_hold_frames INTEGER,
            animation_duration INTEGER,
            auto_save_enabled INTEGER DEFAULT 1,
            running_mode INTEGER DEFAULT 0,
            message_base_text TEXT,
            created_at TEXT,
            updated_at TEXT
        );
    """)
    conn.commit()
    
    # Import and run migration
    import importlib
    migration = importlib.import_module("src.db.migrations.004_add_maintenance_mode_to_chat_configs")
    migration.upgrade(conn)
    conn.commit()
    
    # Verify column exists
    cursor = conn.execute("PRAGMA table_info(chat_configs);")
    columns = [row['name'] for row in cursor.fetchall()]
    assert 'maintenance_mode' in columns
    
    # Verify default value works
    conn.execute("INSERT INTO chat_configs (chat_id) VALUES (123);")
    conn.commit()
    
    cursor = conn.execute("SELECT maintenance_mode FROM chat_configs WHERE chat_id = 123;")
    row = cursor.fetchone()
    assert row['maintenance_mode'] == 0
    
    conn.close()
    db_path.unlink()


def test_migration_004_downgrade_removes_column():
    """Test that migration 004 downgrade removes maintenance_mode column."""
    db_path = Path("/tmp/test_migration_004_downgrade.db")
    if db_path.exists():
        db_path.unlink()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Create table with maintenance_mode
    conn.execute("""
        CREATE TABLE chat_configs (
            chat_id INTEGER PRIMARY KEY,
            input_hold_frames INTEGER,
            animation_duration INTEGER,
            auto_save_enabled INTEGER DEFAULT 1,
            running_mode INTEGER DEFAULT 0,
            message_base_text TEXT,
            maintenance_mode INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );
    """)
    conn.commit()
    
    # Run downgrade
    import importlib
    migration = importlib.import_module("src.db.migrations.004_add_maintenance_mode_to_chat_configs")
    migration.downgrade(conn)
    conn.commit()
    
    # Verify column is removed
    cursor = conn.execute("PRAGMA table_info(chat_configs);")
    columns = [row['name'] for row in cursor.fetchall()]
    assert 'maintenance_mode' not in columns
    
    conn.close()
    db_path.unlink()
