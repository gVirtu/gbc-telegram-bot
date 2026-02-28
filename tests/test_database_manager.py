import pytest
import sqlite3
import json
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


def test_save_and_load_chat_config_with_modifier_states(db_manager):
    """Test that modifier_states is saved and loaded correctly."""
    config = ChatConfig(
        chat_id=123,
        maintenance_mode=True,
        modifier_states={"run": True},
        auto_save_enabled=True,
    )

    db_manager.save_chat_config(config)

    loaded = db_manager.load_chat_config(123)
    assert loaded is not None
    assert loaded.maintenance_mode is True
    assert loaded.modifier_states == {"run": True}
    assert loaded.chat_id == 123


def test_save_and_load_chat_config_empty_modifier_states(db_manager):
    """Test that empty modifier_states is saved and loaded correctly."""
    config = ChatConfig(chat_id=456, modifier_states={})
    db_manager.save_chat_config(config)
    loaded = db_manager.load_chat_config(456)
    assert loaded is not None
    assert loaded.modifier_states == {}


def test_get_or_create_chat_config_default_modifier_states(db_manager):
    """Test that get_or_create_chat_config defaults modifier_states to {}."""
    config = db_manager.get_or_create_chat_config(789)
    assert config.modifier_states == {}


def test_get_or_create_chat_config_default_maintenance_mode(db_manager):
    """Test that get_or_create_chat_config defaults maintenance_mode to False."""
    config = db_manager.get_or_create_chat_config(999)
    assert config.maintenance_mode is False


def test_load_chat_config_with_null_modifier_states_defaults_to_empty(db_manager):
    """Test that loading config with NULL modifier_states defaults to {}.

    The modifier_states column is NOT NULL in the live schema, but a row with
    NULL can appear after a manual migration or schema repair.  We simulate
    that by inserting a row into a temporary table that has no NOT NULL
    constraint and then mocking the cursor so load_chat_config sees NULL.
    """
    from unittest.mock import patch, MagicMock
    import datetime

    now = datetime.datetime.utcnow().isoformat()

    # Build a fake sqlite3.Row-like mapping that load_chat_config will read
    fake_row = {
        'chat_id': 111,
        'input_hold_frames': None,
        'animation_duration': None,
        'auto_save_enabled': 1,
        'modifier_states': None,   # <-- the NULL case under test
        'message_base_text': None,
        'maintenance_mode': 0,
        'language': None,
        'created_at': now,
        'updated_at': now,
    }

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fake_row

    with patch.object(db_manager.connection, 'execute', return_value=mock_cursor):
        loaded = db_manager.load_chat_config(111)

    assert loaded is not None
    assert loaded.modifier_states == {}


def test_save_and_load_chat_config_multiple_modifier_states(db_manager):
    """Test round-trip with multiple modifier keys."""
    config = ChatConfig(chat_id=222, modifier_states={"run": True, "turbo": False})
    db_manager.save_chat_config(config)
    loaded = db_manager.load_chat_config(222)
    assert loaded is not None
    assert loaded.modifier_states == {"run": True, "turbo": False}
