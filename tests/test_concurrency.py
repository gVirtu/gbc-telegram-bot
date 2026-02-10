"""Tests for concurrent access and race conditions.

This module tests thread-safety and async race conditions
in the input handler and game controller manager.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.handlers.input_handler import InputHandler
from src.models.game_state import ChatGameState, GameButton, GameSession


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset rate limiter singleton before each test and initialize with high limits."""
    import src.utils.rate_limiter as rl_module
    rl_module._rate_limiter = None
    # Initialize with high limits for concurrency tests
    rl_module.init_rate_limiter(
        max_per_chat=100,
        per_chat_window=60.0,
        max_global=1000,
        global_window=1.0,
    )
    yield


class TestInputLocking:
    """Test input processing lock prevents concurrent inputs."""

    @pytest.fixture
    def handler(self, mock_bot):
        """Create input handler with mocked bot."""
        return InputHandler(mock_bot)

    @pytest.fixture
    def session(self, chat_id):
        """Create a game session."""
        return GameSession(
            chat_id=chat_id,
            state=ChatGameState(chat_id=chat_id, message_id=789)
        )

    @pytest.mark.asyncio
    async def test_concurrent_inputs_rejected(self, handler, session, chat_id):
        """Test that concurrent inputs to same chat are rejected.
        
        When input is being processed, subsequent inputs should be
        rejected until the first completes.
        """
        # Setup session
        handler._sessions[chat_id] = session
        
        # Mock the processing to be slow
        async def slow_process(*args, **kwargs):
            await asyncio.sleep(0.1)
        
        handler._process_sequence = AsyncMock(side_effect=slow_process)
        
        # Create two callback queries
        cq1 = MagicMock()
        cq1.message.chat.id = chat_id
        cq1.message.message_id = 789
        cq1.data = "a"
        cq1.from_user.id = 1001
        cq1.from_user.first_name = "User1"
        cq1.from_user.username = "user1"
        cq1.answer = AsyncMock()

        cq2 = MagicMock()
        cq2.message.chat.id = chat_id
        cq2.message.message_id = 789
        cq2.data = "b"
        cq2.from_user.id = 1002
        cq2.from_user.first_name = "User2"
        cq2.from_user.username = "user2"
        cq2.answer = AsyncMock()
        
        # Fire both at the same time
        task1 = asyncio.create_task(handler.handle_button_press(cq1))
        task2 = asyncio.create_task(handler.handle_button_press(cq2))
        
        # Wait for both to complete
        await asyncio.gather(task1, task2, return_exceptions=True)
        
        # One should be processing, one should be rejected
        processing_calls = handler._process_sequence.call_count
        
        # Either first processed and second rejected, or vice versa
        assert processing_calls == 1, "Only one input should be processed"

    @pytest.mark.asyncio
    async def test_lock_released_after_completion(self, handler, session, chat_id):
        """Test that lock is released after input processing completes.
        
        After processing finishes, new inputs should be accepted.
        """
        handler._sessions[chat_id] = session
        
        # Fast processing
        handler._process_sequence = AsyncMock()
        
        cq1 = MagicMock()
        cq1.message.chat.id = chat_id
        cq1.message.message_id = 789
        cq1.data = "a"
        cq1.from_user.id = 1001
        cq1.from_user.first_name = "User1"
        cq1.from_user.username = "user1"
        cq1.answer = AsyncMock()

        cq2 = MagicMock()
        cq2.message.chat.id = chat_id
        cq2.message.message_id = 789
        cq2.data = "b"
        cq2.from_user.id = 1002
        cq2.from_user.first_name = "User2"
        cq2.from_user.username = "user2"
        cq2.answer = AsyncMock()

        # Process first input
        await handler.handle_button_press(cq1)
        assert chat_id not in handler._processing, "Lock should be released"
        
        # Process second input
        await handler.handle_button_press(cq2)
        assert handler._process_sequence.call_count == 2, "Both inputs should be processed"

    @pytest.mark.asyncio
    async def test_lock_released_on_exception(self, handler, session, chat_id):
        """Test that lock is released even if processing raises exception.
        
        Lock should always be released to prevent deadlock.
        """
        handler._sessions[chat_id] = session
        
        # Processing that raises exception
        async def failing_process(*args, **kwargs):
            raise ValueError("Test error")
        
        handler._process_sequence = AsyncMock(side_effect=failing_process)
        handler._send_error_message = AsyncMock()
        
        cq = MagicMock()
        cq.message.chat.id = chat_id
        cq.message.message_id = 789
        cq.data = "a"
        cq.from_user.id = 1001
        cq.from_user.first_name = "User1"
        cq.from_user.username = "user1"
        cq.answer = AsyncMock()

        # Process (will raise)
        await handler.handle_button_press(cq)
        
        # Lock should still be released
        assert chat_id not in handler._processing, "Lock must be released even on error"

    @pytest.mark.asyncio
    async def test_different_chats_can_process_concurrently(self, handler):
        """Test that different chats can process inputs simultaneously.
        
        The lock is per-chat, not global.
        """
        chat_id1 = 111
        chat_id2 = 222
        
        handler._sessions[chat_id1] = GameSession(
            chat_id=chat_id1,
            state=ChatGameState(chat_id=chat_id1, message_id=100)
        )
        handler._sessions[chat_id2] = GameSession(
            chat_id=chat_id2,
            state=ChatGameState(chat_id=chat_id2, message_id=200)
        )
        
        processing_started = []
        
        async def record_and_delay(*args, **kwargs):
            chat = args[0]  # First arg is chat_id
            processing_started.append(chat)
            await asyncio.sleep(0.05)
        
        handler._process_sequence = AsyncMock(side_effect=record_and_delay)
        
        cq1 = MagicMock()
        cq1.message.chat.id = chat_id1
        cq1.message.message_id = 100
        cq1.data = "a"
        cq1.from_user.id = 1001
        cq1.from_user.first_name = "User1"
        cq1.from_user.username = "user1"
        cq1.answer = AsyncMock()

        cq2 = MagicMock()
        cq2.message.chat.id = chat_id2
        cq2.message.message_id = 200
        cq2.data = "b"
        cq2.from_user.id = 1002
        cq2.from_user.first_name = "User2"
        cq2.from_user.username = "user2"
        cq2.answer = AsyncMock()
        
        # Start both concurrently
        task1 = asyncio.create_task(handler.handle_button_press(cq1))
        task2 = asyncio.create_task(handler.handle_button_press(cq2))
        
        await asyncio.gather(task1, task2)
        
        # Both should have started processing (not blocked by each other)
        assert chat_id1 in processing_started
        assert chat_id2 in processing_started


