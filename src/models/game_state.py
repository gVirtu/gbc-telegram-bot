"""Data models for the Telegram GBC Bot.

This module defines all data structures used throughout the application,
including game state, chat configuration, and input tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable


KNOWN_FEATURE_FLAGS: frozenset[str] = frozenset({"update_group_avatar", "media_only_mirror", "realtime_recaps", "auto_send_recaps"})


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
        }
        return emoji_map[self]
    
    @property
    def emoji_alt(self) -> str:
        """Get the emoji representation of the button."""
        emoji_map = {
            GameButton.UP: "⬆️",
            GameButton.DOWN: "⬇️",
            GameButton.LEFT: "⬅️",
            GameButton.RIGHT: "➡️",
            GameButton.A: "🅰️",
            GameButton.B: "🅱️",
            GameButton.START: "▶️",
            GameButton.SELECT: "⏹️",
            GameButton.WAIT: "👁️",
        }
        return emoji_map[self]


@dataclass
class ModifierButtonSpec:
    """Spec for a game-specific modifier button.

    A modifier button is displayed in the keyboard and, when active,
    causes a modifier button to be held alongside specified inputs.

    Attributes:
        key: Unique identifier used in modifier_states map (e.g. "run")
        modifier_button: Button held during input (e.g. GameButton.B)
        applies_to: Inputs that get the modifier (e.g. directional buttons)
        active_label_key: i18n key for label when modifier is ON
        inactive_label_key: i18n key for label when modifier is OFF
    """

    key: str
    modifier_button: GameButton
    applies_to: list[GameButton]
    active_label_key: str
    inactive_label_key: str
    condition: Optional[Callable[[Controller, int], bool]] = None


@dataclass
class EventSpec:
    """Spec for a game event that can be detected and rewarded.

    Attributes:
        title: Human-readable display name (e.g. "Wild Battle Started")
        score: Points awarded when this event occurs
    """

    title: str
    score: int


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
        user_input_counts: Track total inputs per user (user_id -> count)
        created_at: When this game state was created
        updated_at: When this game state was last updated
    """

    chat_id: int
    message_id: Optional[int] = None
    input_in_progress: bool = False
    last_input: Optional[GameButton] = None
    last_input_time: Optional[datetime] = None
    last_animation_file_id: Optional[str] = None
    user_input_counts: dict[str, int] = field(default_factory=dict)
    global_frame_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "input_in_progress": self.input_in_progress,
            "last_input": self.last_input.value if self.last_input else None,
            "last_input_time": self.last_input_time.isoformat() if self.last_input_time else None,
            "last_animation_file_id": self.last_animation_file_id,
            "user_input_counts": self.user_input_counts,
            "global_frame_count": self.global_frame_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
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
            last_animation_file_id=data.get("last_animation_file_id"),
            user_input_counts=data.get("user_input_counts", {}),
            global_frame_count=data.get("global_frame_count", 0),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
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
        modifier_states: Map of modifier key to active state (e.g. {"run": True})
        message_base_text: Custom base text for game messages (default: "Sua vez!")
        maintenance_mode: Whether maintenance mode is enabled (only admins can send inputs)
        language: Language code for this chat (e.g., "pt-BR", "en-US"), None for default
        created_at: When this config was created
        updated_at: When this config was last updated
    """

    chat_id: int
    input_hold_frames: Optional[int] = None
    animation_duration: Optional[int] = None
    auto_save_enabled: bool = True
    modifier_states: dict[str, bool] = field(default_factory=dict)
    message_base_text: Optional[str] = None
    maintenance_mode: bool = False
    language: Optional[str] = None
    platform: str = "telegram"
    mirrors_chat_id: Optional[int] = None
    feature_flags: dict[str, bool] = field(default_factory=dict)
    last_avatar_update_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "chat_id": self.chat_id,
            "input_hold_frames": self.input_hold_frames,
            "animation_duration": self.animation_duration,
            "auto_save_enabled": self.auto_save_enabled,
            "modifier_states": self.modifier_states,
            "message_base_text": self.message_base_text,
            "maintenance_mode": self.maintenance_mode,
            "language": self.language,
            "platform": self.platform,
            "mirrors_chat_id": self.mirrors_chat_id,
            "feature_flags": self.feature_flags,
            "last_avatar_update_at": self.last_avatar_update_at.isoformat() if self.last_avatar_update_at else None,
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
            modifier_states=data.get("modifier_states", {}),
            message_base_text=data.get("message_base_text"),
            maintenance_mode=data.get("maintenance_mode", False),
            language=data.get("language"),
            platform=data.get("platform", "telegram"),
            mirrors_chat_id=data.get("mirrors_chat_id"),
            feature_flags=data.get("feature_flags", {}),
            last_avatar_update_at=datetime.fromisoformat(data["last_avatar_update_at"]) if data.get("last_avatar_update_at") else None,
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
class RecapFileRecord:
    """Information about a daily recap timelapse file.

    Attributes:
        chat_id: Telegram chat ID
        date: Date in YYYYMMDD format
        part_number: Part number (1-based) for split recaps
        is_rt: Whether this is a realtime recap
        file_id: Telegram file ID (None if invalidated)
        frame_count: Total frames in timelapse
        duration_sec: Duration of timelapse in seconds
        file_size_bytes: File size in bytes
        created_at: When this recap was first created
        updated_at: When this recap was last updated
        auto_sent_at: When this recap was automatically sent (None if not yet sent)
    """

    chat_id: int
    date: str
    part_number: int = 1
    is_rt: bool = False
    file_id: Optional[str] = None
    frame_count: int = 0
    duration_sec: float = 0.0
    file_size_bytes: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    auto_sent_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "chat_id": self.chat_id,
            "date": self.date,
            "part_number": self.part_number,
            "is_rt": self.is_rt,
            "file_id": self.file_id,
            "frame_count": self.frame_count,
            "duration_sec": self.duration_sec,
            "file_size_bytes": self.file_size_bytes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "auto_sent_at": self.auto_sent_at.isoformat() if self.auto_sent_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RecapFileRecord":
        """Create instance from dictionary."""
        return cls(
            chat_id=data["chat_id"],
            date=data["date"],
            part_number=data.get("part_number", 1),
            is_rt=data.get("is_rt", False),
            file_id=data.get("file_id"),
            frame_count=data.get("frame_count", 0),
            duration_sec=data.get("duration_sec", 0.0),
            file_size_bytes=data.get("file_size_bytes", 0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            auto_sent_at=datetime.fromisoformat(data["auto_sent_at"]) if data.get("auto_sent_at") else None,
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


@dataclass
class TimelapseJobRow:
    """A timelapse encoding job persisted in the database.

    Attributes:
        id: Database row ID
        chat_id: Chat ID (as string, matching DB TEXT type)
        folder_path: Absolute path to the folder containing .npy frame files
        timestamp: ISO8601 timestamp of when the batch was captured
        fps: Output frames per second for the timelapse video
        compositing_context: Deserialized JSON dict with frame/sidebar/reaction data
        frame_count: Total raw captured frames (from compositing_context["frame_count"])
        status: 'pending', 'processing', 'done', or 'failed'
        created_at: ISO8601 creation timestamp
        updated_at: ISO8601 last-update timestamp
    """

    id: int
    chat_id: str
    folder_path: str
    timestamp: str
    fps: int
    compositing_context: dict
    frame_count: int
    status: str
    created_at: str
    updated_at: str


# Button layout for inline keyboard (3x3 grid with Start/Select at bottom)
BUTTON_LAYOUT = [
    [GameButton.SELECT, GameButton.UP, GameButton.START],
    [GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT],
    [GameButton.WAIT, GameButton.A, GameButton.B],
]
