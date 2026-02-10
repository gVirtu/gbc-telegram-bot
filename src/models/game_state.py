"""Data models for the Telegram GBC Bot.

This module defines all data structures used throughout the application,
including game state, chat configuration, and input tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class GameButton(str, Enum):
    """GameBoy buttons supported by the bot."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    A = "a"
    B = "b"
    START = "start"
    SELECT = "select"
    WAIT = "wait"
    SEQUENCE = "sequence"
    ENVIAR = "enviar"
    RUN = "run"
    
    @property
    def emoji(self) -> str:
        """Get the emoji representation of the button."""
        emoji_map = {
            GameButton.UP: "⬆️",
            GameButton.DOWN: "⬇️",
            GameButton.LEFT: "⬅️",
            GameButton.RIGHT: "➡️",
            GameButton.A: "🅰️",
            GameButton.B: "🅱️",
            GameButton.START: "START",
            GameButton.SELECT: "SELECT",
            GameButton.WAIT: "👁️",
            GameButton.SEQUENCE: "🔢 SEQUÊNCIA",
            GameButton.ENVIAR: "✅",
            GameButton.RUN: "🏃",
        }
        return emoji_map[self]
    
    @property
    def display_name(self) -> str:
        """Get human-readable button name."""
        name_map = {
            GameButton.UP: "Cima",
            GameButton.DOWN: "Baixo",
            GameButton.LEFT: "Esquerda",
            GameButton.RIGHT: "Direita",
            GameButton.A: "A",
            GameButton.B: "B",
            GameButton.START: "Start",
            GameButton.SELECT: "Select",
            GameButton.WAIT: "Espera",
            GameButton.SEQUENCE: "Sequência",
            GameButton.ENVIAR: "Enviar",
            GameButton.RUN: "Correr",
        }
        return name_map[self]


@dataclass
class SequenceBuilder:
    """Tracks the state of a sequence being built."""
    user_id: int
    user_name: str
    buttons: list[GameButton] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)
    max_length: int = 4

    def add_button(self, button: GameButton) -> bool:
        """Add button to sequence. Returns False if full."""
        if len(self.buttons) >= self.max_length:
            return False
        self.buttons.append(button)
        return True

    def is_full(self) -> bool:
        return len(self.buttons) >= self.max_length

    def is_empty(self) -> bool:
        return len(self.buttons) == 0

    def has_timed_out(self, timeout_seconds: float) -> bool:
        elapsed = (datetime.utcnow() - self.start_time).total_seconds()
        return elapsed > timeout_seconds

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "buttons": [b.value for b in self.buttons],
            "start_time": self.start_time.isoformat(),
            "max_length": self.max_length,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SequenceBuilder":
        return cls(
            user_id=data["user_id"],
            user_name=data["user_name"],
            buttons=[GameButton(b) for b in data.get("buttons", [])],
            start_time=datetime.fromisoformat(data["start_time"]),
            max_length=data.get("max_length", 4),
        )


