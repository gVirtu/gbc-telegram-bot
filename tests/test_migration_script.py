"""Tests for migration script.

This module tests migration of data from JSON files to SQLite.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.db.manager import DatabaseManager
from src.models.game_state import ChatConfig, ChatGameState, GameButton, SaveSlotInfo


class TestMigrateChatConfig:
    """Test chat config migration."""

    @pytest.fixture
    def data_dir(self, tmp_path):
        """Create test data directory with config."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        
        config_data = {
            "chat_id": 123456,
            "input_hold_frames": 60,
            "animation_duration": 20,
            "auto_save_enabled": False,
            "running_mode": True,
            "created_at": "2024-01-15T10:30:00",
            "updated_at": "2024-01-15T12:00:00",
        }
        
        config_file = config_dir / "123456.json"
        config_file.write_text(json.dumps(config_data))
        
        return tmp_path

    @pytest.fixture
    def db_manager(self, tmp_path):
        """Create database manager with test database."""
        db_path = tmp_path / "test.db"
        manager = DatabaseManager(db_path=db_path)
        manager.initialize()
        return manager

    def test_migrate_chat_config(self, data_dir, db_manager):
        """Test that chat config is migrated to SQLite."""
        from scripts.migrate_to_sqlite import migrate_chat_configs
        
        migrate_chat_configs(data_dir, db_manager, dry_run=False)
        
        loaded = db_manager.load_chat_config(123456)
        
        assert loaded is not None
        assert loaded.chat_id == 123456
        assert loaded.input_hold_frames == 60
        assert loaded.animation_duration == 20
        assert loaded.auto_save_enabled is False
        assert loaded.running_mode is True

    def test_migrate_chat_config_dry_run(self, data_dir, db_manager):
        """Test that dry run doesn't persist data."""
        from scripts.migrate_to_sqlite import migrate_chat_configs
        
        migrate_chat_configs(data_dir, db_manager, dry_run=True)
        
        loaded = db_manager.load_chat_config(123456)
        
        assert loaded is None


class TestMigrateGameState:
    """Test game state migration."""

    @pytest.fixture
    def data_dir(self, tmp_path):
        """Create test data directory with game state."""
        polls_dir = tmp_path / "polls"
        polls_dir.mkdir()
        
        state_data = {
            "chat_id": 789012,
            "message_id": 1234,
            "input_in_progress": True,
            "last_input": "a",
            "last_input_time": "2024-01-15T10:30:00",
            "frame_hash": "abc123hash",
            "user_input_counts": {"111": 5, "222": 3},
            "recent_inputs": [
                {"user_id": 111, "user_name": "Alice", "buttons": ["up"], "timestamp": "2024-01-15T10:29:00"}
            ],
            "created_at": "2024-01-15T09:00:00",
            "updated_at": "2024-01-15T10:30:00",
        }
        
        poll_file = polls_dir / "789012.json"
        poll_file.write_text(json.dumps(state_data))
        
        return tmp_path

    @pytest.fixture
    def db_manager(self, tmp_path):
        """Create database manager with test database."""
        db_path = tmp_path / "test.db"
        manager = DatabaseManager(db_path=db_path)
        manager.initialize()
        return manager

    def test_migrate_game_state(self, data_dir, db_manager):
        """Test that game state is migrated to SQLite."""
        from scripts.migrate_to_sqlite import migrate_game_states
        
        migrate_game_states(data_dir, db_manager, dry_run=False)
        
        loaded = db_manager.load_game_state(789012)
        
        assert loaded is not None
        assert loaded.chat_id == 789012
        assert loaded.message_id == 1234
        assert loaded.input_in_progress is True
        assert loaded.last_input == GameButton.A
        assert loaded.frame_hash == "abc123hash"
        assert loaded.user_input_counts == {"111": 5, "222": 3}

    def test_migrate_game_state_dry_run(self, data_dir, db_manager):
        """Test that dry run doesn't persist data."""
        from scripts.migrate_to_sqlite import migrate_game_states
        
        migrate_game_states(data_dir, db_manager, dry_run=True)
        
        loaded = db_manager.load_game_state(789012)
        
        assert loaded is None


class TestMigrateSaveSlot:
    """Test save slot migration."""

    @pytest.fixture
    def data_dir(self, tmp_path):
        """Create test data directory with save slots."""
        saves_dir = tmp_path / "saves" / "345678"
        saves_dir.mkdir(parents=True)
        
        state_data = b"fake save state bytes data"
        (saves_dir / "slot_0.state").write_bytes(state_data)
        
        slot_info = {
            "slot_number": 0,
            "created_at": "2024-01-15T10:00:00",
            "updated_at": "2024-01-15T12:00:00",
            "is_auto_save": True,
            "description": "Auto-save at checkpoint",
        }
        (saves_dir / "slot_0.json").write_text(json.dumps(slot_info))
        
        return tmp_path

    @pytest.fixture
    def db_manager(self, tmp_path):
        """Create database manager with test database."""
        db_path = tmp_path / "test.db"
        manager = DatabaseManager(db_path=db_path)
        manager.initialize()
        return manager

    @pytest.fixture
    def new_states_dir(self, tmp_path):
        """Create new directory for state files."""
        new_dir = tmp_path / "new_states"
        new_dir.mkdir()
        return new_dir

    def test_migrate_save_slot(self, data_dir, db_manager, new_states_dir):
        """Test that save slot is migrated to SQLite."""
        from scripts.migrate_to_sqlite import migrate_save_slots
        
        migrate_save_slots(data_dir, db_manager, new_states_dir, dry_run=False)
        
        loaded_data = db_manager.load_from_slot(345678, 0)
        
        assert loaded_data == b"fake save state bytes data"
        
        info = db_manager.get_slot_info(345678, 0)
        
        assert info is not None
        assert info.slot_number == 0
        assert info.is_auto_save is True
        assert info.description == "Auto-save at checkpoint"

    def test_migrate_save_slot_dry_run(self, data_dir, db_manager, new_states_dir):
        """Test that dry run doesn't persist data."""
        from scripts.migrate_to_sqlite import migrate_save_slots
        
        migrate_save_slots(data_dir, db_manager, new_states_dir, dry_run=True)
        
        loaded_data = db_manager.load_from_slot(345678, 0)
        
        assert loaded_data is None
