"""Tests for state management.

This module tests file-based persistence including game state,
configuration, and save slots.
"""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models.game_state import ChatConfig, ChatGameState, GameButton, SaveSlotInfo, TimelapseJobRow
from src.utils.state_manager import StateManager


class TestStateManagerInitialization:
    """Test StateManager initialization."""
    
    def test_default_initialization(self, tmp_path):
        """Test initialization with default data_dir."""
        # This would use settings.data_dir, so we test with explicit path
        manager = StateManager(data_dir=tmp_path)
        
        assert manager.data_dir == tmp_path
        # Check database is created
        assert (tmp_path / "bot.db").exists()


class TestGameStatePersistence:
    """Test game state save/load operations."""
    
    @pytest.fixture
    def manager(self, tmp_path):
        """Create a state manager with temp directory."""
        return StateManager(data_dir=tmp_path)
    
    def test_load_game_state(self, manager):
        """Test loading game state."""
        # First save a state
        state = ChatGameState(
            chat_id=123456,
            message_id=789,
            last_input=GameButton.B,
        )
        manager.save_game_state(state)
        
        # Load it back
        loaded = manager.load_game_state(123456)
        
        assert loaded is not None
        assert loaded.chat_id == 123456
        assert loaded.message_id == 789
        assert loaded.last_input == GameButton.B
    
    def test_load_nonexistent_state(self, manager):
        """Test loading state that doesn't exist."""
        loaded = manager.load_game_state(999999)
        
        assert loaded is None
    
    def test_delete_game_state(self, manager):
        """Test deleting game state."""
        # Create state
        state = ChatGameState(chat_id=123456)
        manager.save_game_state(state)
        
        # Delete it
        result = manager.delete_game_state(123456)
        
        assert result is True
        assert manager.load_game_state(123456) is None
    
    def test_delete_nonexistent_state(self, manager):
        """Test deleting state that doesn't exist."""
        result = manager.delete_game_state(999999)

        assert result is False

    def test_global_frame_count_round_trips(self, manager):
        """global_frame_count is saved and loaded correctly."""
        state = ChatGameState(chat_id=111222, global_frame_count=750)
        manager.save_game_state(state)

        loaded = manager.load_game_state(111222)
        assert loaded is not None
        assert loaded.global_frame_count == 750

    def test_global_frame_count_defaults_to_zero(self, manager):
        """global_frame_count defaults to 0 for states loaded before migration."""
        state = ChatGameState(chat_id=333444)
        manager.save_game_state(state)

        loaded = manager.load_game_state(333444)
        assert loaded.global_frame_count == 0


class TestChatConfigPersistence:
    """Test chat configuration persistence."""
    
    @pytest.fixture
    def manager(self, tmp_path):
        """Create a state manager with temp directory."""
        return StateManager(data_dir=tmp_path)
    
    def test_load_chat_config(self, manager):
        """Test loading chat configuration."""
        # Save config
        config = ChatConfig(
            chat_id=123456,
            input_hold_frames=60,
            animation_duration=20,
        )
        manager.save_chat_config(config)
        
        # Load it
        loaded = manager.load_chat_config(123456)
        
        assert loaded is not None
        assert loaded.chat_id == 123456
        assert loaded.input_hold_frames == 60
        assert loaded.animation_duration == 20
    
    def test_get_or_create_chat_config_new(self, manager):
        """Test creating new config when none exists."""
        config = manager.get_or_create_chat_config(123456)
        
        assert config.chat_id == 123456
        assert config.input_hold_frames is None  # Default
        
        # Should be saved
        assert manager.load_chat_config(123456) is not None
    
    def test_get_or_create_chat_config_existing(self, manager):
        """Test loading existing config."""
        # Create config with custom values
        config = ChatConfig(chat_id=123456, input_hold_frames=45)
        manager.save_chat_config(config)
        
        # Get it
        loaded = manager.get_or_create_chat_config(123456)
        
        assert loaded.input_hold_frames == 45


