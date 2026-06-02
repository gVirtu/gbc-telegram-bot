"""Input buffer data structures for the Telegram GBC Bot.

This module defines the buffered input system for collecting and draining
user inputs in time-based batches.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.models.game_state import GameButton


@dataclass
class BufferedInput:
    """Represents a single buffered button press from a user.

    Each button press creates one BufferedInput slot.

    Attributes:
        user_id: Platform user ID who pressed the button
        user_name: Display name of the user
        button: The button that was pressed
        received_at: When this input was received
    """

    user_id: int
    user_name: str
    button: GameButton
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "button": self.button.value,
            "received_at": self.received_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BufferedInput":
        """Create instance from dictionary."""
        return cls(
            user_id=data["user_id"],
            user_name=data["user_name"],
            button=GameButton(data["button"]),
            received_at=datetime.fromisoformat(data["received_at"]),
        )


@dataclass
class PendingBuffer:
    """Manages an in-memory buffer of pending button inputs for a chat.

    Inputs are collected here before being drained as a batch for animation.
    No persistence — the buffer is discarded on restart.

    Attributes:
        items: Ordered list of buffered inputs (FIFO)
        max_size: Maximum number of inputs allowed
    """

    items: list[BufferedInput] = field(default_factory=list)
    max_size: int = 50

    def is_empty(self) -> bool:
        """Check if buffer has no items."""
        return len(self.items) == 0

    def is_full(self) -> bool:
        """Check if buffer has reached max size."""
        return len(self.items) >= self.max_size

    def total_buttons(self) -> int:
        """Return total number of buffered inputs."""
        return len(self.items)

    def add(
        self,
        user_id: int,
        user_name: str,
        button: GameButton,
    ) -> tuple[bool, tuple]:
        """Add a button press to the buffer.

        Args:
            user_id: Platform user ID
            user_name: Display name
            button: The button pressed

        Returns:
            Tuple of (success, (message_key, message_params))
        """
        if self.is_full():
            return False, ("queue.error_queue_full", {})

        self.items.append(
            BufferedInput(
                user_id=user_id,
                user_name=user_name,
                button=button,
            )
        )
        position = len(self.items)
        return True, ("queue.added_to_queue", {"position": position})

    def pop_batch(self, n: int) -> list[BufferedInput]:
        """Pop up to n items from the front of the buffer (FIFO).

        Args:
            n: Maximum number of items to pop

        Returns:
            List of BufferedInput items (may be fewer than n if buffer is smaller)
        """
        batch = self.items[:n]
        self.items = self.items[n:]
        return batch
