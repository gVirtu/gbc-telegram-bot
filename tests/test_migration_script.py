"""Tests for migration script."""
import json
import pytest
from pathlib import Path
from datetime import datetime

from src.models.game_state import ChatGameState, ChatConfig, SaveSlotInfo, GameButton
from src.db import DatabaseManager


class TestMigrationScript:
    """Test data migration from JSON files to SQLite."""
    
    def test_migrate_chat_config(self, tmp_path):
        """Verify chat config migration."""
        # Create old-style data directory
        data_dir = tmp_path / "data"
        config_dir = data_dir / "config"
        config_dir.mkdir(parents=True)
        
        # Create config JSON file
        config = ChatConfig(chat_id=123, input_hold_frames=10, modifier_states={"run": True})
        config_file = config_dir / "123.json"
        with open(config_file, 'w') as f:
            json.dump(config.to_dict(), f)
        
        # Run migration
        from scripts.migrate_to_sqlite import migrate_data
        db_manager = DatabaseManager(tmp_path / "bot.db")
        db_manager.initialize()
        
        migrate_data(data_dir, db_manager)
        
        # Verify migrated
        loaded = db_manager.load_chat_config(123)
        assert loaded is not None
        assert loaded.input_hold_frames == 10
        assert loaded.modifier_states == {"run": True}
    
    def test_migrate_game_state(self, tmp_path):
        """Verify game state migration."""
        data_dir = tmp_path / "data"
        polls_dir = data_dir / "polls"
        polls_dir.mkdir(parents=True)
        
        # Create game state JSON
        state = ChatGameState(
            chat_id=456,
            message_id=789,
            last_input=GameButton.A,
            user_input_counts={"111": 5, "222": 3},
        )
        state_file = polls_dir / "456.json"
        with open(state_file, 'w') as f:
            json.dump(state.to_dict(), f)
        
        # Run migration
        from scripts.migrate_to_sqlite import migrate_data
        db_manager = DatabaseManager(tmp_path / "bot.db")
        db_manager.initialize()
        
        migrate_data(data_dir, db_manager)
        
        # Verify migrated
        loaded = db_manager.load_game_state(456)
        assert loaded is not None
        assert loaded.message_id == 789
        assert loaded.last_input == GameButton.A
        assert loaded.user_input_counts == {"111": 5, "222": 3}
    
    def test_migrate_save_slot(self, tmp_path):
        """Verify save slot migration."""
        data_dir = tmp_path / "data"
        saves_dir = data_dir / "saves" / "789"
        saves_dir.mkdir(parents=True)
        
        # Create save slot metadata and binary file
        slot_info = SaveSlotInfo(slot_number=0, is_auto_save=True, description="Test")
        with open(saves_dir / "slot_0.json", 'w') as f:
            json.dump(slot_info.to_dict(), f)
        
        state_data = b"fake_save_state_data"
        with open(saves_dir / "slot_0.state", 'wb') as f:
            f.write(state_data)
        
        # Also need game state for foreign key
        polls_dir = data_dir / "polls"
        polls_dir.mkdir(parents=True)
        state = ChatGameState(chat_id=789)
        with open(polls_dir / "789.json", 'w') as f:
            json.dump(state.to_dict(), f)
        
        # Run migration
        from scripts.migrate_to_sqlite import migrate_data
        db_manager = DatabaseManager(tmp_path / "bot.db")
        db_manager.initialize()
        
        migrate_data(data_dir, db_manager)
        
        # Verify migrated
        info = db_manager.get_slot_info(789, 0)
        assert info is not None
        assert info.is_auto_save is True
        
        # Verify binary data accessible
        loaded_data = db_manager.load_from_slot(789, 0)
        assert loaded_data == state_data
