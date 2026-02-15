# Input Queue System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace explicit SEQUENCE mode with implicit input queue system where all inputs are queued and processed sequentially with estimated timing.

**Architecture:** 
- Remove `BUILDING_SEQUENCE` state, keep only `IDLE` and `PROCESSING` states
- Queue mode is implicit when `len(queue) > 0` while in PROCESSING state
- Queue items hold user attribution and mutable back for same-user batching
- Timing calculated per-item: `animation_duration + sequence_delay_seconds * (len(buttons) - 1)`

**Tech Stack:** Python 3.11, python-telegram-bot, pytest-asyncio, PyBoy emulator

---

## Task 1: Add `max_queue_size` Configuration Setting

**Files:**
- Modify: `src/config.py:122-141`

**Step 1: Add the new setting**

Add after `sequence_build_timeout`:

```python
    max_queue_size: int = Field(
        default=10,
        description="Maximum number of items in the input queue",
        ge=1,
        le=50,
    )
```

**Step 2: Verify the setting loads**

Run: `python -c "from src.config import settings; print(settings.max_queue_size)"`

Expected: `10` (or custom value from env var)

**Step 3: Write test for the new setting**

Create test in `tests/test_config.py`:

```python
def test_max_queue_size_default():
    """Test max_queue_size has default value."""
    from src.config import Settings
    
    settings = Settings(
        telegram_bot_token="test_token",
        webhook_url="https://test.example.com",
        webhook_secret="test_secret_1234567890",
    )
    
    assert settings.max_queue_size == 10

def test_max_queue_size_custom():
    """Test max_queue_size accepts custom values."""
    from src.config import Settings
    
    settings = Settings(
        telegram_bot_token="test_token",
        webhook_url="https://test.example.com",
        webhook_secret="test_secret_1234567890",
        max_queue_size=20,
    )
    
    assert settings.max_queue_size == 20

def test_max_queue_size_validation():
    """Test max_queue_size validates range."""
    from src.config import Settings
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError):
        Settings(
            telegram_bot_token="test_token",
            webhook_url="https://test.example.com",
            webhook_secret="test_secret_1234567890",
            max_queue_size=0,  # Below minimum
        )
    
    with pytest.raises(ValidationError):
        Settings(
            telegram_bot_token="test_token",
            webhook_url="https://test.example.com",
            webhook_secret="test_secret_1234567890",
            max_queue_size=100,  # Above maximum
        )
```

**Step 4: Run tests**

Run: `poetry run pytest tests/test_config.py::test_max_queue_size_default -v`
Run: `poetry run pytest tests/test_config.py::test_max_queue_size_custom -v`
Run: `poetry run pytest tests/test_config.py::test_max_queue_size_validation -v`

Expected: All PASS

**Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add max_queue_size configuration setting"
```

---

## Task 2: Create `QueueItem` Dataclass in Models

**Files:**
- Create: `src/models/input_queue.py` (new file)
- Modify: `src/models/__init__.py` (export new classes)

**Step 1: Create the QueueItem dataclass**

Create `src/models/input_queue.py`:

```python
"""Input queue data structures for the Telegram GBC Bot.

This module defines the queue system for batched user inputs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.models.game_state import GameButton


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
    ) -> tuple[bool, str]:
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
                return False, "Queue full! Please wait for current inputs to finish."
        
        # Check if we should extend the back item
        if self.items and self.items[-1].user_id == user_id:
            self.items[-1].add_button(button)
            position = len(self.items)
            return True, f"Added to your sequence (queue position: {position})"
        
        # Create new item
        new_item = QueueItem(
            user_id=user_id,
            user_name=user_name,
            buttons=[button],
        )
        self.items.append(new_item)
        position = len(self.items)
        return True, f"Added to queue (position: {position})"
    
    def get_queue_status(self) -> str:
        """Get a human-readable queue status."""
        if self.is_empty():
            return "Queue empty"
        
        items_desc = []
        for i, item in enumerate(self.items, 1):
            button_count = len(item.buttons)
            buttons_text = "1 button" if button_count == 1 else f"{button_count} buttons"
            items_desc.append(f"{i}. {item.user_name} ({buttons_text})")
        
        return "Queue:\n" + "\n".join(items_desc)
    
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
```

**Step 2: Update models/__init__.py to export new classes**

Add to `src/models/__init__.py`:

```python
from src.models.input_queue import InputQueue, QueueItem

__all__ = [
    # ... existing exports ...
    "InputQueue",
    "QueueItem",
]
```

**Step 3: Write tests for QueueItem**

Create `tests/test_input_queue.py`:

```python
"""Tests for input queue data structures."""

import pytest
from datetime import datetime

from src.models.input_queue import QueueItem, InputQueue
from src.models.game_state import GameButton


class TestQueueItem:
    """Test QueueItem dataclass."""
    
    def test_queue_item_creation(self):
        """Test creating a QueueItem."""
        item = QueueItem(
            user_id=123,
            user_name="TestUser",
            buttons=[GameButton.A, GameButton.B],
        )
        
        assert item.user_id == 123
        assert item.user_name == "TestUser"
        assert len(item.buttons) == 2
        assert item.buttons[0] == GameButton.A
        assert item.buttons[1] == GameButton.B
    
    def test_queue_item_add_button(self):
        """Test adding buttons to QueueItem."""
        item = QueueItem(user_id=123, user_name="TestUser")
        
        assert item.is_empty()
        
        item.add_button(GameButton.UP)
        assert len(item) == 1
        assert not item.is_empty()
        
        item.add_button(GameButton.DOWN)
        assert len(item) == 2
    
    def test_queue_item_serialization(self):
        """Test QueueItem to/from dict."""
        item = QueueItem(
            user_id=123,
            user_name="TestUser",
            buttons=[GameButton.A, GameButton.B],
        )
        
        data = item.to_dict()
        restored = QueueItem.from_dict(data)
        
        assert restored.user_id == item.user_id
        assert restored.user_name == item.user_name
        assert len(restored.buttons) == len(item.buttons)
        assert restored.buttons[0] == GameButton.A
        assert restored.buttons[1] == GameButton.B


class TestInputQueue:
    """Test InputQueue class."""
    
    def test_queue_creation(self):
        """Test creating an empty queue."""
        queue = InputQueue(max_size=5)
        
        assert queue.is_empty()
        assert len(queue) == 0
        assert not queue.is_full()
        assert queue.peek() is None
        assert queue.pop() is None
    
    def test_queue_add_single_user(self):
        """Test adding inputs from single user batches them."""
        queue = InputQueue(max_size=5)
        
        # First input creates new item
        success, msg = queue.add_input(123, "Alice", GameButton.A)
        assert success
        assert len(queue) == 1
        
        # Second input from same user extends existing item
        success, msg = queue.add_input(123, "Alice", GameButton.B)
        assert success
        assert len(queue) == 1  # Still one item
        assert len(queue.items[0].buttons) == 2
    
    def test_queue_add_different_users(self):
        """Test adding inputs from different users creates separate items."""
        queue = InputQueue(max_size=5)
        
        queue.add_input(123, "Alice", GameButton.A)
        queue.add_input(456, "Bob", GameButton.B)
        
        assert len(queue) == 2
        assert queue.items[0].user_id == 123
        assert queue.items[1].user_id == 456
    
    def test_queue_full_rejection(self):
        """Test queue rejects new users when full."""
        queue = InputQueue(max_size=2)
        
        queue.add_input(123, "Alice", GameButton.A)
        queue.add_input(456, "Bob", GameButton.B)
        
        assert queue.is_full()
        
        # New user should be rejected
        success, msg = queue.add_input(789, "Charlie", GameButton.UP)
        assert not success
        assert "full" in msg.lower()
    
    def test_queue_full_extend_allowed(self):
        """Test same user can extend even when queue is full."""
        queue = InputQueue(max_size=2)
        
        queue.add_input(123, "Alice", GameButton.A)
        queue.add_input(456, "Bob", GameButton.B)
        
        assert queue.is_full()
        
        # Same user (Bob) can still extend their item
        success, msg = queue.add_input(456, "Bob", GameButton.DOWN)
        assert success
        assert len(queue) == 2  # Still 2 items
        assert len(queue.items[1].buttons) == 2
    
    def test_queue_pop_order(self):
        """Test queue pops items in FIFO order."""
        queue = InputQueue(max_size=5)
        
        queue.add_input(123, "Alice", GameButton.A)
        queue.add_input(456, "Bob", GameButton.B)
        
        item = queue.pop()
        assert item.user_id == 123
        assert len(queue) == 1
        
        item = queue.pop()
        assert item.user_id == 456
        assert queue.is_empty()
    
    def test_queue_peek_doesnt_remove(self):
        """Test peek doesn't remove item."""
        queue = InputQueue(max_size=5)
        queue.add_input(123, "Alice", GameButton.A)
        
        item1 = queue.peek()
        item2 = queue.peek()
        
        assert item1 is item2
        assert len(queue) == 1
    
    def test_queue_serialization(self):
        """Test InputQueue to/from dict."""
        queue = InputQueue(max_size=5)
        queue.add_input(123, "Alice", GameButton.A)
        queue.add_input(123, "Alice", GameButton.B)  # Same user = extend
        queue.add_input(456, "Bob", GameButton.UP)
        
        data = queue.to_dict()
        restored = InputQueue.from_dict(data)
        
        assert restored.max_size == queue.max_size
        assert len(restored) == len(queue)
        assert len(restored.items[0].buttons) == 2  # Alice's 2 buttons
        assert len(restored.items[1].buttons) == 1  # Bob's 1 button
    
    def test_queue_status_message(self):
        """Test queue status message generation."""
        queue = InputQueue(max_size=5)
        
        assert queue.get_queue_status() == "Queue empty"
        
        queue.add_input(123, "Alice", GameButton.A)
        queue.add_input(123, "Alice", GameButton.B)
        queue.add_input(456, "Bob", GameButton.UP)
        
        status = queue.get_queue_status()
        assert "Alice" in status
        assert "Bob" in status
        assert "2 buttons" in status
        assert "1 button" in status
