"""Tests for DatabaseManager."""
import pytest
from datetime import datetime
from pathlib import Path

from src.db.manager import DatabaseManager
from src.models.game_state import ChatConfig, ChatGameState, GameButton


@pytest.fixture
def db_manager(tmp_path):
    """Create a DatabaseManager with temporary database."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    yield manager
    manager.close()


class TestChatConfigOperations:
    """Test chat configuration CRUD operations."""
    
    def test_save_chat_config_creates_new(self, db_manager):
        """Verify saving new config creates row."""
        config = ChatConfig(
            chat_id=123,
            input_hold_frames=10,
            animation_duration=5,
            auto_save_enabled=True,
            running_mode=False
        )
        
        db_manager.save_chat_config(config)
        
        loaded = db_manager.load_chat_config(123)
        assert loaded is not None
        assert loaded.chat_id == 123
        assert loaded.input_hold_frames == 10
        assert loaded.auto_save_enabled is True
    
    def test_load_chat_config_nonexistent_returns_none(self, db_manager):
        """Verify loading nonexistent config returns None."""
        result = db_manager.load_chat_config(999)
        assert result is None
    
    def test_save_chat_config_updates_existing(self, db_manager):
        """Verify saving existing config updates row."""
        config1 = ChatConfig(chat_id=123, input_hold_frames=10)
        db_manager.save_chat_config(config1)
        
        config2 = ChatConfig(chat_id=123, input_hold_frames=20)
        db_manager.save_chat_config(config2)
        
        loaded = db_manager.load_chat_config(123)
        assert loaded.input_hold_frames == 20
    
    def test_get_or_create_chat_config_creates_default(self, db_manager):
        """Verify get_or_create creates default config."""
        config = db_manager.get_or_create_chat_config(123)
        
        assert config.chat_id == 123
        assert config.input_hold_frames is None
        assert config.auto_save_enabled is True
        assert config.created_at is not None
    
    def test_get_or_create_chat_config_returns_existing(self, db_manager):
        """Verify get_or_create returns existing config."""
        original = ChatConfig(chat_id=123, input_hold_frames=15)
        db_manager.save_chat_config(original)
        
        loaded = db_manager.get_or_create_chat_config(123)
        assert loaded.input_hold_frames == 15


class TestGameStateOperations:
    """Test game state CRUD operations."""
    
    def test_save_game_state_creates_new(self, db_manager):
        """Verify saving new game state creates row."""
        state = ChatGameState(
            chat_id=123,
            message_id=456,
            input_in_progress=True,
            last_input=GameButton.A,
            frame_hash="abc123"
        )
        
        db_manager.save_game_state(state)
        
        loaded = db_manager.load_game_state(123)
        assert loaded is not None
        assert loaded.chat_id == 123
        assert loaded.message_id == 456
        assert loaded.input_in_progress is True
        assert loaded.last_input == GameButton.A
        assert loaded.frame_hash == "abc123"
    
    def test_load_game_state_nonexistent_returns_none(self, db_manager):
        """Verify loading nonexistent state returns None."""
        result = db_manager.load_game_state(999)
        assert result is None
    
    def test_save_game_state_updates_existing(self, db_manager):
        """Verify saving existing state updates row."""
        state1 = ChatGameState(chat_id=123, message_id=100)
        db_manager.save_game_state(state1)
        
        state2 = ChatGameState(chat_id=123, message_id=200)
        db_manager.save_game_state(state2)
        
        loaded = db_manager.load_game_state(123)
        assert loaded.message_id == 200
    
    def test_delete_game_state(self, db_manager):
        """Verify delete removes game state."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        deleted = db_manager.delete_game_state(123)
        assert deleted is True
        
        loaded = db_manager.load_game_state(123)
        assert loaded is None
    
    def test_delete_game_state_nonexistent_returns_false(self, db_manager):
        """Verify deleting nonexistent state returns False."""
        result = db_manager.delete_game_state(999)
        assert result is False
    
    def test_save_game_state_with_user_counts(self, db_manager):
        """Verify user input counts are saved."""
        state = ChatGameState(
            chat_id=123,
            user_input_counts={"111": 5, "222": 3}
        )
        db_manager.save_game_state(state)
        
        loaded = db_manager.load_game_state(123)
        assert loaded.user_input_counts == {"111": 5, "222": 3}
    
    def test_save_game_state_with_recent_inputs(self, db_manager):
        """Verify recent inputs are saved."""
        from datetime import datetime
        state = ChatGameState(
            chat_id=123,
            recent_inputs=[{
                "user_id": 111,
                "user_name": "Alice",
                "buttons": ["a"],
                "timestamp": datetime.utcnow().isoformat()
            }]
        )
        db_manager.save_game_state(state)
        
        loaded = db_manager.load_game_state(123)
        assert len(loaded.recent_inputs) == 1
        assert loaded.recent_inputs[0]["user_name"] == "Alice"
