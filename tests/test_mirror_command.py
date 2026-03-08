"""Tests for the /mirror command."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.adapters.base import CommandContext
from src.handlers.commands import mirror_command, COMMAND_HANDLERS
from src.models.game_state import ChatConfig


def _make_ctx(chat_id: int, args: list[str], is_admin: bool = True):
    adapter = MagicMock()
    adapter.platform = "telegram"
    adapter.send_text = AsyncMock()
    adapter.is_admin = AsyncMock(return_value=is_admin)
    return CommandContext(
        chat_id=chat_id,
        user_id=1,
        user_name="TestUser",
        args=args,
        adapter=adapter,
        raw=None,
    )


@pytest.mark.asyncio
class TestMirrorCommandRegistration:
    async def test_mirror_in_command_handlers(self):
        assert "mirror" in COMMAND_HANDLERS
        assert COMMAND_HANDLERS["mirror"] is mirror_command


@pytest.mark.asyncio
class TestMirrorCommandNoArgs:
    async def test_no_args_sends_usage(self):
        ctx = _make_ctx(10, [])
        with patch("src.handlers.commands.state_manager"), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "usage text"
            await mirror_command(ctx)

        mock_t.get.assert_called_with("commands.mirror.usage", 10)
        ctx.adapter.send_text.assert_called_once_with(10, "usage text")


@pytest.mark.asyncio
class TestMirrorCommandStatus:
    async def test_status_independent(self):
        ctx = _make_ctx(10, ["status"])
        with patch("src.handlers.commands.state_manager") as mock_sm, \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_sm.load_chat_config.return_value = ChatConfig(chat_id=10)
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_t.get.return_value = "independent"

            await mirror_command(ctx)

        mock_t.get.assert_called_with("commands.mirror.status_independent", 10)
        ctx.adapter.send_text.assert_called_once_with(10, "independent")

    async def test_status_as_mirror(self):
        ctx = _make_ctx(20, ["status"])
        with patch("src.handlers.commands.state_manager") as mock_sm, \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_sm.load_chat_config.return_value = ChatConfig(chat_id=20, mirrors_chat_id=10)
            mock_t.get.return_value = "mirroring 10"

            await mirror_command(ctx)

        mock_t.get.assert_called_with("commands.mirror.status_as_mirror", 20, leader_id=10)

    async def test_status_as_leader(self):
        ctx = _make_ctx(10, ["status"])
        with patch("src.handlers.commands.state_manager") as mock_sm, \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_sm.load_chat_config.return_value = ChatConfig(chat_id=10)
            mock_sm.get_mirror_chat_ids.return_value = [20, 30]
            mock_t.get.return_value = "leader"

            await mirror_command(ctx)

        mock_t.get.assert_called_with("commands.mirror.status_as_leader", 10, mirrors="20, 30")


@pytest.mark.asyncio
class TestMirrorCommandUnset:
    async def test_unset_requires_admin(self):
        ctx = _make_ctx(20, ["unset"], is_admin=False)
        with patch("src.handlers.commands.state_manager"), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "admin required"
            await mirror_command(ctx)

        ctx.adapter.send_text.assert_called_once_with(20, "admin required")

    async def test_unset_clears_mirrors_chat_id(self):
        ctx = _make_ctx(20, ["unset"])
        config = ChatConfig(chat_id=20, mirrors_chat_id=10)
        with patch("src.handlers.commands.state_manager") as mock_sm, \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_sm.get_or_create_chat_config.return_value = config
            mock_t.get.return_value = "unset success"

            await mirror_command(ctx)

        assert config.mirrors_chat_id is None
        mock_sm.save_chat_config.assert_called_once_with(config)
        ctx.adapter.send_text.assert_called_once_with(20, "unset success")


@pytest.mark.asyncio
class TestMirrorCommandSet:
    async def test_set_requires_admin(self):
        ctx = _make_ctx(20, ["10"], is_admin=False)
        with patch("src.handlers.commands.state_manager"), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "admin required"
            await mirror_command(ctx)

        ctx.adapter.send_text.assert_called_once()

    async def test_set_invalid_id(self):
        ctx = _make_ctx(20, ["not_a_number"])
        with patch("src.handlers.commands.state_manager"), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "invalid id"
            await mirror_command(ctx)

        mock_t.get.assert_called_with("commands.mirror.error_invalid_id", 20)

    async def test_set_self_target_rejected(self):
        ctx = _make_ctx(10, ["10"])
        with patch("src.handlers.commands.state_manager"), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "self error"
            await mirror_command(ctx)

        mock_t.get.assert_called_with("commands.mirror.error_target_is_self", 10)

    async def test_set_leader_not_found(self):
        ctx = _make_ctx(20, ["10"])
        with patch("src.handlers.commands.state_manager") as mock_sm, \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_sm.load_chat_config.return_value = None
            mock_t.get.return_value = "not found"
            await mirror_command(ctx)

        mock_t.get.assert_called_with("commands.mirror.error_leader_not_found", 20, leader_id=10)

    async def test_set_leader_is_mirror_rejected(self):
        ctx = _make_ctx(20, ["10"])
        with patch("src.handlers.commands.state_manager") as mock_sm, \
             patch("src.handlers.commands.translation_manager") as mock_t:
            # Leader is itself a mirror
            mock_sm.load_chat_config.return_value = ChatConfig(chat_id=10, mirrors_chat_id=5)
            mock_t.get.return_value = "target is mirror"
            await mirror_command(ctx)

        mock_t.get.assert_called_with("commands.mirror.error_target_is_mirror", 20)

    async def test_set_current_has_mirrors_rejected(self):
        ctx = _make_ctx(20, ["10"])
        with patch("src.handlers.commands.state_manager") as mock_sm, \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_sm.load_chat_config.return_value = ChatConfig(chat_id=10)
            mock_sm.get_mirror_chat_ids.return_value = [30]  # 20 already has mirrors
            mock_t.get.return_value = "has mirrors"
            await mirror_command(ctx)

        mock_t.get.assert_called_with("commands.mirror.error_current_has_mirrors", 20)

    async def test_set_success(self):
        ctx = _make_ctx(20, ["10"])
        config = ChatConfig(chat_id=20)
        with patch("src.handlers.commands.state_manager") as mock_sm, \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_sm.load_chat_config.return_value = ChatConfig(chat_id=10)
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = config
            mock_t.get.return_value = "success"
            await mirror_command(ctx)

        assert config.mirrors_chat_id == 10
        mock_sm.save_chat_config.assert_called_once_with(config)
        ctx.adapter.send_text.assert_called_once_with(20, "success")
        mock_t.get.assert_called_with("commands.mirror.set_success", 20, leader_id=10)