```

**Step 4: Run tests**

Run: `poetry run pytest tests/test_input_queue.py -v`

Expected: All PASS

**Step 5: Commit**

```bash
git add src/models/input_queue.py src/models/__init__.py tests/test_input_queue.py
git commit -m "feat: add InputQueue and QueueItem data structures"
```

---

## Task 3: Update ChatGameState to Include InputQueue

**Files:**
- Modify: `src/models/game_state.py:114-178`

**Step 1: Add InputQueue import and field**

Add import at top of `src/models/game_state.py`:

```python
from src.models.input_queue import InputQueue
```

Add `input_queue` field to `ChatGameState` dataclass after `sequence_builder`:

```python
    sequence_builder: Optional[SequenceBuilder] = None
    input_queue: Optional[InputQueue] = None
```

**Step 2: Update to_dict/from_dict methods**

Update `to_dict()` to include input_queue:

```python
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            # ... existing fields ...
            "sequence_builder": self.sequence_builder.to_dict() if self.sequence_builder else None,
            "input_queue": self.input_queue.to_dict() if self.input_queue else None,
        }
```

Update `from_dict()` to restore input_queue:

```python
    @classmethod
    def from_dict(cls, data: dict) -> "ChatGameState":
        """Create instance from dictionary."""
        return cls(
            # ... existing fields ...
            sequence_builder=SequenceBuilder.from_dict(data["sequence_builder"]) if data.get("sequence_builder") else None,
            input_queue=InputQueue.from_dict(data["input_queue"]) if data.get("input_queue") else None,
        )
```

**Step 3: Update tests in tests/test_models.py**

Add test for input_queue serialization:

```python
def test_chat_game_state_with_input_queue():
    """Test ChatGameState with input queue."""
    from src.models.game_state import ChatGameState
    from src.models.input_queue import InputQueue, QueueItem
    
    state = ChatGameState(chat_id=123456)
    state.input_queue = InputQueue(max_size=5)
    state.input_queue.add_input(123, "Alice", GameButton.A)
    
    data = state.to_dict()
    restored = ChatGameState.from_dict(data)
    
    assert restored.input_queue is not None
    assert len(restored.input_queue) == 1
    assert restored.input_queue.items[0].user_id == 123
```

**Step 4: Run tests**

Run: `poetry run pytest tests/test_models.py -v`

Expected: All PASS

**Step 5: Commit**

```bash
git add src/models/game_state.py tests/test_models.py
git commit -m "feat: add input_queue field to ChatGameState"
```

---

## Task 4: Remove SEQUENCE Button from BUTTON_LAYOUT

**Files:**
- Modify: `src/models/game_state.py:316-322`

**Step 1: Update BUTTON_LAYOUT**

Change from:

```python
BUTTON_LAYOUT = [
    [GameButton.SELECT, GameButton.UP, GameButton.START],
    [GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT],
    [GameButton.WAIT, GameButton.A, GameButton.B],
    [GameButton.RUN, GameButton.SEQUENCE],
]
```

To:

```python
BUTTON_LAYOUT = [
    [GameButton.SELECT, GameButton.UP, GameButton.START],
    [GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT],
    [GameButton.WAIT, GameButton.A, GameButton.B],
    [GameButton.RUN],
]
```

**Step 2: Update keyboard.py to remove SEQUENCE handling**

Remove or deprecate in `src/keyboard.py`:
- `create_sequence_building_keyboard()` function
- `create_processing_keyboard_for_sequence()` function

Also remove SEQUENCE and ENVIAR from BUTTON_DESCRIPTIONS.

**Step 3: Update tests**

Update `tests/test_keyboard.py` to remove tests for removed functions.

**Step 4: Run tests**

Run: `poetry run pytest tests/test_keyboard.py -v`

Expected: All PASS (after removing obsolete tests)

**Step 5: Commit**

```bash
git add src/models/game_state.py src/keyboard.py tests/test_keyboard.py
git commit -m "refactor: remove SEQUENCE button from layout"
```

---

## Task 5: Rewrite InputHandler with Queue-Based Logic

**Files:**
- Modify: `src/handlers/input_handler.py` (significant rewrite)

**Step 1: Update imports**

Remove imports for sequence-related functions:

```python
# Remove these imports:
# from src.keyboard import (
#     ...
#     create_sequence_building_keyboard,
#     create_processing_keyboard_for_sequence,
#     ...
# )

