"""Integration tests for database migration."""
from src.db import DatabaseManager
from src.models.game_state import ChatGameState

class TestStateManagerCompatibility:
    """Test DatabaseManager provides same interface as StateManager."""
    
    def test_both_managers_have_same_methods(self):
        """Verify DatabaseManager has all StateManager methods."""
        required_methods = {
            'save_game_state', 'load_game_state', 'delete_game_state',
            'save_chat_config', 'load_chat_config', 'get_or_create_chat_config',
            'save_to_slot', 'load_from_slot', 'get_slot_info', 'list_save_slots', 'delete_slot',
            'find_next_auto_save_slot', 'chat_exists', 'delete_all_chat_data'
        }
        
        for method in required_methods:
            assert hasattr(DatabaseManager, method), f"DatabaseManager missing {method}"
    
    def test_game_state_roundtrip(self, tmp_path):
        """Verify game state saved by DatabaseManager can be loaded correctly."""
        db_manager = DatabaseManager(tmp_path / "test.db")
        db_manager.initialize()
        
        state = ChatGameState(
            chat_id=123,
            message_id=456,
            input_in_progress=True
        )
        
        db_manager.save_game_state(state)
        loaded = db_manager.load_game_state(123)
        
        assert loaded.chat_id == state.chat_id
        assert loaded.message_id == state.message_id
        assert loaded.input_in_progress == state.input_in_progress
