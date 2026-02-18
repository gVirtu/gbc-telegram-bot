import pytest
import sqlite3
from pathlib import Path
from datetime import datetime

from src.db.manager import DatabaseManager
from src.models.game_state import ChatConfig


@pytest.fixture
def db_manager(tmp_path):
    """Create a temporary database manager for testing."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    yield manager
    manager.close()


def test_save_and_load_chat_config_with_maintenance_mode(db_manager):
    """Test that maintenance_mode is saved and loaded correctly."""
    config = ChatConfig(
        chat_id=123,
        maintenance_mode=True,
        running_mode=False,
        auto_save_enabled=True,
    )
    
    db_manager.save_chat_config(config)
    
    loaded = db_manager.load_chat_config(123)
    assert loaded is not None
    assert loaded.maintenance_mode is True
    assert loaded.chat_id == 123


def test_load_chat_config_without_maintenance_mode_defaults_to_false(db_manager):
    """Test that loading config without maintenance_mode defaults to False."""
    # Insert config manually without maintenance_mode (simulating old data)
    db_manager.connection.execute("""
        INSERT INTO chat_configs 
        (chat_id, input_hold_frames, animation_duration, auto_save_enabled, running_mode, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (456, None, None, 1, 0, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
    db_manager.connection.commit()
    
    loaded = db_manager.load_chat_config(456)
    assert loaded is not None
    assert loaded.maintenance_mode is False


def test_get_or_create_chat_config_default_maintenance_mode(db_manager):
    """Test that get_or_create_chat_config defaults maintenance_mode to False."""
    config = db_manager.get_or_create_chat_config(789)
    assert config.maintenance_mode is False