# Add import:
from src.models.input_queue import InputQueue, QueueItem
```

**Step 2: Update InputHandler class initialization**

Replace `_processing: set[int]` with `_input_queues: dict[int, InputQueue]`:

```python
class InputHandler:
    """Handles game input processing with queue-based system.
    
    This class manages the game flow:
    1. Receiving button presses and queueing them
    2. Processing queue items sequentially with estimated timing
    3. Updating Telegram messages with new frames
    4. Managing game state transitions (IDLE/PROCESSING)
    """
    
    def __init__(self, bot: Bot):
        """Initialize the input handler.
        
        Args:
            bot: The Telegram Bot instance
        """
        self.bot = bot
        self._sessions: dict[int, GameSession] = {}
        self._processing: set[int] = set()  # Chats currently processing (keep for backward compat)
        self._input_queues: dict[int, InputQueue] = {}  # Chat ID -> InputQueue
```

**Step 3: Add queue management methods**

Add these methods to InputHandler:

```python
    def _get_or_create_queue(self, chat_id: int) -> InputQueue:
        """Get or create input queue for a chat.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            InputQueue for the chat
        """
        if chat_id not in self._input_queues:
            # Try to load from session state
            session = self._get_session(chat_id)
            if session and session.state.input_queue:
                self._input_queues[chat_id] = session.state.input_queue
            else:
                # Create new queue with max size from settings
                self._input_queues[chat_id] = InputQueue(max_size=settings.max_queue_size)
        
        return self._input_queues[chat_id]
    
    def _calculate_processing_time(self, buttons: list[GameButton]) -> float:
        """Calculate estimated time to process a button sequence.
        
        Args:
            buttons: List of buttons to process
            
        Returns:
            Estimated time in seconds
        """
        base_time = settings.animation_duration
        
        if len(buttons) > 1:
            # Add delay between buttons
            delay_time = settings.sequence_delay_seconds * (len(buttons) - 1)
            base_time += delay_time
        
        return base_time
    
    def _is_processing(self, chat_id: int) -> bool:
        """Check if a chat is currently processing input.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            True if processing is active
        """
        return chat_id in self._processing
```

**Step 4: Rewrite handle_button_press method**

Replace the entire method with queue-based logic:

```python
    async def handle_button_press(self, callback_query) -> None:
        """Handle a button press with queue-based processing.
        
        All inputs are added to the queue. If not currently processing,
        starts processing immediately. If processing, queues the input.
        """
        chat_id = callback_query.message.chat.id
        message_id = callback_query.message.message_id
        callback_data = callback_query.data

        # Validate callback is a game button
        if not is_valid_button_callback(callback_data):
            try:
                await callback_query.answer("Invalid button")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        button = get_button_from_callback(callback_data)
        session = self._get_session(chat_id)
        if not session:
            try:
                await callback_query.answer("Nenhum jogo ativo! Use /start_game primeiro.")
            except Exception as e:
                logger.error(f"Error processing input for chat {chat_id}: {e}")
            return

        # Extract user info
        user_id = callback_query.from_user.id
        user_name = (
            callback_query.from_user.first_name or
            (f"@{callback_query.from_user.username}" if callback_query.from_user.username else "User")
        )

        # Handle RUN button specially - toggle running mode
        if button == GameButton.RUN:
            await self._handle_run_button_press(
                callback_query, session, chat_id, message_id
            )
            return

        # Get or create queue
        queue = self._get_or_create_queue(chat_id)
        
        # Add input to queue
        success, message = queue.add_input(user_id, user_name, button)
        
        if not success:
            try:
                await callback_query.answer(message)
            except Exception as e:
                logger.error(f"Error answering callback for chat {chat_id}: {e}")
            return
        
        # Save queue to session state
        session.state.input_queue = queue
        state_manager.save_game_state(session.state)
        
        # Check if we should start processing
        if not self._is_processing(chat_id):
            # Start processing loop
            try:
                await callback_query.answer(f"Processing: {button.display_name}")
                asyncio.create_task(self._process_queue_loop(chat_id, message_id))
            except Exception as e:
                logger.error(f"Error starting queue processing for chat {chat_id}: {e}")
                await self._send_error_message(chat_id, "Error starting input processing.")
        else:
            # Already processing, just acknowledge queue addition
            try:
                await callback_query.answer(message)
            except Exception as e:
                logger.error(f"Error answering callback for chat {chat_id}: {e}")
