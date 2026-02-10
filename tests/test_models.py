"""Tests for game state models.

This module tests all data models including ChatGameState, ChatConfig,
SaveSlotInfo, and GameSession.
"""

from datetime import datetime, timedelta

import pytest

from src.models.game_state import (
    BUTTON_LAYOUT,
    ChatConfig,
    ChatGameState,
    GameButton,
    GameSession,
    SaveSlotInfo,
)


class TestGameButton:
    """Test GameButton enum."""

    @pytest.mark.parametrize("button,expected", [
        (GameButton.UP, "up"),
        (GameButton.DOWN, "down"),
        (GameButton.LEFT, "left"),
        (GameButton.RIGHT, "right"),
        (GameButton.A, "a"),
        (GameButton.B, "b"),
        (GameButton.START, "start"),
        (GameButton.SELECT, "select"),
    ])
    def test_button_values(self, button, expected):
        """Test all buttons have correct string values."""
        assert button.value == expected

    @pytest.mark.parametrize("button,expected_emoji", [
        (GameButton.UP, "⬆️"),
        (GameButton.DOWN, "⬇️"),
        (GameButton.LEFT, "⬅️"),
        (GameButton.RIGHT, "➡️"),
        (GameButton.A, "🅰️"),
        (GameButton.B, "🅱️"),
        (GameButton.START, "START"),
        (GameButton.SELECT, "SELECT"),
    ])
    def test_button_emojis(self, button, expected_emoji):
        """Test emoji mapping."""
        assert button.emoji == expected_emoji

    @pytest.mark.parametrize("button,expected_name", [
        (GameButton.UP, "Cima"),
        (GameButton.DOWN, "Baixo"),
        (GameButton.LEFT, "Esquerda"),
        (GameButton.RIGHT, "Direita"),
        (GameButton.A, "A"),
        (GameButton.B, "B"),
        (GameButton.START, "Start"),
        (GameButton.SELECT, "Select"),
    ])
    def test_button_display_names(self, button, expected_name):
        """Test display name mapping."""
        assert button.display_name == expected_name
    
    def test_button_from_string(self):
        """Test creating button from string value."""
        assert GameButton("up") == GameButton.UP
        assert GameButton("a") == GameButton.A
        assert GameButton("start") == GameButton.START

    def test_wait_button_properties(self):
        """Test WAIT button has correct properties."""
        assert GameButton.WAIT.value == "wait"
        assert GameButton.WAIT.emoji == "👁️"
        assert GameButton.WAIT.display_name == "Espera"

    def test_wait_button_from_string(self):
        """Test creating WAIT button from string."""
        assert GameButton("wait") == GameButton.WAIT


class TestChatGameState:
    """Test ChatGameState dataclass."""
    
    @pytest.fixture
    def game_state(self):
        """Create a test game state."""
        return ChatGameState(
            chat_id=123456789,
            message_id=100,
            input_in_progress=False,
            last_input=GameButton.A,
            frame_hash="abc123",
        )
    
    def test_initial_state(self, game_state):
        """Test initial state creation."""
        assert game_state.chat_id == 123456789
        assert game_state.message_id == 100
        assert game_state.input_in_progress is False
        assert game_state.last_input == GameButton.A
        assert game_state.frame_hash == "abc123"
        assert isinstance(game_state.created_at, datetime)
        assert isinstance(game_state.updated_at, datetime)
    
    def test_to_dict(self, game_state):
        """Test serialization to dictionary."""
        data = game_state.to_dict()
        
        assert data["chat_id"] == 123456789
        assert data["message_id"] == 100
        assert data["input_in_progress"] is False
        assert data["last_input"] == "a"
        assert data["frame_hash"] == "abc123"
        assert "created_at" in data
        assert "updated_at" in data
    
    def test_to_dict_with_none_values(self):
        """Test serialization with None values."""
        state = ChatGameState(chat_id=123)
        data = state.to_dict()
        
        assert data["message_id"] is None
        assert data["last_input"] is None
        assert data["frame_hash"] is None
        assert data["last_input_time"] is None
    
    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "chat_id": 123456789,
            "message_id": 100,
            "input_in_progress": True,
            "last_input": "b",
            "last_input_time": "2024-01-01T12:00:00",
            "frame_hash": "def456",
            "created_at": "2024-01-01T10:00:00",
            "updated_at": "2024-01-01T12:00:00",
        }
        
        state = ChatGameState.from_dict(data)
        
        assert state.chat_id == 123456789
        assert state.message_id == 100
        assert state.input_in_progress is True
        assert state.last_input == GameButton.B
        assert state.frame_hash == "def456"
        assert state.last_input_time == datetime(2024, 1, 1, 12, 0, 0)
    
    def test_from_dict_with_none(self):
        """Test deserialization with None values."""
        data = {
            "chat_id": 123,
            "message_id": None,
            "input_in_progress": False,
            "last_input": None,
            "last_input_time": None,
            "frame_hash": None,
            "created_at": "2024-01-01T10:00:00",
            "updated_at": "2024-01-01T10:00:00",
        }
        
        state = ChatGameState.from_dict(data)
        
        assert state.last_input is None
        assert state.last_input_time is None
    
    def test_update_timestamp(self, game_state):
        """Test timestamp update."""
        old_updated = game_state.updated_at
        
        # Wait a tiny bit to ensure time difference
        import time
        time.sleep(0.01)
        
        game_state.update_timestamp()
        
        assert game_state.updated_at > old_updated


