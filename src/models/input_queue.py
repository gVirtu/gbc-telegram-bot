"""Input queue data structures for the Telegram GBC Bot.

This module defines the queue system for batched user inputs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.models.game_state import GameButton
from src.config import settings
from src.i18n import translation_manager


@dataclass
class QueueItem:
    """Represents a single item in the input queue.
    
    Each item contains a sequence of buttons from one user.
    The queue has a "mutable back" - if the same user sends
    multiple inputs, they get batched into a single item until
    another user contributes.
    
    Attributes:
        user_id: Telegram user ID who contributed this item
        user_name: Display name of the user
        buttons: List of buttons in this sequence
        created_at: When this item was created
        updated_at: When this item was last updated (buttons added)
    """
    
    user_id: int
    user_name: str
    buttons: list[GameButton] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def add_button(self, button: GameButton) -> bool:
        """Add a button to this item.
        
        Args:
            button: The button to add
            
        Returns:
            True if added successfully
        """
        self.buttons.append(button)
        self.updated_at = datetime.utcnow()
        return True
    
    def is_empty(self) -> bool:
        """Check if this item has no buttons."""
        return len(self.buttons) == 0
    
    def __len__(self) -> int:
        """Return number of buttons in this item."""
        return len(self.buttons)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "buttons": [b.value for b in self.buttons],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "QueueItem":
        """Create instance from dictionary."""
        return cls(
            user_id=data["user_id"],
            user_name=data["user_name"],
            buttons=[GameButton(b) for b in data.get("buttons", [])],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


@dataclass
class InputQueue:
    """Manages the input queue for a chat.
    
    The queue holds QueueItems waiting to be processed.
    It supports a "mutable back" where the same user can
    extend their item until another user contributes.
    
    Attributes:
        items: List of queue items (front to back)
        max_size: Maximum number of items allowed
    """
    
    items: list[QueueItem] = field(default_factory=list)
    max_size: int = 10
    max_sequence_length: int = settings.max_sequence_length
    
    def is_empty(self) -> bool:
        """Check if queue has no items."""
        return len(self.items) == 0
    
    def __len__(self) -> int:
        """Return number of items in queue."""
        return len(self.items)
    
    def is_full(self) -> bool:
        """Check if queue has reached max size."""
        return len(self.items) >= self.max_size
    
    def peek(self) -> Optional[QueueItem]:
        """Get the front item without removing it."""
        if self.is_empty():
            return None
        return self.items[0]
    
    def pop(self) -> Optional[QueueItem]:
        """Remove and return the front item."""
        if self.is_empty():
            return None
        return self.items.pop(0)
    
    def add_input(
        self,
        user_id: int,
        user_name: str,
        button: GameButton,
    ) -> tuple[bool, tuple]:
        """Add an input to the queue.
        
        If the back item is from the same user, extend it.
        Otherwise, create a new item at the back.
        
        Args:
            user_id: Telegram user ID
            user_name: Display name
            button: The button pressed
            
        Returns:
            Tuple of (success, message)
            - success: True if added successfully
            - message: Status message for user feedback
        """
        # Check if queue is full
        if self.is_full():
            # Check if we can extend the back item
            if not self.items or self.items[-1].user_id != user_id:
                return False, ("queue.error_queue_full", {})
        
        # Check if we should extend the back item
        if self.items and self.items[-1].user_id == user_id:
            if len(self.items[-1].buttons) >= self.max_sequence_length:
                return False, ("queue.error_max_sequence_length", {})
            self.items[-1].add_button(button)
            position = len(self.items)
            return True, ("queue.added_to_sequence", {"position": position})
        
        # Create new item
        new_item = QueueItem(
            user_id=user_id,
            user_name=user_name,
            buttons=[button],
        )
        self.items.append(new_item)
        position = len(self.items)
        return True, ("queue.added_to_queue", {"position": position})
    
    def get_queue_status(self, chat_id: int) -> str:
        """Get a human-readable queue status."""
        if self.is_empty():
            return translation_manager.get("queue.empty", chat_id)
        
        items_desc = []
        for i, item in enumerate(self.items, 1):
            button_count = len(item.buttons)
            buttons_text = translation_manager.get("queue.one_button", chat_id) if button_count == 1 else translation_manager.get("queue.n_buttons", chat_id, count=button_count)
            items_desc.append(translation_manager.get("queue.item_description", chat_id, i=i, user=item.user_name, buttons=buttons_text))
        
        return translation_manager.get("queue.status_header", chat_id) + "\n" + "\n".join(items_desc)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "items": [item.to_dict() for item in self.items],
            "max_size": self.max_size,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "InputQueue":
        """Create instance from dictionary."""
        return cls(
            items=[QueueItem.from_dict(item_data) for item_data in data.get("items", [])],
            max_size=data.get("max_size", 10),
        )