```

**Step 5: Create new _process_queue_loop method**

Add this new method to replace the old processing logic:

```python
    async def _process_queue_loop(self, chat_id: int, message_id: int) -> None:
        """Process queue items until empty.
        
        This loop:
        1. Pops the front item from the queue
        2. Processes it (generates animation)
        3. Calculates estimated time
        4. Waits for estimated time
        5. Repeats if queue has more items
        6. Returns to IDLE state when queue is empty
        
        Args:
            chat_id: Telegram chat ID
            message_id: Message ID to update
        """
        self._processing.add(chat_id)
        session = self._get_session(chat_id)
        
        if not session:
            self._processing.discard(chat_id)
            return
        
        try:
            while True:
                queue = self._get_or_create_queue(chat_id)
                
                if queue.is_empty():
                    # Queue empty, we're done
                    break
                
                # Get next item
                item = queue.pop()
                session.state.input_queue = queue  # Update state
                
                # Record user input
                self._record_user_input(session, item.user_id, item.user_name, item.buttons)
                
                # Process this item
                try:
                    await self._process_queue_item(chat_id, message_id, item)
                except Exception as e:
                    logger.error(f"Error processing queue item for chat {chat_id}: {e}")
                    # Continue to next item despite error
                
                # Update state after processing
                state_manager.save_game_state(session.state)
                
                # Calculate and wait estimated time
                wait_time = self._calculate_processing_time(item.buttons)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
        
        finally:
            self._processing.discard(chat_id)
            if session:
                session.state.input_in_progress = False
                state_manager.save_game_state(session.state)
            
            logger.info(f"Queue processing completed for chat {chat_id}")
```

**Step 6: Create _process_queue_item method**

Add this method (adapted from existing _process_sequence):

```python
    async def _process_queue_item(
        self,
        chat_id: int,
        message_id: int,
        item: QueueItem,
    ) -> None:
        """Process a single queue item.
        
        Args:
            chat_id: Telegram chat ID
            message_id: Message ID to update
            item: QueueItem to process
        """
        buttons = item.buttons
        controller = await game_controller_manager.get_or_create_controller(chat_id)

        # Check running mode
        config = state_manager.get_or_create_chat_config(chat_id)
        running_mode = config.running_mode if config else False

        logger.info(f"Processing queue item with {len(buttons)} buttons for chat {chat_id}")

        # Animation capture settings
        frames = []
        game_fps = 60
        capture_fps = 10
        capture_interval_frames = game_fps // capture_fps

        # Directional buttons that can use running mode
        directional_buttons = (GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT)

        # Capture current frame
        frames.append(controller.get_frame().copy())

        # Execute each button with delays
        for i, button in enumerate(buttons):
            if button == GameButton.WAIT:
                logger.debug(f"WAIT button in sequence for chat {chat_id}")
                controller.tick(frames=settings.input_hold_frames)
            elif running_mode and button in directional_buttons:
                logger.debug(f"Executing {button.value} with B in running mode for chat {chat_id}")
                controller.send_input_with_modifier(button, GameButton.B, frames=settings.input_hold_frames)
            else:
                logger.debug(f"Executing {button.value} in sequence for chat {chat_id}")
                controller.send_input(button, frames=settings.input_hold_frames)

            # Capture frame after button
            frames.append(controller.get_frame().copy())

            # Apply delay between buttons (if not last)
            if i < len(buttons) - 1:
                delay_frames = int(settings.sequence_delay_seconds * game_fps)
                for frame_num in range(delay_frames):
                    controller.tick(1)
                    if frame_num % capture_interval_frames == 0:
                        frames.append(controller.get_frame().copy())

        # Continue animating after last button
        session = self._get_session(chat_id)
        recent = session.state.recent_inputs if session else []
        caption = create_game_message_text(recent_inputs=recent)

        animation_frames = int(settings.animation_duration * game_fps)
        for frame_num in range(animation_frames):
            controller.tick(1)
            if frame_num % capture_interval_frames == 0:
                frames.append(controller.get_frame().copy())

        # Add To Be Continued frames
        from src.utils.frame_utils import generate_tbc_frames
        tbc_frames = generate_tbc_frames(
            frames[-1] if frames else controller.get_frame(),
            overlay_path=settings.tbc_overlay_path,
            duration_frames=settings.tbc_duration_frames,
            max_width_percent=0.7
        )
        frames.extend(tbc_frames)

        input_keyboard = create_input_keyboard(running_mode=running_mode)

        # Generate and send MP4
        if frames:
            logger.info(f"Generating MP4 with {len(frames)} frames for chat {chat_id}")
            try:
                from src.utils.frame_utils import save_frames_as_mp4, should_update_frame
                mp4_buffer = save_frames_as_mp4(frames, fps=capture_fps)
                mp4_buffer.seek(0)

                await self._edit_message_media(
                    chat_id, message_id, mp4_buffer, caption, media_type="animation", reply_markup=input_keyboard
                )

                _, last_hash = should_update_frame(frames[-1], None)
                controller.update_frame_hash(last_hash)
            except Exception as e:
                logger.error(f"Failed to generate MP4 for chat {chat_id}: {e}")
                try:
                    png_buffer = controller.get_frame_as_png()
                    await self._edit_message_media(chat_id, message_id, png_buffer, caption, reply_markup=input_keyboard)
                except Exception as e2:
                    logger.error(f"Fallback failed for chat {chat_id}: {e2}")

        # Auto-save if enabled
        if config and config.auto_save_enabled:
            try:
                slot = state_manager.find_next_auto_save_slot(chat_id)
                state_data = controller.save_state()
                state_manager.save_to_slot(
                    chat_id=chat_id,
                    slot_number=slot,
                    state_data=state_data,
                    description="Auto-save",
                    is_auto_save=True,
                )
                logger.debug(f"Auto-saved to slot {slot} for chat {chat_id}")
            except Exception as e:
                logger.warning(f"Failed to auto-save for chat {chat_id}: {e}")

        logger.info(f"Completed processing queue item for chat {chat_id}")
