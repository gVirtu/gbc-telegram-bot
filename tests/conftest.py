"""Shared pytest fixtures for all tests."""

import asyncio
import os
import pytest
from unittest.mock import MagicMock, AsyncMock
import numpy as np
from io import BytesIO

# Set test environment before any imports
os.environ["PYTEST_CURRENT_TEST"] = "1"
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
os.environ["WEBHOOK_URL"] = "https://test.example.com"
os.environ["WEBHOOK_SECRET"] = "test_secret_1234567890"


@pytest.fixture(autouse=True)
async def cancel_pending_tasks():
    """Cancel any asyncio Tasks left running after each async test.

    Tests that call handle_button_press() without mocking asyncio.create_task
    leave background Tasks (_run_buffer_timer, _process_queue_loop) pending
    when the test ends.  On macOS the event loop uses a kqueue file descriptor;
    if the GC finalises those orphaned Tasks after the loop has been closed the
    OS may reuse the same FD number for the next test's kqueue, causing the
    next test to fail with OSError: [Errno 9] Bad file descriptor.
    """
    yield
    # One iteration lets newly-created tasks reach their first await point so
    # their coroutines are considered "started" — preventing the
    # "coroutine was never awaited" RuntimeWarning when they are cancelled.
    await asyncio.sleep(0)
    tasks = [t for t in asyncio.all_tasks() if not t.done() and t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.fixture
def mock_bot():
    """Create a mock Telegram bot."""
    bot = MagicMock()
    bot.send_photo = AsyncMock(return_value=MagicMock(message_id=100))
    bot.send_message = AsyncMock()
    bot.edit_message_reply_markup = AsyncMock()
    bot.edit_message_media = AsyncMock()
    bot.edit_message_caption = AsyncMock()
    bot.set_webhook = AsyncMock(return_value=True)
    bot.delete_webhook = AsyncMock(return_value=True)
    return bot


@pytest.fixture
def mock_rom_path(tmp_path):
    """Create a mock ROM file path."""
    rom_path = tmp_path / "test.gbc"
    rom_path.write_bytes(b"mock rom data for testing")
    return rom_path


@pytest.fixture
def mock_settings(tmp_path, mock_rom_path):
    """Create mock settings with temp paths."""
    settings = MagicMock()
    settings.telegram_bot_token.get_secret_value.return_value = "test_token"
    settings.webhook_url = "https://test.example.com"
    settings.webhook_secret = "test_secret_1234567890"
    settings.rom_path = mock_rom_path
    settings.data_dir = tmp_path / "data"
    settings.save_slots = 5
    settings.port = 8000
    settings.log_level = "INFO"
    settings.input_hold_frames = 30
    settings.animation_duration = 5
    settings.get_webhook_path.return_value = "/webhook/test_hash_1234"
    settings.get_chat_save_dir.return_value = tmp_path / "saves" / "123456"
    settings.get_config_file.return_value = tmp_path / "config" / "123456.json"
    settings.allowed_chat_ids = []
    return settings


@pytest.fixture
def mock_pyboy():
    """Create a mock PyBoy instance."""
    mock = MagicMock()
    mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
    mock_screen = MagicMock()
    type(mock_screen).ndarray = MagicMock(return_value=mock_frame)
    mock.screen = mock_screen
    mock.tick = MagicMock()
    mock.send_input = MagicMock()
    return mock


@pytest.fixture
def mock_controller(mock_pyboy, mock_rom_path):
    """Create a mock game controller."""
    from src.game import GameController
    
    controller = GameController(123456, rom_path=mock_rom_path)
    controller.pyboy = mock_pyboy
    controller._initialized = True
    return controller


@pytest.fixture
def mock_game_frame():
    """Create a standard GameBoy frame."""
    return np.zeros((144, 160, 3), dtype=np.uint8)


@pytest.fixture
def mock_png_buffer():
    """Create a mock PNG buffer."""
    return BytesIO(b"fake_png_data")


@pytest.fixture
def base_settings_dict(tmp_path, mock_rom_path):
    """Base settings dict for Settings tests."""
    return {
        "telegram_bot_token": "test_token",
        "webhook_url": "https://example.com",
        "webhook_secret": "test_secret_1234567890",
        "rom_path": mock_rom_path,
        "data_dir": tmp_path / "data",
    }


@pytest.fixture
def valid_settings_kwargs(tmp_path, mock_rom_path):
    """Valid kwargs for Settings instantiation."""
    return {
        "telegram_bot_token": "test_token",
        "webhook_url": "https://example.com",
        "webhook_secret": "test_secret_1234567890",
        "rom_path": mock_rom_path,
        "data_dir": tmp_path / "data",
    }


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear settings cache before each test."""
    from src.config import get_settings
    get_settings.cache_clear()
    yield


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset rate limiter singleton before each test."""
    import src.utils.rate_limiter as rl_module
    rl_module._rate_limiter = None
    yield


@pytest.fixture
def mock_callback_query(mock_bot):
    """Create a mock callback query."""
    cq = MagicMock()
    cq.message.chat.id = 123456
    cq.message.message_id = 789
    cq.data = "a"
    cq.answer = AsyncMock()
    cq.from_user.id = 456
    cq.from_user.first_name = "TestUser"
    cq.from_user.username = "testuser"
    return cq


@pytest.fixture
def mock_update():
    """Create a mock Telegram Update object."""
    update = MagicMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = 123456
    update.effective_chat.type = "private"
    update.effective_user = MagicMock()
    update.effective_user.id = 789
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.text = ""
    return update


@pytest.fixture
def mock_context(mock_bot):
    """Create a mock Telegram Context object."""
    context = MagicMock()
    context.bot = mock_bot
    context.args = []
    return context


@pytest.fixture
def chat_id():
    """Standard test chat ID."""
    return 123456


@pytest.fixture
def message_id():
    """Standard test message ID."""
    return 789


@pytest.fixture
def user_id():
    """Standard test user ID."""
    return 456


@pytest.fixture
def mock_adapter():
    """Create a mock BotAdapter for tests."""
    adapter = MagicMock()
    adapter.platform = "telegram"
    adapter.send_game_message = AsyncMock(return_value=100)
    adapter.edit_game_message = AsyncMock(return_value=None)
    adapter.edit_game_keyboard = AsyncMock()
    adapter.send_screenshot = AsyncMock()
    adapter.send_text = AsyncMock()
    adapter.send_video = AsyncMock(return_value=None)
    adapter.send_animation = AsyncMock()
    adapter.delete_message = AsyncMock()
    adapter.build_game_keyboard = MagicMock(return_value=MagicMock())
    adapter.build_save_slot_keyboard = MagicMock(return_value=MagicMock())
    adapter.is_admin = AsyncMock(return_value=True)
    adapter.answer_interaction = AsyncMock()
    return adapter


@pytest.fixture
def mock_ctx(mock_adapter):
    """Create a mock CommandContext for tests."""
    from src.adapters.base import CommandContext
    return CommandContext(
        chat_id=123456,
        user_id=456,
        user_name="TestUser",
        args=[],
        adapter=mock_adapter,
        raw=None,
    )


@pytest.fixture(autouse=True)
def reset_input_handler():
    """Reset InputHandler singleton before each test."""
    import src.handlers.input_handler as ih_module
    old_handler = ih_module._input_handler
    ih_module._input_handler = None
    yield
    ih_module._input_handler = old_handler