class TestSaveSlots:
    """Test save slot operations."""
    
    @pytest.fixture
    def manager(self, tmp_path):
        """Create a state manager with temp directory."""
        return StateManager(data_dir=tmp_path)
    
    def test_save_to_slot(self, manager):
        """Test saving to a slot."""
        # Need game state first
        state = ChatGameState(chat_id=123456)

        manager.save_game_state(state)

        state_data = b"fake save state data"
        
        info = manager.save_to_slot(
            chat_id=123456,
            slot_number=0,
            state_data=state_data,
            description="Test save",
        )
        
        assert info.slot_number == 0
        assert info.description == "Test save"

        # Check file exists
        slot_file = manager.data_dir / "saves" / "123456" / "slot_0.state"
        assert slot_file.exists()
    
    def test_load_from_slot(self, manager):
        """Test loading from a slot."""
        # Need game state first
        state = ChatGameState(chat_id=123456)

        manager.save_game_state(state)

        # Save data
        state_data = b"test data 12345"
        manager.save_to_slot(123456, 1, state_data)
        
        # Load it
        loaded = manager.load_from_slot(123456, 1)
        
        assert loaded == state_data
    
    def test_load_nonexistent_slot(self, manager):
        """Test loading from slot that doesn't exist."""
        loaded = manager.load_from_slot(123456, 99)
        
        assert loaded is None
    
    def test_list_save_slots(self, manager):
        """Test listing save slots."""
        # Need game state first
        state = ChatGameState(chat_id=123456)

        manager.save_game_state(state)

        # Create multiple slots
        manager.save_to_slot(123456, 0, b"data0")
        manager.save_to_slot(123456, 2, b"data2")
        manager.save_to_slot(123456, 4, b"data4")
        
        slots = manager.list_save_slots(123456, max_slots=5)
        
        assert len(slots) == 3
        slot_numbers = [s.slot_number for s in slots]
        assert 0 in slot_numbers
        assert 2 in slot_numbers
        assert 4 in slot_numbers
    
    def test_list_save_slots_empty(self, manager):
        """Test listing slots when none exist."""
        slots = manager.list_save_slots(123456, max_slots=5)
        
        assert slots == []
    
    def test_delete_slot(self, manager):
        """Test deleting a slot."""
        # Need game state first
        state = ChatGameState(chat_id=123456)

        manager.save_game_state(state)

        # Create slot
        manager.save_to_slot(123456, 0, b"data")
        
        # Delete it
        result = manager.delete_slot(123456, 0)
        
        assert result is True
        assert manager.load_from_slot(123456, 0) is None
    
    def test_find_next_auto_save_slot_empty(self, manager):
        """Test finding next auto-save slot when none exist."""
        slot = manager.find_next_auto_save_slot(123456, num_slots=5)
        
        assert slot == 0
    
    def test_find_next_auto_save_slot_with_existing(self, manager):
        """Test finding next auto-save slot with existing saves."""
        # Need game state first
        state = ChatGameState(chat_id=123456)

        manager.save_game_state(state)

        # Create auto-saves in slots 0 and 1
        manager.save_to_slot(123456, 0, b"data", is_auto_save=True)
        manager.save_to_slot(123456, 1, b"data", is_auto_save=True)
        
        # Next should be slot 2
        slot = manager.find_next_auto_save_slot(123456, num_slots=5)
        
        assert slot == 2
    
    def test_find_next_auto_save_slot_wraparound(self, manager):
        """Test auto-save slot wraps around after reaching limit."""
        # Need game state first
        state = ChatGameState(chat_id=123456)

        manager.save_game_state(state)

        # Create saves in all 3 slots (with num_slots=3)
        manager.save_to_slot(123456, 0, b"data", is_auto_save=True)
        manager.save_to_slot(123456, 1, b"data", is_auto_save=True)
        manager.save_to_slot(123456, 2, b"data", is_auto_save=True)
        
        # With num_slots=3, next should wrap to 0
        slot = manager.find_next_auto_save_slot(123456, num_slots=3)
        assert slot == 0  # Wraps around


class TestChatManagement:
    """Test chat-level operations."""
    
    @pytest.fixture
    def manager(self, tmp_path):
        """Create a state manager with temp directory."""
        return StateManager(data_dir=tmp_path)
    
    def test_chat_exists_with_game_state(self, manager):
        """Test checking if chat exists with game state."""
        state = ChatGameState(chat_id=123456)
        manager.save_game_state(state)
        
        assert manager.chat_exists(123456) is True
    
    def test_chat_exists_with_config(self, manager):
        """Test checking if chat exists with config."""
        config = ChatConfig(chat_id=123456)
        manager.save_chat_config(config)
        
        assert manager.chat_exists(123456) is True
    
    def test_chat_exists_with_saves(self, manager):
        """Test checking if chat exists with saves."""
        # Need game state first
        state = ChatGameState(chat_id=123456)

        manager.save_game_state(state)

        manager.save_to_slot(123456, 0, b"data")
        
        assert manager.chat_exists(123456) is True
    
    def test_chat_exists_nonexistent(self, manager):
        """Test checking if nonexistent chat exists."""
        assert manager.chat_exists(999999) is False
    
    def test_delete_all_chat_data(self, manager):
        """Test deleting all data for a chat."""
        # Create various data
        manager.save_game_state(ChatGameState(chat_id=123456))
        manager.save_chat_config(ChatConfig(chat_id=123456))
        manager.save_to_slot(123456, 0, b"data")
        
        # Delete all
        result = manager.delete_all_chat_data(123456)
        
        assert result is True
        assert manager.chat_exists(123456) is False
        assert manager.load_game_state(123456) is None
        assert manager.load_chat_config(123456) is None
    
    def test_delete_all_chat_data_nonexistent(self, manager):
        """Test deleting all data for nonexistent chat."""
        result = manager.delete_all_chat_data(999999)
        
        assert result is False