```

**Step 7: Remove old sequence-related methods**

Remove or deprecate:
- `_handle_sequence_button_press()`
- `_handle_button_in_sequence_mode()`
- `_start_sequence_building()`
- `_check_sequence_timeout()`
- `_submit_sequence()`
- `_create_sequence_building_caption()`

Update `_handle_normal_button_press()` to just redirect to main handler (or remove entirely).

**Step 8: Run tests**

Run: `poetry run pytest tests/test_input_handler.py -v`

Expected: Some tests will fail initially - update them in Task 6

**Step 9: Commit**

```bash
git add src/handlers/input_handler.py
git commit -m "refactor: rewrite InputHandler with queue-based processing"
```

---

## Task 6: Update Input Handler Tests

**Files:**
- Modify: `tests/test_input_handler.py`

**Step 1: Remove sequence-related tests**

Remove tests that test sequence building functionality:
- Tests for `_handle_sequence_button_press`
- Tests for `_handle_button_in_sequence_mode`
- Tests for `_start_sequence_building`
- Tests for `_check_sequence_timeout`
- Tests for `_submit_sequence`

**Step 2: Add queue-based tests**

Add new test class:

```python
class TestInputQueueProcessing:
    """Test queue-based input processing."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create mock bot."""
        bot = MagicMock()
        bot.edit_message_reply_markup = AsyncMock()
        bot.edit_message_media = AsyncMock()
        return bot
    
    @pytest.fixture
    def handler(self, mock_bot):
        """Create handler."""
        return InputHandler(mock_bot)
    
    @pytest.fixture
    def mock_controller(self):
        """Create mock game controller."""
        controller = MagicMock()
        controller.tick.return_value = MagicMock()
        controller.send_input.return_value = MagicMock()
        controller.get_frame_as_png.return_value = BytesIO(b"png")
        controller.get_frame.return_value = MagicMock()
        controller.last_frame_hash = None
        return controller
    
    @pytest.mark.asyncio
    async def test_first_input_starts_processing(self, handler, mock_bot, mock_controller):
        """Test first input starts processing immediately."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager") as mock_state:
                mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                
                # Create session
                handler._sessions[123456] = GameSession(
                    chat_id=123456,
                    state=ChatGameState(chat_id=123456, message_id=789)
                )
                
                # Mock _process_queue_loop to verify it was called
                handler._process_queue_loop = AsyncMock()
                
                # Create callback query
                cq = MagicMock()
                cq.message.chat.id = 123456
                cq.message.message_id = 789
                cq.data = "a"
                cq.from_user.id = 123
                cq.from_user.first_name = "Alice"
                cq.from_user.username = None
                cq.answer = AsyncMock()
                
                await handler.handle_button_press(cq)
                
                # Should acknowledge with "Processing"
                cq.answer.assert_called_once_with("Processing: A")
                
                # Should start processing loop
                handler._process_queue_loop.assert_called_once_with(123456, 789)
    
    @pytest.mark.asyncio
    async def test_second_input_queues(self, handler, mock_bot, mock_controller):
        """Test second input is queued while processing."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager") as mock_state:
                mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                
                # Create session and mark as processing
                handler._sessions[123456] = GameSession(
                    chat_id=123456,
                    state=ChatGameState(chat_id=123456, message_id=789)
                )
                handler._processing.add(123456)
                
                # Create callback query
                cq = MagicMock()
                cq.message.chat.id = 123456
                cq.message.message_id = 789
                cq.data = "b"
                cq.from_user.id = 456
                cq.from_user.first_name = "Bob"
                cq.from_user.username = None
                cq.answer = AsyncMock()
                
                await handler.handle_button_press(cq)
                
                # Should acknowledge with queue position
                call_args = cq.answer.call_args[0][0]
                assert "position" in call_args.lower() or "queue" in call_args.lower()
                
                # Verify queue was updated
                queue = handler._get_or_create_queue(123456)
                assert len(queue) == 1
    
    @pytest.mark.asyncio
    async def test_same_user_batches_inputs(self, handler, mock_bot, mock_controller):
        """Test same user inputs are batched into single queue item."""
        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr:
            with patch("src.handlers.input_handler.state_manager") as mock_state:
                mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
                handler._process_queue_loop = AsyncMock()
                
                # Create session
                handler._sessions[123456] = GameSession(
                    chat_id=123456,
                    state=ChatGameState(chat_id=123456, message_id=789)
                )
                
                user_id = 123
                
                # First input
                cq1 = MagicMock()
                cq1.message.chat.id = 123456
                cq1.message.message_id = 789
                cq1.data = "a"
                cq1.from_user.id = user_id
                cq1.from_user.first_name = "Alice"
                cq1.from_user.username = None
                cq1.answer = AsyncMock()
                
                await handler.handle_button_press(cq1)
                
                # Second input from same user (while not processing yet)
                # Reset the processing flag since we're mocking _process_queue_loop
                handler._processing.discard(123456)
                
                cq2 = MagicMock()
                cq2.message.chat.id = 123456
                cq2.message.message_id = 789
                cq2.data = "b"
                cq2.from_user.id = user_id
                cq2.from_user.first_name = "Alice"
                cq2.from_user.username = None
                cq2.answer = AsyncMock()
                
                await handler.handle_button_press(cq2)
                
                # Should have one queue item with 2 buttons
                queue = handler._get_or_create_queue(123456)
                assert len(queue) == 1
                assert len(queue.items[0].buttons) == 2
    
    @pytest.mark.asyncio
    async def test_queue_processing_time_calculation(self, handler, mock_bot, mock_controller):
        """Test processing time calculation."""
        with patch("src.handlers.input_handler.settings") as mock_settings:
            mock_settings.animation_duration = 5
            mock_settings.sequence_delay_seconds = 1.0
            
            # Single button: just animation_duration
            time_1 = handler._calculate_processing_time([GameButton.A])
            assert time_1 == 5.0
            
            # Two buttons: animation_duration + 1 * sequence_delay
            time_2 = handler._calculate_processing_time([GameButton.A, GameButton.B])
            assert time_2 == 6.0
            
            # Four buttons: animation_duration + 3 * sequence_delay
            time_4 = handler._calculate_processing_time([GameButton.A, GameButton.B, GameButton.UP, GameButton.DOWN])
            assert time_4 == 8.0
    
    @pytest.mark.asyncio
    async def test_queue_full_rejection(self, handler, mock_bot):
        """Test queue rejects new inputs when full."""
        with patch("src.handlers.input_handler.settings") as mock_settings:
            mock_settings.max_queue_size = 2
            
            handler._sessions[123456] = GameSession(
                chat_id=123456,
                state=ChatGameState(chat_id=123456, message_id=789)
            )
            handler._processing.add(123456)  # Mark as processing
            
            # Fill queue with different users
            queue = handler._get_or_create_queue(123456)
            queue.add_input(111, "User1", GameButton.A)
            queue.add_input(222, "User2", GameButton.B)
            
            assert queue.is_full()
            
            # Try to add from third user
            cq = MagicMock()
            cq.message.chat.id = 123456
            cq.message.message_id = 789
            cq.data = "up"
            cq.from_user.id = 333
            cq.from_user.first_name = "User3"
            cq.from_user.username = None
            cq.answer = AsyncMock()
            
            await handler.handle_button_press(cq)
            
            # Should reject
            call_args = cq.answer.call_args[0][0]
            assert "full" in call_args.lower()