@dataclass
class ChatGameState:
    """Represents the current game state for a chat.

    This tracks whether input is being processed, the current message ID,
    and the last input for display purposes.

    Attributes:
        chat_id: Telegram chat ID
        message_id: ID of the message showing the game frame
        input_in_progress: Whether an input is currently being processed
        last_input: The last button that was pressed
        last_input_time: When the last input was processed
        frame_hash: Hash of the last sent frame (for optimization)
        user_input_counts: Track total inputs per user (user_id -> count)
        recent_inputs: Last 3 inputs with user info (FIFO)
        created_at: When this game state was created
        updated_at: When this game state was last updated
    """

    chat_id: int
    message_id: Optional[int] = None
    input_in_progress: bool = False
    last_input: Optional[GameButton] = None
    last_input_time: Optional[datetime] = None
    frame_hash: Optional[str] = None
    user_input_counts: dict[int, int] = field(default_factory=dict)
    recent_inputs: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    sequence_builder: Optional[SequenceBuilder] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "input_in_progress": self.input_in_progress,
            "last_input": self.last_input.value if self.last_input else None,
            "last_input_time": self.last_input_time.isoformat() if self.last_input_time else None,
            "frame_hash": self.frame_hash,
            "user_input_counts": self.user_input_counts,
            "recent_inputs": self.recent_inputs,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "sequence_builder": self.sequence_builder.to_dict() if self.sequence_builder else None,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ChatGameState":
        """Create instance from dictionary."""
        return cls(
            chat_id=data["chat_id"],
            message_id=data.get("message_id"),
            input_in_progress=data.get("input_in_progress", False),
            last_input=GameButton(data["last_input"]) if data.get("last_input") else None,
            last_input_time=datetime.fromisoformat(data["last_input_time"]) if data.get("last_input_time") else None,
            frame_hash=data.get("frame_hash"),
            user_input_counts=data.get("user_input_counts", {}),
            recent_inputs=data.get("recent_inputs", []),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            sequence_builder=SequenceBuilder.from_dict(data["sequence_builder"]) if data.get("sequence_builder") else None,
        )
    
    def update_timestamp(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.utcnow()


@dataclass
class ChatConfig:
    """Per-chat configuration overrides.
    
    Allows individual chats to customize game timing settings.
    Uses system defaults for any unspecified values.
    
    Attributes:
        chat_id: Telegram chat ID
        input_hold_frames: Custom button hold duration
        animation_duration: Custom animation phase duration
        auto_save_enabled: Whether auto-save is enabled
        running_mode: Whether running mode is enabled (holds B during directional inputs)
        created_at: When this config was created
        updated_at: When this config was last updated
    """
    
    chat_id: int
    input_hold_frames: Optional[int] = None
    animation_duration: Optional[int] = None
    auto_save_enabled: bool = True
    running_mode: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "chat_id": self.chat_id,
            "input_hold_frames": self.input_hold_frames,
            "animation_duration": self.animation_duration,
            "auto_save_enabled": self.auto_save_enabled,
            "running_mode": self.running_mode,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ChatConfig":
        """Create instance from dictionary."""
        return cls(
            chat_id=data["chat_id"],
            input_hold_frames=data.get("input_hold_frames"),
            animation_duration=data.get("animation_duration"),
            auto_save_enabled=data.get("auto_save_enabled", True),
            running_mode=data.get("running_mode", False),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )
    
    def update_timestamp(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.utcnow()


@dataclass
class SaveSlotInfo:
    """Information about a save slot.
    
    Attributes:
        slot_number: Slot index (0-4 for 5 slots)
        created_at: When this save was created
        updated_at: When this save was last updated
        is_auto_save: Whether this is an auto-save slot
        description: Optional user-provided description
    """
    
    slot_number: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_auto_save: bool = False
    description: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "slot_number": self.slot_number,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_auto_save": self.is_auto_save,
            "description": self.description,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SaveSlotInfo":
        """Create instance from dictionary."""
        return cls(
            slot_number=data["slot_number"],
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            is_auto_save=data.get("is_auto_save", False),
            description=data.get("description"),
        )


@dataclass
class GameSession:
    """Tracks an active game session.
    
    This is kept in memory while a game is active for a chat.
    It references the PyBoy instance and current state.
    
    Attributes:
        chat_id: Telegram chat ID
        state: Current game state for this chat
        last_activity: Timestamp of last user interaction
        total_inputs: Total number of inputs processed
    """
    
    chat_id: int
    state: ChatGameState
    last_activity: datetime = field(default_factory=datetime.utcnow)
    total_inputs: int = 0
    
    def record_activity(self) -> None:
        """Record user activity (input received)."""
        self.last_activity = datetime.utcnow()
        self.total_inputs += 1
    
    def is_idle(self, timeout_seconds: int = 3600) -> bool:
        """Check if session has been idle for longer than timeout.

        Args:
            timeout_seconds: Idle timeout in seconds (default 1 hour)

        Returns:
            True if session is idle, False otherwise
        """
        idle_time = (datetime.utcnow() - self.last_activity).total_seconds()
        return idle_time > timeout_seconds


# Button layout for inline keyboard (3x3 grid with Start/Select at bottom)
BUTTON_LAYOUT = [
    [GameButton.SELECT, GameButton.UP, GameButton.START],
    [GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT],
    [GameButton.WAIT, GameButton.A, GameButton.B],
    [GameButton.RUN, GameButton.SEQUENCE],
]