class TestChatConfig:
    """Test ChatConfig dataclass."""
    
    @pytest.fixture
    def chat_config(self):
        """Create a test chat config."""
        return ChatConfig(
            chat_id=123456789,
            input_hold_frames=45,
            animation_duration=15,
            auto_save_enabled=False,
        )
    
    def test_initial_config(self, chat_config):
        """Test initial config creation."""
        assert chat_config.chat_id == 123456789
        assert chat_config.input_hold_frames == 45
        assert chat_config.animation_duration == 15
        assert chat_config.auto_save_enabled is False
    
    def test_defaults(self):
        """Test default values."""
        config = ChatConfig(chat_id=123)
        
        assert config.input_hold_frames is None
        assert config.animation_duration is None
        assert config.auto_save_enabled is True
    
    def test_to_dict(self, chat_config):
        """Test serialization."""
        data = chat_config.to_dict()
        
        assert data["chat_id"] == 123456789
        assert data["input_hold_frames"] == 45
        assert data["animation_duration"] == 15
        assert data["auto_save_enabled"] is False
        assert "created_at" in data
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "chat_id": 123456789,
            "input_hold_frames": 60,
            "animation_duration": 20,
            "auto_save_enabled": True,
            "created_at": "2024-01-01T10:00:00",
            "updated_at": "2024-01-01T11:00:00",
        }
        
        config = ChatConfig.from_dict(data)
        
        assert config.chat_id == 123456789
        assert config.input_hold_frames == 60
        assert config.animation_duration == 20


class TestSaveSlotInfo:
    """Test SaveSlotInfo dataclass."""
    
    def test_basic_creation(self):
        """Test basic creation."""
        slot = SaveSlotInfo(slot_number=0)
        
        assert slot.slot_number == 0
        assert slot.is_auto_save is False
        assert slot.description is None
    
    def test_with_all_fields(self):
        """Test creation with all fields."""
        now = datetime.utcnow()
        slot = SaveSlotInfo(
            slot_number=2,
            created_at=now,
            updated_at=now,
            is_auto_save=True,
            description="Before gym battle",
        )
        
        assert slot.slot_number == 2
        assert slot.is_auto_save is True
        assert slot.description == "Before gym battle"
    
    def test_to_dict(self):
        """Test serialization."""
        slot = SaveSlotInfo(slot_number=1, is_auto_save=True)
        data = slot.to_dict()
        
        assert data["slot_number"] == 1
        assert data["is_auto_save"] is True
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "slot_number": 3,
            "created_at": "2024-01-01T10:00:00",
            "updated_at": "2024-01-01T12:00:00",
            "is_auto_save": False,
            "description": "Test save",
        }
        
        slot = SaveSlotInfo.from_dict(data)
        
        assert slot.slot_number == 3
        assert slot.is_auto_save is False
        assert slot.description == "Test save"
        assert slot.created_at == datetime(2024, 1, 1, 10, 0, 0)