```

**Step 3: Update existing tests for compatibility**

Update `test_input_already_in_progress` test - the behavior changed:

```python
    @pytest.mark.asyncio
    async def test_input_while_processing_is_queued(self, handler, mock_callback_query):
        """Test input while processing is queued instead of rejected."""
        # Add to processing set
        handler._processing.add(123456)
        
        # Create a session
        handler._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=789)
        )
        
        await handler.handle_button_press(mock_callback_query)
        
        # Should acknowledge with queue position, not reject
        call_args = mock_callback_query.answer.call_args[0][0]
        assert "position" in call_args.lower() or "queue" in call_args.lower()
```

**Step 4: Run all tests**

Run: `poetry run pytest tests/test_input_handler.py -v`

Expected: All PASS

**Step 5: Commit**

```bash
git add tests/test_input_handler.py
git commit -m "test: update input handler tests for queue-based system"
```

---

## Task 7: Update Webhook Handler Integration

**Files:**
- Review: `src/handlers/webhook.py`

**Step 1: Verify webhook handler still works**

The webhook handler should still work since `handle_button_press` signature hasn't changed. Review to ensure no sequence-specific code.

**Step 2: Update any sequence references**

If there are any references to sequence building in webhook.py, remove them.

**Step 3: Run tests**

Run: `poetry run pytest tests/test_webhook.py -v`

Expected: All PASS

**Step 4: Commit**

```bash
git add src/handlers/webhook.py tests/test_webhook.py
git commit -m "refactor: update webhook handler for queue system"
```

---

## Task 8: Update Commands Handler

**Files:**
- Review: `src/handlers/commands.py`

**Step 1: Review for sequence references**

Check if any commands reference sequence building (SEQUENCE button, sequence_builder state). Update if necessary.

**Step 2: Update /status command**

If there's a /status command, consider adding queue status to it:

```python
def _create_status_message(chat_id: int, session, handler) -> str:
    """Create status message including queue info."""
    # ... existing status code ...
    
    # Add queue status
    queue = handler._get_or_create_queue(chat_id)
    if not queue.is_empty():
        text += f"\n\n📋 Queue: {len(queue)} item(s) waiting"
        if handler._is_processing(chat_id):
            text += " (processing...)"
    
    return text
