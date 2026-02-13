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
        assert "cheia" in msg.lower()
    
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
        
        assert queue.get_queue_status() == "Fila vazia"
        
        queue.add_input(123, "Alice", GameButton.A)
        queue.add_input(123, "Alice", GameButton.B)
        queue.add_input(456, "Bob", GameButton.UP)
        
        status = queue.get_queue_status()
        assert "Alice" in status
        assert "Bob" in status
        assert "2 botões" in status
        assert "1 botão" in status