class TestGameSession:
    """Test GameSession dataclass."""
    
    @pytest.fixture
    def game_session(self):
        """Create a test game session."""
        state = ChatGameState(chat_id=123456789)
        return GameSession(chat_id=123456789, state=state)
    
    def test_initial_session(self, game_session):
        """Test initial session creation."""
        assert game_session.chat_id == 123456789
        assert game_session.total_inputs == 0
        assert isinstance(game_session.last_activity, datetime)
        assert isinstance(game_session.state, ChatGameState)
    
    def test_record_activity(self, game_session):
        """Test recording activity."""
        old_activity = game_session.last_activity
        old_total = game_session.total_inputs
        
        # Wait a tiny bit
        import time
        time.sleep(0.01)
        
        game_session.record_activity()
        
        assert game_session.total_inputs == old_total + 1
        assert game_session.last_activity > old_activity
    
    def test_is_idle_false(self, game_session):
        """Test is_idle returns False for recent activity."""
        assert game_session.is_idle(timeout_seconds=3600) is False
    
    def test_is_idle_true(self, game_session):
        """Test is_idle returns True for old activity."""
        # Set last activity to 2 hours ago
        game_session.last_activity = datetime.utcnow() - timedelta(hours=2)
        
        assert game_session.is_idle(timeout_seconds=3600) is True
    
    def test_is_idle_custom_timeout(self, game_session):
        """Test is_idle with custom timeout."""
        # Set last activity to 5 minutes ago
        game_session.last_activity = datetime.utcnow() - timedelta(minutes=5)
        
        # Should be idle with 1 minute timeout
        assert game_session.is_idle(timeout_seconds=60) is True
        
        # Should not be idle with 10 minute timeout
        assert game_session.is_idle(timeout_seconds=600) is False


class TestButtonLayout:
    """Test button layout configuration."""
    
    def test_layout_structure(self):
        """Test button layout is correctly structured."""
        # Should be a list of lists
        assert isinstance(BUTTON_LAYOUT, list)
        assert all(isinstance(row, list) for row in BUTTON_LAYOUT)

        # Check first row (Up and Wait buttons)
        assert GameButton.UP in BUTTON_LAYOUT[0]
        assert GameButton.WAIT in BUTTON_LAYOUT[0]

        # Check second row (Left, Right)
        assert GameButton.LEFT in BUTTON_LAYOUT[1]
        assert GameButton.RIGHT in BUTTON_LAYOUT[1]

        # Check third row (RUN, SEQUENCE, DOWN)
        assert GameButton.RUN in BUTTON_LAYOUT[2]
        assert GameButton.SEQUENCE in BUTTON_LAYOUT[2]
        assert GameButton.DOWN in BUTTON_LAYOUT[2]

        # Check fourth row (A, B)
        assert GameButton.A in BUTTON_LAYOUT[3]
        assert GameButton.B in BUTTON_LAYOUT[3]

        # Check fifth row (Start, Select)
        assert GameButton.START in BUTTON_LAYOUT[4]
        assert GameButton.SELECT in BUTTON_LAYOUT[4]
    
    def test_all_buttons_in_layout(self):
        """Test all buttons are included in layout (except ENVIAR which is only shown during sequence building)."""
        all_buttons = set()
        for row in BUTTON_LAYOUT:
            all_buttons.update(row)

        # ENVIAR is not in the normal layout - it replaces SEQUENCE during sequence building
        expected_buttons = set(GameButton) - {GameButton.ENVIAR}
        assert all_buttons == expected_buttons
        assert len(all_buttons) == 11  # 11 buttons (excluding ENVIAR)

    def test_wait_button_in_first_row(self):
        """Test WAIT button is positioned with UP button."""
        assert GameButton.WAIT in BUTTON_LAYOUT[0]
        assert GameButton.UP in BUTTON_LAYOUT[0]
        assert len(BUTTON_LAYOUT[0]) == 2