```

**Step 3: Run tests**

Run: `poetry run pytest tests/test_commands.py -v`

Expected: All PASS

**Step 4: Commit**

```bash
git add src/handlers/commands.py tests/test_commands.py
git commit -m "refactor: update commands for queue system"
```

---

## Task 9: Update Integration Tests

**Files:**
- Review: `tests/test_integration.py`

**Step 1: Update integration tests**

Update any integration tests that test sequence functionality to test queue functionality instead.

**Step 2: Run tests**

Run: `poetry run pytest tests/test_integration.py -v`

Expected: All PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: update integration tests for queue system"
```

---

## Task 10: Final Verification and Cleanup

**Files:**
- All modified files

**Step 1: Run all tests**

Run: `poetry run pytest`

Expected: All PASS

**Step 2: Run type checking**

Run: `poetry run python -m mypy src/ --ignore-missing-imports`

Expected: No critical errors

**Step 3: Remove dead code**

Delete any now-unused imports or helper functions.

**Step 4: Update documentation**

Update CLAUDE.md or README.md with new behavior description.

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: implement input queue system

- Replace explicit SEQUENCE mode with implicit queue
- All inputs are now queued and processed sequentially
- Same-user inputs are batched into single queue items
- Processing uses estimated timing: animation_duration + sequence_delay
- Remove SEQUENCE button from layout
- Add max_queue_size configuration"
```

---

## Summary

This implementation plan:

1. **Adds configuration** for max queue size
2. **Creates new data structures** (QueueItem, InputQueue) in `src/models/input_queue.py`
3. **Updates ChatGameState** to include input_queue field
4. **Removes SEQUENCE button** from BUTTON_LAYOUT
5. **Rewrites InputHandler** with queue-based processing
6. **Updates all tests** to reflect new behavior
7. **Maintains backward compatibility** where possible (existing session loading)

The new system:
- Is simpler (no explicit SEQUENCE mode)
- Is more intuitive (all inputs work the same way)
- Prevents missed inputs (queue collects them during processing)
- Maintains attribution (each queue item knows which user contributed)
- Supports batching (same-user inputs are combined)
- Is configurable (max queue size setting)

**REQUIRED SUB-SKILL:** Use superpowers:executing-plans to implement this plan task-by-task.