class TestPathHelpers:
    """Test internal path helper methods."""
    
    @pytest.fixture
    def manager(self, tmp_path):
        """Create a state manager with temp directory."""
        return StateManager(data_dir=tmp_path)
    
    def test_get_save_slot_path(self, manager):
        """Test save slot path generation."""
        path = manager.get_save_slot_path(123456, 2)
        
        assert "saves" in str(path)
        assert "123456" in str(path)
        assert "slot_2.state" in str(path)
    
    def test_get_save_info_path(self, manager):
        """Test save info path generation."""
        path = manager.get_save_info_path(123456, 2)
        
        assert "saves" in str(path)
        assert "123456" in str(path)
        assert "slot_2.json" in str(path)
    

class TestErrorHandling:
    """Test error handling and edge cases."""
    
    @pytest.fixture
    def manager(self, tmp_path):
        """Create a state manager with temp directory."""
        return StateManager(data_dir=tmp_path)
    
    def test_update_existing_state(self, manager):
        """Test updating an existing state."""
        # Create initial state
        state1 = ChatGameState(chat_id=123456, message_id=100)
        manager.save_game_state(state1)

        # Update with new state
        state2 = ChatGameState(chat_id=123456, message_id=200)
        manager.save_game_state(state2)

        # Should have new values
        loaded = manager.load_game_state(123456)
        assert loaded.message_id == 200


