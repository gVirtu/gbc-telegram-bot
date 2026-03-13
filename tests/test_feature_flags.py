"""Tests for the feature flags system.

Covers:
- ChatConfig to_dict/from_dict round-trip for feature_flags and last_avatar_update_at
- DB save/load of feature_flags and last_avatar_update_at
- /feature command logic
- _should_update_avatar cooldown logic
- _update_group_avatar called on mock adapter when flag is set and cooldown passed
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.adapters.base import CommandContext
from src.handlers.commands import feature_command, COMMAND_HANDLERS
from src.handlers.input_handler import _should_update_avatar, AVATAR_UPDATE_INTERVAL
from src.models.game_state import ChatConfig, KNOWN_FEATURE_FLAGS
from src.db.manager import DatabaseManager


# ======================================================
# Model round-trip tests
# ======================================================

class TestChatConfigFeatureFlags:
    def test_to_dict_includes_feature_flags(self):
        config = ChatConfig(chat_id=1, feature_flags={"update_group_avatar": True})
        d = config.to_dict()
        assert d["feature_flags"] == {"update_group_avatar": True}

    def test_to_dict_includes_last_avatar_update_at_none(self):
        config = ChatConfig(chat_id=1)
        d = config.to_dict()
        assert d["last_avatar_update_at"] is None

    def test_to_dict_includes_last_avatar_update_at_value(self):
        ts = datetime(2026, 3, 8, 12, 0, 0)
        config = ChatConfig(chat_id=1, last_avatar_update_at=ts)
        d = config.to_dict()
        assert d["last_avatar_update_at"] == ts.isoformat()

    def test_from_dict_round_trip_feature_flags(self):
        ts = datetime(2026, 3, 8, 12, 0, 0)
        config = ChatConfig(
            chat_id=1,
            feature_flags={"update_group_avatar": True},
            last_avatar_update_at=ts,
        )
        restored = ChatConfig.from_dict(config.to_dict())
        assert restored.feature_flags == {"update_group_avatar": True}
        assert restored.last_avatar_update_at == ts

    def test_from_dict_defaults_when_missing(self):
        data = ChatConfig(chat_id=1).to_dict()
        del data["feature_flags"]
        del data["last_avatar_update_at"]
        config = ChatConfig.from_dict(data)
        assert config.feature_flags == {}
        assert config.last_avatar_update_at is None

    def test_known_feature_flags_contains_update_group_avatar(self):
        assert "update_group_avatar" in KNOWN_FEATURE_FLAGS

    def test_known_feature_flags_contains_media_only_mirror(self):
        assert "media_only_mirror" in KNOWN_FEATURE_FLAGS

    def test_known_feature_flags_contains_realtime_recaps(self):
        assert "realtime_recaps" in KNOWN_FEATURE_FLAGS


# ======================================================
# DB persistence tests
# ======================================================

@pytest.fixture
def db_manager(tmp_path):
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    yield manager
    manager.close()


class TestDbFeatureFlags:
    def test_save_and_load_feature_flags(self, db_manager):
        config = ChatConfig(chat_id=101, feature_flags={"update_group_avatar": True})
        db_manager.save_chat_config(config)
        loaded = db_manager.load_chat_config(101)
        assert loaded is not None
        assert loaded.feature_flags == {"update_group_avatar": True}

    def test_save_and_load_empty_feature_flags(self, db_manager):
        config = ChatConfig(chat_id=102, feature_flags={})
        db_manager.save_chat_config(config)
        loaded = db_manager.load_chat_config(102)
        assert loaded is not None
        assert loaded.feature_flags == {}

    def test_save_and_load_last_avatar_update_at(self, db_manager):
        ts = datetime(2026, 3, 8, 10, 0, 0)
        config = ChatConfig(chat_id=103, last_avatar_update_at=ts)
        db_manager.save_chat_config(config)
        loaded = db_manager.load_chat_config(103)
        assert loaded is not None
        assert loaded.last_avatar_update_at == ts

    def test_save_and_load_last_avatar_update_at_none(self, db_manager):
        config = ChatConfig(chat_id=104)
        db_manager.save_chat_config(config)
        loaded = db_manager.load_chat_config(104)
        assert loaded is not None
        assert loaded.last_avatar_update_at is None

    def test_default_feature_flags_on_new_config(self, db_manager):
        config = db_manager.get_or_create_chat_config(200)
        assert config.feature_flags == {}


# ======================================================
# /feature command tests
# ======================================================

def make_ctx(mock_adapter, args=None, chat_id=123):
    return CommandContext(
        chat_id=chat_id,
        user_id=456,
        user_name="TestUser",
        args=args if args is not None else [],
        adapter=mock_adapter,
        raw=None,
    )


@pytest.mark.asyncio
async def test_feature_command_registered():
    assert "feature" in COMMAND_HANDLERS
    assert COMMAND_HANDLERS["feature"] == feature_command


@pytest.mark.asyncio
async def test_feature_command_enables_flag(mock_adapter):
    ctx = make_ctx(mock_adapter, args=["update_group_avatar", "true"])

    mock_config = MagicMock()
    mock_config.feature_flags = {}

    with patch("src.handlers.commands.check_admin_permission", return_value=(True, None)):
        with patch("src.handlers.commands.state_manager") as mock_state:
            mock_state.get_or_create_chat_config.return_value = mock_config
            await feature_command(ctx)

    assert mock_config.feature_flags["update_group_avatar"] is True
    mock_state.save_chat_config.assert_called_once_with(mock_config)
    mock_adapter.send_text.assert_called_once()
    text = mock_adapter.send_text.call_args[0][1]
    assert "enabled" in text


@pytest.mark.asyncio
async def test_feature_command_disables_flag(mock_adapter):
    ctx = make_ctx(mock_adapter, args=["update_group_avatar", "false"])

    mock_config = MagicMock()
    mock_config.feature_flags = {"update_group_avatar": True}

    with patch("src.handlers.commands.check_admin_permission", return_value=(True, None)):
        with patch("src.handlers.commands.state_manager") as mock_state:
            mock_state.get_or_create_chat_config.return_value = mock_config
            await feature_command(ctx)

    assert mock_config.feature_flags["update_group_avatar"] is False


@pytest.mark.asyncio
async def test_feature_command_rejects_non_admin(mock_adapter):
    ctx = make_ctx(mock_adapter, args=["update_group_avatar", "true"])

    with patch("src.handlers.commands.check_admin_permission", return_value=(False, "Admin only")):
        await feature_command(ctx)

    mock_adapter.send_text.assert_called_once_with(123, "Admin only")


@pytest.mark.asyncio
async def test_feature_command_rejects_unknown_flag(mock_adapter):
    ctx = make_ctx(mock_adapter, args=["nonexistent_flag", "true"])

    with patch("src.handlers.commands.check_admin_permission", return_value=(True, None)):
        await feature_command(ctx)

    text = mock_adapter.send_text.call_args[0][1]
    assert "Unknown feature flag" in text


@pytest.mark.asyncio
async def test_feature_command_rejects_invalid_value(mock_adapter):
    ctx = make_ctx(mock_adapter, args=["update_group_avatar", "yes"])

    with patch("src.handlers.commands.check_admin_permission", return_value=(True, None)):
        await feature_command(ctx)

    text = mock_adapter.send_text.call_args[0][1]
    assert "true" in text or "false" in text


@pytest.mark.asyncio
async def test_feature_command_rejects_missing_args(mock_adapter):
    ctx = make_ctx(mock_adapter, args=["update_group_avatar"])

    with patch("src.handlers.commands.check_admin_permission", return_value=(True, None)):
        await feature_command(ctx)

    text = mock_adapter.send_text.call_args[0][1]
    assert "Usage" in text


# ======================================================
# Avatar cooldown tests
# ======================================================

class TestShouldUpdateAvatar:
    def test_returns_true_when_never_updated(self):
        config = ChatConfig(chat_id=1, last_avatar_update_at=None)
        assert _should_update_avatar(config) is True

    def test_returns_false_when_updated_recently(self):
        config = ChatConfig(
            chat_id=1,
            last_avatar_update_at=datetime.utcnow() - timedelta(minutes=30)
        )
        assert _should_update_avatar(config) is False

    def test_returns_true_when_cooldown_expired(self):
        config = ChatConfig(
            chat_id=1,
            last_avatar_update_at=datetime.utcnow() - timedelta(hours=2)
        )
        assert _should_update_avatar(config) is True

    def test_exactly_at_boundary_is_true(self):
        config = ChatConfig(
            chat_id=1,
            last_avatar_update_at=datetime.utcnow() - AVATAR_UPDATE_INTERVAL
        )
        assert _should_update_avatar(config) is True


# ======================================================
# _update_group_avatar integration tests
# ======================================================

@pytest.mark.asyncio
async def test_update_group_avatar_calls_adapter(mock_adapter):
    from src.handlers.input_handler import InputHandler

    handler = InputHandler()
    mock_controller = MagicMock()
    png_buf = MagicMock()
    png_buf.getvalue.return_value = b"fakepng"
    mock_controller.get_frame_as_png.return_value = png_buf

    mock_adapter.update_chat_photo = AsyncMock()
    config = ChatConfig(chat_id=1, feature_flags={"update_group_avatar": True})

    with patch("src.handlers.input_handler.state_manager") as mock_state:
        await handler._update_group_avatar(1, mock_controller, mock_adapter, config)

    mock_adapter.update_chat_photo.assert_called_once_with(1, b"fakepng")
    assert config.last_avatar_update_at is not None
    mock_state.save_chat_config.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_update_group_avatar_sends_error_on_failure(mock_adapter):
    from src.handlers.input_handler import InputHandler

    handler = InputHandler()
    mock_controller = MagicMock()
    png_buf = MagicMock()
    png_buf.getvalue.return_value = b"fakepng"
    mock_controller.get_frame_as_png.return_value = png_buf

    mock_adapter.update_chat_photo = AsyncMock(side_effect=Exception("Forbidden"))
    mock_adapter.send_text = AsyncMock()

    config = ChatConfig(chat_id=1, feature_flags={"update_group_avatar": True})

    with patch("src.handlers.input_handler.state_manager"):
        await handler._update_group_avatar(1, mock_controller, mock_adapter, config)

    mock_adapter.send_text.assert_called_once()
    text = mock_adapter.send_text.call_args[0][1]
    assert "Failed" in text or "admin" in text
