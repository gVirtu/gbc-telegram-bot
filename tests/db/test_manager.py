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


class TestInputQueueOperations:
    """Test input queue persistence operations."""
    
    def test_save_input_queue_with_items(self, db_manager):
        """Verify saving input queue with items."""
        from src.models.input_queue import InputQueue, QueueItem
        from src.models.game_state import GameButton
        
        # Need game state first (foreign key constraint)
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        queue = InputQueue()
        queue.add_input(456, "Alice", GameButton.A)
        queue.add_input(789, "Bob", GameButton.B)
        
        db_manager._save_input_queue(123, queue)
        
        loaded_queue = db_manager._load_input_queue(123)
        assert loaded_queue is not None
        assert len(loaded_queue.items) == 2
        assert loaded_queue.items[0].user_name == "Alice"
        assert loaded_queue.items[1].user_name == "Bob"
    
    def test_load_input_queue_empty(self, db_manager):
        """Verify loading empty input queue returns None."""
        queue = db_manager._load_input_queue(123)
        assert queue is None
    
    def test_save_input_queue_with_multiple_buttons(self, db_manager):
        """Verify queue items can have multiple buttons."""
        from src.models.input_queue import InputQueue
        from src.models.game_state import GameButton
        
        # Need game state first
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        queue = InputQueue()
        queue.add_input(456, "Alice", GameButton.A)
        queue.add_input(456, "Alice", GameButton.B)  # Same user extends item
        
        db_manager._save_input_queue(123, queue)
        
        loaded_queue = db_manager._load_input_queue(123)
        assert len(loaded_queue.items) == 1
        assert len(loaded_queue.items[0].buttons) == 2
        assert loaded_queue.items[0].buttons[0] == GameButton.A
        assert loaded_queue.items[0].buttons[1] == GameButton.B


class TestSaveSlotOperations:
    """Test save slot operations."""
    
    def test_save_to_slot_creates_metadata(self, db_manager, tmp_path):
        """Verify save creates slot metadata in database."""
        # Need game state first
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        state_data = b"fake_state_data"
        state_file_path = tmp_path / "state_file.state"
        
        info = db_manager.save_to_slot(
            chat_id=123,
            slot_number=0,
            state_data=state_data,
            state_file_path=state_file_path,
            description="Test save",
            is_auto_save=True
        )
        
        assert info.slot_number == 0
        assert info.is_auto_save is True
        assert info.description == "Test save"
        
        # Verify file was created
        assert state_file_path.exists()
        assert state_file_path.read_bytes() == state_data
    
    def test_get_slot_info(self, db_manager, tmp_path):
        """Verify loading slot info."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        db_manager.save_to_slot(
            chat_id=123,
            slot_number=1,
            state_data=b"data",
            state_file_path=tmp_path / "slot1.state",
            description="Manual save"
        )
        
        info = db_manager.get_slot_info(123, 1)
        assert info is not None
        assert info.slot_number == 1
        assert info.description == "Manual save"
        assert info.is_auto_save is False
    
    def test_list_save_slots(self, db_manager, tmp_path):
        """Verify listing save slots."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        db_manager.save_to_slot(123, 0, b"data1", tmp_path / "slot0.state")
        db_manager.save_to_slot(123, 2, b"data2", tmp_path / "slot2.state")
        
        slots = db_manager.list_save_slots(123)
        assert len(slots) == 2
        slot_numbers = [s.slot_number for s in slots]
        assert 0 in slot_numbers
        assert 2 in slot_numbers
    
    def test_delete_slot(self, db_manager, tmp_path):
        """Verify deleting slot removes metadata and file."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        state_file = tmp_path / "slot0.state"
        db_manager.save_to_slot(123, 0, b"data", state_file)
        
        deleted = db_manager.delete_slot(123, 0)
        assert deleted is True
        
        info = db_manager.get_slot_info(123, 0)
        assert info is None
        assert not state_file.exists()
    
    def test_find_next_auto_save_slot(self, db_manager, tmp_path):
        """Verify round-robin auto-save slot selection."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        # Save auto-saves to slots 0 and 2
        db_manager.save_to_slot(123, 0, b"data0", tmp_path / "slot0.state", is_auto_save=True)
        db_manager.save_to_slot(123, 2, b"data2", tmp_path / "slot2.state", is_auto_save=True)
        
        next_slot = db_manager.find_next_auto_save_slot(123, num_slots=5)
        assert next_slot == 3  # Should be slot after 2
    
    def test_load_from_slot(self, db_manager, tmp_path):
        """Verify loading binary state data from slot."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        state_data = b"pyboy_save_state_data"
        db_manager.save_to_slot(123, 0, state_data, tmp_path / "slot0.state")
        
        loaded_data = db_manager.load_from_slot(123, 0)
        assert loaded_data == state_data
