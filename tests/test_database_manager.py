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