class TestGameControllerManagerConcurrency:
    """Test GameControllerManager thread-safety."""

    @pytest.mark.asyncio
    async def test_concurrent_controller_creation(self):
        """Test that concurrent get_or_create_controller is safe."""
        from src.game import GameControllerManager
        
        manager = GameControllerManager()
        chat_id = 123456
        
        with patch("src.game.settings") as mock_settings:
            with patch("src.game.PyBoy") as mock_pyboy_class:
                mock_controller_instance = MagicMock()
                mock_pyboy_class.return_value = mock_controller_instance
                
                # Attempt to create controller from multiple coroutines simultaneously
                async def create_controller():
                    return await manager.get_or_create_controller(chat_id)
                
                # Fire 5 concurrent creations
                tasks = [create_controller() for _ in range(5)]
                results = await asyncio.gather(*tasks)
                
                # All should return the same controller
                first = results[0]
                assert all(r is first for r in results), "All should get same controller"
                
                # PyBoy should only be initialized once
                assert mock_pyboy_class.call_count == 1, "Should only create one PyBoy"


class TestStateManagerConcurrency:
    """Test StateManager file operations under concurrency."""

    @pytest.mark.asyncio
    async def test_concurrent_save_operations(self, tmp_path):
        """Test that concurrent saves don't corrupt state files."""
        from src.utils.state_manager import StateManager
        from src.models.game_state import ChatGameState
        
        manager = StateManager(data_dir=tmp_path)
        chat_id = 123456
        
        async def save_state(iteration):
            state = ChatGameState(
                chat_id=chat_id,
                frame_hash=f"hash_{iteration}"
            )
            manager.save_game_state(state)
        
        # Fire 10 concurrent saves
        tasks = [save_state(i) for i in range(10)]
        await asyncio.gather(*tasks)
        
        # Load state - should be one of the saved values
        loaded = manager.load_game_state(chat_id)
        assert loaded is not None
        assert loaded.frame_hash.startswith("hash_")

    @pytest.mark.asyncio
    async def test_read_while_writing(self, tmp_path):
        """Test reading state while another coroutine is writing."""
        from src.utils.state_manager import StateManager
        from src.models.game_state import ChatGameState
        
        manager = StateManager(data_dir=tmp_path)
        chat_id = 123456
        
        # Initial save
        manager.save_game_state(ChatGameState(chat_id=chat_id, frame_hash="initial"))
        
        async def writer():
            for i in range(5):
                manager.save_game_state(
                    ChatGameState(chat_id=chat_id, frame_hash=f"write_{i}")
                )
                await asyncio.sleep(0.01)
        
        async def reader():
            results = []
            for _ in range(10):
                state = manager.load_game_state(chat_id)
                if state:
                    results.append(state.frame_hash)
                await asyncio.sleep(0.005)
            return results
        
        # Run writer and reader concurrently
        write_task = asyncio.create_task(writer())
        read_results = await reader()
        await write_task
        
        # Reader should have gotten valid states (not crashed)
        assert len(read_results) > 0
        assert all(r is not None for r in read_results)
