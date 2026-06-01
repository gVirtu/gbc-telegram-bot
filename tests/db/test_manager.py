"""Tests for DatabaseManager."""
import pytest
from datetime import datetime

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
            modifier_states={}
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
        )
        
        db_manager.save_game_state(state)
        
        loaded = db_manager.load_game_state(123)
        assert loaded is not None
        assert loaded.chat_id == 123
        assert loaded.message_id == 456
        assert loaded.input_in_progress is True
        assert loaded.last_input == GameButton.A
    
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
        db_manager.save_game_state(state, save_user_input_counts=True)
        
        loaded = db_manager.load_game_state(123)
        assert loaded.user_input_counts == {"111": 5, "222": 3}
    
    def test_save_game_state_with_recent_inputs(self, db_manager):
        """Verify recent inputs are queryable via get_recent_inputs_for_overlay."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)

        db_manager.append_recent_input(
            chat_id=123,
            user_id=111,
            user_name="Alice",
            button="a",
            timestamp=datetime.utcnow().isoformat()
        )

        rows = db_manager.get_recent_inputs_for_overlay(123)
        assert len(rows) == 1
        assert rows[0]["user_name"] == "Alice"



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


def test_db_package_imports():
    """Verify all public exports are importable."""
    from src.db import DatabaseManager, DatabaseConnection, get_db_path
    
    assert DatabaseManager is not None
    assert DatabaseConnection is not None
    assert callable(get_db_path)


class TestUtilityOperations:
    """Test utility operations."""
    
    def test_chat_exists_with_game_state(self, db_manager):
        """Verify chat_exists returns True with game state."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        assert db_manager.chat_exists(123) is True
    
    def test_chat_exists_with_config(self, db_manager):
        """Verify chat_exists returns True with config."""
        config = ChatConfig(chat_id=456)
        db_manager.save_chat_config(config)
        
        assert db_manager.chat_exists(456) is True
    
    def test_chat_exists_with_save_slot(self, db_manager, tmp_path):
        """Verify chat_exists returns True with save slot."""
        state = ChatGameState(chat_id=789)
        db_manager.save_game_state(state)
        
        db_manager.save_to_slot(789, 0, b"data", tmp_path / "slot.state")
        
        assert db_manager.chat_exists(789) is True
    
    def test_chat_exists_nonexistent(self, db_manager):
        """Verify chat_exists returns False for nonexistent chat."""
        assert db_manager.chat_exists(999) is False
    
    def test_delete_all_chat_data(self, db_manager, tmp_path):
        """Verify delete_all removes all data for chat."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        config = ChatConfig(chat_id=123)
        db_manager.save_chat_config(config)
        
        db_manager.save_to_slot(123, 0, b"data", tmp_path / "slot.state")
        
        deleted = db_manager.delete_all_chat_data(123)
        assert deleted is True
        
        assert db_manager.load_game_state(123) is None
        assert db_manager.load_chat_config(123) is None
        assert db_manager.list_save_slots(123) == []
    
    def test_delete_all_chat_data_nonexistent(self, db_manager):
        """Verify delete_all returns False for nonexistent chat."""
        result = db_manager.delete_all_chat_data(999)
        assert result is False


class TestDatabaseManagerMigrationHandling:
    """Test DatabaseManager handles migration errors correctly."""
    
    def test_manager_initialization_propagates_migration_error(self, tmp_path):
        """Verify DatabaseManager propagates migration errors."""
        import src.db.migrations.runner
        from src.db.manager import DatabaseManager
        from src.db.migrations.runner import MigrationError
        
        original_discover = src.db.migrations.runner.discover_migrations
        
        def mock_discover_with_failure():
            from src.db.migrations.base import Migration
            
            def failing_upgrade(conn):
                raise RuntimeError("Migration failed during manager init!")
            
            return [
                Migration(version=1, name="001_baseline", upgrade=lambda c: None, downgrade=None),
                Migration(version=2, name="002_failing", upgrade=failing_upgrade, downgrade=None),
            ]
        
        src.db.migrations.runner.discover_migrations = mock_discover_with_failure
        
        manager = DatabaseManager(tmp_path / "test.db")
        try:
            with pytest.raises(MigrationError) as exc_info:
                manager.initialize()
            
            assert "Migration failed during manager init!" in str(exc_info.value)
        finally:
            src.db.migrations.runner.discover_migrations = original_discover
            if hasattr(manager, 'connection'):
                manager.close()

    def test_save_and_load_chat_config_with_language(self, db_manager):
        """Verify saving and loading config with language field."""
        config = ChatConfig(
            chat_id=123,
            input_hold_frames=10,
            auto_save_enabled=True,
            language="en-US"
        )
        
        db_manager.save_chat_config(config)
        
        loaded = db_manager.load_chat_config(123)
        assert loaded is not None
        assert loaded.language == "en-US"
    
    def test_save_chat_config_with_none_language(self, db_manager):
        """Verify saving config with None language works."""
        config = ChatConfig(
            chat_id=456,
            language=None
        )
        
        db_manager.save_chat_config(config)
        
        loaded = db_manager.load_chat_config(456)
        assert loaded is not None
        assert loaded.language is None
    
    def test_update_language_on_existing_config(self, db_manager):
        """Verify updating language on existing config."""
        # Create config without language
        config1 = ChatConfig(chat_id=789)
        db_manager.save_chat_config(config1)
        
        # Update with language
        config2 = ChatConfig(chat_id=789, language="pt-BR")
        db_manager.save_chat_config(config2)
        
        # Verify language was updated
        loaded = db_manager.load_chat_config(789)
        assert loaded.language == "pt-BR"
    
    def test_change_language_from_one_to_another(self, db_manager):
        """Verify changing language from one value to another."""
        # Create with pt-BR
        config1 = ChatConfig(chat_id=111, language="pt-BR")
        db_manager.save_chat_config(config1)
        
        # Change to en-US
        config2 = ChatConfig(chat_id=111, language="en-US")
        db_manager.save_chat_config(config2)
        
        # Verify change
        loaded = db_manager.load_chat_config(111)
        assert loaded.language == "en-US"
    
    def test_clear_language_to_none(self, db_manager):
        """Verify clearing language back to None."""
        # Create with language
        config1 = ChatConfig(chat_id=222, language="en-US")
        db_manager.save_chat_config(config1)
        
        # Clear to None
        config2 = ChatConfig(chat_id=222, language=None)
        db_manager.save_chat_config(config2)
        
        # Verify cleared
        loaded = db_manager.load_chat_config(222)
        assert loaded.language is None


class TestGameEventsOperations:
    """Test game events insertion and querying."""

    def test_insert_game_events(self, db_manager):
        events = [
            {"event_type": "level_up", "awarded_score": 100, "frame_offset": 10},
            {"event_type": "boss_defeated", "awarded_score": 500, "frame_offset": 50},
        ]
        user_ids = [111, 222]
        event_ids = db_manager.insert_game_events(
            chat_id=123,
            cartridge_title="Zelda",
            events=events,
            user_ids=user_ids,
            platform="telegram",
        )
        assert len(event_ids) == 2
        assert event_ids[0] > 0
        assert event_ids[1] > event_ids[0]

        rows = db_manager.connection.execute(
            "SELECT * FROM game_events WHERE chat_id = ? ORDER BY id;",
            (123,),
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["event_type"] == "level_up"
        assert rows[0]["awarded_score"] == 100
        assert rows[0]["cartridge_title"] == "Zelda"

        for ev_id in event_ids:
            user_rows = db_manager.connection.execute(
                "SELECT user_id FROM game_event_users WHERE event_id = ? ORDER BY user_id;",
                (ev_id,),
            ).fetchall()
            assert [r["user_id"] for r in user_rows] == [111, 222]

    def test_get_game_events_for_chat(self, db_manager):
        events = [
            {"event_type": "collect", "awarded_score": 10, "frame_offset": 10},
            {"event_type": "collect", "awarded_score": 20, "frame_offset": 20},
            {"event_type": "collect", "awarded_score": 30, "frame_offset": 30},
        ]
        db_manager.insert_game_events(
            chat_id=456,
            cartridge_title="Pokemon",
            events=events,
            user_ids=[333],
            platform="discord",
        )

        result = db_manager.get_game_events_for_chat(456, min_frame_offset=15)
        assert len(result) == 2
        assert result[0]["frame_offset"] == 20
        assert result[0]["user_ids"] == [333]
        assert result[1]["frame_offset"] == 30
        assert result[1]["user_ids"] == [333]

    def test_insert_game_events_no_commit(self, db_manager):
        from src.db.connection import DatabaseConnection

        events = [{"event_type": "score", "awarded_score": 50, "frame_offset": 5}]
        event_ids = db_manager.insert_game_events(
            chat_id=789,
            cartridge_title="Metroid",
            events=events,
            user_ids=[444],
            platform="telegram",
            commit=False,
        )
        assert len(event_ids) == 1

        alt_conn = DatabaseConnection(db_manager.connection.db_path)
        alt_conn.initialize()
        try:
            rows = alt_conn.execute(
                "SELECT * FROM game_events WHERE chat_id = ?;",
                (789,),
            ).fetchall()
            assert len(rows) == 0
        finally:
            alt_conn.close()

        db_manager.connection.commit()

        rows = db_manager.connection.execute(
            "SELECT * FROM game_events WHERE chat_id = ?;",
            (789,),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "score"