class TestTimelapseJobMethods:
    """Tests for timelapse job CRUD methods on StateManager."""

    @pytest.fixture
    def manager(self, tmp_path):
        return StateManager(data_dir=tmp_path)

    def _ctx(self, frame_count=10):
        return {
            "frame_count": frame_count,
            "frame_skip": 1,
            "capture_fps": 15,
            "timelapse_fps": 10,
            "pre_existing_inputs": [],
            "new_inputs_with_offsets": [],
            "reactions": [],
            "user_colors": {},
        }

    # ── insert_timelapse_job ──────────────────────────────────────────────────

    def test_insert_returns_int_id(self, manager, tmp_path):
        job_id = manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        assert isinstance(job_id, int)
        assert job_id >= 1

    def test_insert_stores_pending_status(self, manager, tmp_path):
        manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        job = manager.fetch_next_pending_job("123")
        assert job is not None
        assert job.status == "pending"

    def test_insert_round_trips_compositing_context(self, manager, tmp_path):
        ctx = self._ctx(frame_count=42)
        manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, ctx)
        job = manager.fetch_next_pending_job("123")
        assert job.compositing_context["frame_count"] == 42
        assert job.frame_count == 42

    def test_insert_multiple_jobs_same_chat(self, manager, tmp_path):
        manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        manager.insert_timelapse_job("123", "/frames/b", "2026-01-01T00:01:00", 10, self._ctx())
        # Both should exist as pending
        assert len(manager.get_chats_with_pending_jobs()) == 1

    # ── fetch_next_pending_job ────────────────────────────────────────────────

    def test_fetch_returns_none_when_empty(self, manager):
        assert manager.fetch_next_pending_job("999") is None

    def test_fetch_returns_oldest_first(self, manager):
        manager.insert_timelapse_job("123", "/frames/old", "2026-01-01T10:00:00", 10, self._ctx())
        manager.insert_timelapse_job("123", "/frames/new", "2026-01-01T10:01:00", 10, self._ctx())
        job = manager.fetch_next_pending_job("123")
        assert job.folder_path == "/frames/old"

    def test_fetch_ignores_other_chats(self, manager):
        manager.insert_timelapse_job("456", "/frames/other", "2026-01-01T00:00:00", 10, self._ctx())
        assert manager.fetch_next_pending_job("123") is None

    def test_fetch_ignores_non_pending_jobs(self, manager):
        job_id = manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        manager.update_job_status(job_id, "done")
        assert manager.fetch_next_pending_job("123") is None

    # ── update_job_status ─────────────────────────────────────────────────────

    def test_update_status_to_processing(self, manager):
        job_id = manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        manager.update_job_status(job_id, "processing")
        # Job is no longer "pending", so fetch returns None
        assert manager.fetch_next_pending_job("123") is None

    def test_update_status_to_done(self, manager):
        job_id = manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        manager.update_job_status(job_id, "done")
        assert manager.fetch_next_pending_job("123") is None

    def test_update_status_to_failed(self, manager):
        job_id = manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        manager.update_job_status(job_id, "failed")
        assert manager.fetch_next_pending_job("123") is None

    # ── reset_stuck_jobs ──────────────────────────────────────────────────────

    def test_reset_stuck_jobs_returns_count(self, manager):
        job_id = manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        manager.update_job_status(job_id, "processing")
        count = manager.reset_stuck_jobs()
        assert count == 1

    def test_reset_stuck_jobs_makes_processing_pending_again(self, manager):
        job_id = manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        manager.update_job_status(job_id, "processing")
        manager.reset_stuck_jobs()
        job = manager.fetch_next_pending_job("123")
        assert job is not None
        assert job.status == "pending"

    def test_reset_stuck_jobs_ignores_done_and_failed(self, manager):
        id1 = manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        id2 = manager.insert_timelapse_job("123", "/frames/b", "2026-01-01T00:01:00", 10, self._ctx())
        manager.update_job_status(id1, "done")
        manager.update_job_status(id2, "failed")
        count = manager.reset_stuck_jobs()
        assert count == 0

    def test_reset_stuck_jobs_zero_when_none_stuck(self, manager):
        manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        assert manager.reset_stuck_jobs() == 0

    # ── get_chats_with_pending_jobs ───────────────────────────────────────────

    def test_get_chats_empty_when_no_jobs(self, manager):
        assert manager.get_chats_with_pending_jobs() == []

    def test_get_chats_returns_distinct_chat_ids(self, manager):
        manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        manager.insert_timelapse_job("123", "/frames/b", "2026-01-01T00:01:00", 10, self._ctx())
        manager.insert_timelapse_job("456", "/frames/c", "2026-01-01T00:00:00", 10, self._ctx())
        chats = manager.get_chats_with_pending_jobs()
        assert sorted(chats) == ["123", "456"]

    def test_get_chats_excludes_non_pending(self, manager):
        job_id = manager.insert_timelapse_job("123", "/frames/a", "2026-01-01T00:00:00", 10, self._ctx())
        manager.update_job_status(job_id, "done")
        manager.insert_timelapse_job("456", "/frames/b", "2026-01-01T00:00:00", 10, self._ctx())
        chats = manager.get_chats_with_pending_jobs()
        assert chats == ["456"]

    # ── cleanup_orphaned_folders ──────────────────────────────────────────────

    def test_cleanup_returns_zero_when_no_frames_dir(self, manager, tmp_path):
        with patch("src.utils.state_manager.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            count = manager.cleanup_orphaned_folders()
        assert count == 0

    def test_cleanup_deletes_folder_with_no_db_row(self, manager, tmp_path):
        orphan = tmp_path / "frames" / "123" / "20260101_orphan"
        orphan.mkdir(parents=True)
        (orphan / "frame_000000.npy").write_bytes(b"fake")

        with patch("src.utils.state_manager.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            count = manager.cleanup_orphaned_folders()

        assert count == 1
        assert not orphan.exists()

    def test_cleanup_preserves_folder_with_db_row(self, manager, tmp_path):
        folder = tmp_path / "frames" / "123" / "20260101_known"
        folder.mkdir(parents=True)
        manager.insert_timelapse_job("123", str(folder), "2026-01-01T00:00:00", 10, self._ctx())

        with patch("src.utils.state_manager.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            count = manager.cleanup_orphaned_folders()

        assert count == 0
        assert folder.exists()

    def test_cleanup_deletes_only_orphans(self, manager, tmp_path):
        known = tmp_path / "frames" / "123" / "20260101_known"
        known.mkdir(parents=True)
        orphan = tmp_path / "frames" / "123" / "20260101_orphan"
        orphan.mkdir(parents=True)
        manager.insert_timelapse_job("123", str(known), "2026-01-01T00:00:00", 10, self._ctx())

        with patch("src.utils.state_manager.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            count = manager.cleanup_orphaned_folders()

        assert count == 1
        assert known.exists()
        assert not orphan.exists()
