"""Tests for buffered input queue data structures."""

from datetime import datetime

from src.models.input_queue import BufferedInput, PendingBuffer
from src.models.game_state import GameButton


class TestBufferedInput:
    """Test BufferedInput dataclass."""

    def test_buffered_input_creation(self):
        bi = BufferedInput(user_id=123, user_name="Alice", button=GameButton.A)
        assert bi.user_id == 123
        assert bi.user_name == "Alice"
        assert bi.button == GameButton.A
        assert isinstance(bi.received_at, datetime)

    def test_buffered_input_serialization(self):
        bi = BufferedInput(user_id=42, user_name="Bob", button=GameButton.UP)
        d = bi.to_dict()
        restored = BufferedInput.from_dict(d)

        assert restored.user_id == bi.user_id
        assert restored.user_name == bi.user_name
        assert restored.button == bi.button
        assert restored.received_at.isoformat() == bi.received_at.isoformat()


class TestPendingBuffer:
    """Test PendingBuffer class."""

    def test_empty_buffer(self):
        buf = PendingBuffer(max_size=10)
        assert buf.is_empty()
        assert not buf.is_full()
        assert buf.total_buttons() == 0

    def test_add_success(self):
        buf = PendingBuffer(max_size=5)
        success, (key, params) = buf.add(1, "Alice", GameButton.A)
        assert success
        assert buf.total_buttons() == 1
        assert not buf.is_empty()

    def test_add_full_rejection(self):
        buf = PendingBuffer(max_size=2)
        buf.add(1, "Alice", GameButton.A)
        buf.add(2, "Bob", GameButton.B)
        assert buf.is_full()

        success, (key, _) = buf.add(3, "Charlie", GameButton.UP)
        assert not success
        assert key == "queue.error_queue_full"
        assert buf.total_buttons() == 2

    def test_add_multiple_inputs_same_user(self):
        """Each button press creates its own BufferedInput slot (no mutable-back grouping)."""
        buf = PendingBuffer(max_size=10)
        buf.add(1, "Alice", GameButton.A)
        buf.add(1, "Alice", GameButton.B)
        assert buf.total_buttons() == 2
        assert buf.items[0].button == GameButton.A
        assert buf.items[1].button == GameButton.B

    def test_add_different_users_fifo(self):
        buf = PendingBuffer(max_size=10)
        buf.add(1, "Alice", GameButton.A)
        buf.add(2, "Bob", GameButton.B)
        buf.add(1, "Alice", GameButton.UP)
        assert buf.total_buttons() == 3
        assert buf.items[0].user_id == 1
        assert buf.items[1].user_id == 2
        assert buf.items[2].user_id == 1

    def test_pop_batch_fifo(self):
        buf = PendingBuffer(max_size=10)
        buf.add(1, "Alice", GameButton.A)
        buf.add(2, "Bob", GameButton.B)
        buf.add(1, "Alice", GameButton.UP)

        batch = buf.pop_batch(2)
        assert len(batch) == 2
        assert batch[0].button == GameButton.A
        assert batch[1].button == GameButton.B
        assert buf.total_buttons() == 1

    def test_pop_batch_partial(self):
        """pop_batch returns fewer items than requested if buffer is smaller."""
        buf = PendingBuffer(max_size=10)
        buf.add(1, "Alice", GameButton.A)

        batch = buf.pop_batch(5)
        assert len(batch) == 1
        assert buf.is_empty()

    def test_pop_batch_empty(self):
        buf = PendingBuffer(max_size=10)
        batch = buf.pop_batch(3)
        assert batch == []

    def test_is_full(self):
        buf = PendingBuffer(max_size=3)
        buf.add(1, "A", GameButton.A)
        buf.add(2, "B", GameButton.B)
        assert not buf.is_full()
        buf.add(3, "C", GameButton.UP)
        assert buf.is_full()

    def test_total_buttons_after_pop(self):
        buf = PendingBuffer(max_size=10)
        for i in range(5):
            buf.add(i, f"User{i}", GameButton.A)
        buf.pop_batch(3)
        assert buf.total_buttons() == 2
