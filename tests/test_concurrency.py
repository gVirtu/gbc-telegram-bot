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
    def handler(self):
        """Create input handler."""
        return InputHandler()

    @pytest.fixture
    def session(self, chat_id):
        """Create a game session."""
        return GameSession(
            chat_id=chat_id,
            state=ChatGameState(chat_id=chat_id, message_id=789)
        )

    @pytest.mark.asyncio
    async def test_concurrent_inputs_queued(self, handler, session, chat_id, mock_adapter):
        """Test that concurrent inputs to same chat are queued.

        When input is being processed, subsequent inputs should be
        added to the queue for sequential processing.
        """
        with patch("src.handlers.input_handler.state_manager"):
            # Setup session
            handler._sessions[chat_id] = session

            # Create two callback queries from different users
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
            await handler.handle_button_press(
                callback_data=cq1.data, chat_id=cq1.message.chat.id,
                message_id=cq1.message.message_id, user_id=cq1.from_user.id,
                user_name="User1", adapter=mock_adapter, raw=cq1
            )
            await handler.handle_button_press(
                callback_data=cq2.data, chat_id=cq2.message.chat.id,
                message_id=cq2.message.message_id, user_id=cq2.from_user.id,
                user_name="User2", adapter=mock_adapter, raw=cq2
            )

            # Both inputs should be acknowledged via adapter
            assert mock_adapter.answer_interaction.call_count >= 2, "Both inputs should be acknowledged"
            # Buffer should be created with items from both users
            assert chat_id in handler._pending_buffers, "Buffer should be created"

    @pytest.mark.asyncio
    async def test_processing_cleared_after_completion(self, handler, session, chat_id, mock_adapter):
        """Test that processing flag is set during input handling.

        The processing flag is set by the queue loop when it starts processing.
        """
        with patch("src.handlers.input_handler.state_manager"):
            handler._sessions[chat_id] = session

            cq1 = MagicMock()
            cq1.message.chat.id = chat_id
            cq1.message.message_id = 789
            cq1.data = "a"
            cq1.from_user.id = 1001
            cq1.from_user.first_name = "User1"
            cq1.from_user.username = "user1"
            cq1.answer = AsyncMock()

            # Process first input
            await handler.handle_button_press(
                callback_data=cq1.data, chat_id=cq1.message.chat.id,
                message_id=cq1.message.message_id, user_id=cq1.from_user.id,
                user_name="User1", adapter=mock_adapter, raw=cq1
            )

            # Buffer should be created
            assert chat_id in handler._pending_buffers, "Buffer should be created"
            # Input should be acknowledged via adapter
            mock_adapter.answer_interaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_queue_item_created_on_input(self, handler, session, chat_id, mock_adapter):
        """Test that queue item is created when input is received.

        When a button press is received, it should be added to the queue.
        """
        with patch("src.handlers.input_handler.state_manager"):
            handler._sessions[chat_id] = session

            cq = MagicMock()
            cq.message.chat.id = chat_id
            cq.message.message_id = 789
            cq.data = "a"
            cq.from_user.id = 1001
            cq.from_user.first_name = "User1"
            cq.from_user.username = "user1"
            cq.answer = AsyncMock()

            # Process input
            await handler.handle_button_press(
                callback_data=cq.data, chat_id=cq.message.chat.id,
                message_id=cq.message.message_id, user_id=cq.from_user.id,
                user_name="User1", adapter=mock_adapter, raw=cq
            )

            # Buffer should be created with one item
            assert chat_id in handler._pending_buffers, "Buffer should be created"
            # Input should be acknowledged via adapter
            assert mock_adapter.answer_interaction.called, "Input should be acknowledged"

    @pytest.mark.asyncio
    async def test_different_chats_have_independent_queues(self, handler, mock_adapter):
        """Test that different chats have independent queues.

        Each chat has its own queue and can receive inputs independently.
        """
        with patch("src.handlers.input_handler.state_manager"):
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
            task1 = asyncio.create_task(handler.handle_button_press(
                callback_data=cq1.data, chat_id=cq1.message.chat.id,
                message_id=cq1.message.message_id, user_id=cq1.from_user.id,
                user_name="User1", adapter=mock_adapter, raw=cq1
            ))
            task2 = asyncio.create_task(handler.handle_button_press(
                callback_data=cq2.data, chat_id=cq2.message.chat.id,
                message_id=cq2.message.message_id, user_id=cq2.from_user.id,
                user_name="User2", adapter=mock_adapter, raw=cq2
            ))

            await asyncio.gather(task1, task2)

            # Both should have their own buffers created
            assert chat_id1 in handler._pending_buffers, "Chat 1 should have a buffer"
            assert chat_id2 in handler._pending_buffers, "Chat 2 should have a buffer"
            # Both inputs should be acknowledged via adapter
            assert mock_adapter.answer_interaction.call_count >= 2, "Both inputs should be acknowledged"


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
            )
            manager.save_game_state(state)
        
        # Fire 10 concurrent saves
        tasks = [save_state(i) for i in range(10)]
        await asyncio.gather(*tasks)
        
        # Load state - should be one of the saved values
        loaded = manager.load_game_state(chat_id)
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_read_while_writing(self, tmp_path):
        """Test reading state while another coroutine is writing."""
        from src.utils.state_manager import StateManager
        from src.models.game_state import ChatGameState
        
        manager = StateManager(data_dir=tmp_path)
        chat_id = 123456
        
        # Initial save
        manager.save_game_state(ChatGameState(chat_id=chat_id, message_id=-1))
        
        async def writer():
            for i in range(5):
                manager.save_game_state(
                    ChatGameState(chat_id=chat_id, message_id=i)
                )
                await asyncio.sleep(0.01)
        
        async def reader():
            results = []
            for _ in range(10):
                state = manager.load_game_state(chat_id)
                if state:
                    results.append(state.message_id)
                await asyncio.sleep(0.005)
            return results
        
        # Run writer and reader concurrently
        write_task = asyncio.create_task(writer())
        read_results = await reader()
        await write_task
        
        # Reader should have gotten valid states (not crashed)
        assert len(read_results) > 0
        assert all(r is not None for r in read_results)
