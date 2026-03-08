"""Tests verifying that state-changing commands are blocked from mirror chats."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.adapters.base import CommandContext
from src.handlers.commands import (
    start_game_command,
    reboot_command,
    save_command,
    load_command,
    message_command,
    language_command,
    maintenance_command,
)

LEADER_ID = 100
MIRROR_ID = 200


def _make_ctx(chat_id: int, args: list[str] = None):
    adapter = MagicMock()
    adapter.platform = "telegram"
    adapter.send_text = AsyncMock()
    adapter.is_admin = AsyncMock(return_value=True)
    return CommandContext(
        chat_id=chat_id,
        user_id=1,
        user_name="TestUser",
        args=args or [],
        adapter=adapter,
        raw=None,
    )


def _patch_mirror(leader_id: int):
    """Patch get_leader_chat_id to return leader_id."""
    return patch("src.handlers.commands.get_leader_chat_id", return_value=leader_id)


def _patch_admin_ok():
    return patch(
        "src.handlers.commands.check_admin_permission",
        new=AsyncMock(return_value=(True, None)),
    )


@pytest.mark.asyncio
class TestMirrorBlockedCommands:
    async def test_start_game_blocked_from_mirror(self):
        ctx = _make_ctx(MIRROR_ID)
        with _patch_mirror(LEADER_ID), _patch_admin_ok(), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "mirror error"
            await start_game_command(ctx)

        mock_t.get.assert_called_with("commands.error_mirror_only_leader", MIRROR_ID)
        ctx.adapter.send_text.assert_called_once_with(MIRROR_ID, "mirror error")

    async def test_reboot_blocked_from_mirror(self):
        ctx = _make_ctx(MIRROR_ID)
        with _patch_mirror(LEADER_ID), _patch_admin_ok(), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "mirror error"
            await reboot_command(ctx)

        mock_t.get.assert_called_with("commands.error_mirror_only_leader", MIRROR_ID)
        ctx.adapter.send_text.assert_called_once_with(MIRROR_ID, "mirror error")

    async def test_save_blocked_from_mirror(self):
        ctx = _make_ctx(MIRROR_ID)
        with _patch_mirror(LEADER_ID), _patch_admin_ok(), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "mirror error"
            await save_command(ctx)

        mock_t.get.assert_called_with("commands.error_mirror_only_leader", MIRROR_ID)
        ctx.adapter.send_text.assert_called_once_with(MIRROR_ID, "mirror error")

    async def test_load_blocked_from_mirror(self):
        ctx = _make_ctx(MIRROR_ID)
        with _patch_mirror(LEADER_ID), _patch_admin_ok(), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "mirror error"
            await load_command(ctx)

        mock_t.get.assert_called_with("commands.error_mirror_only_leader", MIRROR_ID)
        ctx.adapter.send_text.assert_called_once_with(MIRROR_ID, "mirror error")

    async def test_message_command_blocked_from_mirror(self):
        ctx = _make_ctx(MIRROR_ID, args=["hello"])
        with _patch_mirror(LEADER_ID), _patch_admin_ok(), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "mirror error"
            await message_command(ctx)

        mock_t.get.assert_called_with("commands.error_mirror_only_leader", MIRROR_ID)
        ctx.adapter.send_text.assert_called_once_with(MIRROR_ID, "mirror error")

    async def test_language_change_blocked_from_mirror(self):
        ctx = _make_ctx(MIRROR_ID, args=["en-US"])
        with _patch_mirror(LEADER_ID), _patch_admin_ok(), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "mirror error"
            await language_command(ctx)

        mock_t.get.assert_called_with("commands.error_mirror_only_leader", MIRROR_ID)
        ctx.adapter.send_text.assert_called_once_with(MIRROR_ID, "mirror error")

    async def test_maintenance_toggle_blocked_from_mirror(self):
        ctx = _make_ctx(MIRROR_ID, args=["on"])
        with _patch_mirror(LEADER_ID), _patch_admin_ok(), \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_t.get.return_value = "mirror error"
            await maintenance_command(ctx)

        mock_t.get.assert_called_with("commands.error_mirror_only_leader", MIRROR_ID)
        ctx.adapter.send_text.assert_called_once_with(MIRROR_ID, "mirror error")


@pytest.mark.asyncio
class TestMirrorAllowedCases:
    async def test_start_game_allowed_from_leader(self):
        """When leader_id == chat_id, the mirror check passes."""
        ctx = _make_ctx(LEADER_ID)
        with _patch_mirror(LEADER_ID), _patch_admin_ok(), \
             patch("src.handlers.commands.translation_manager") as mock_t, \
             patch("src.handlers.commands.get_input_handler") as mock_handler_fn:
            mock_t.get.return_value = "starting..."
            mock_handler = MagicMock()
            mock_handler.cleanup_session = MagicMock()
            mock_handler.start_game = AsyncMock(return_value=42)
            mock_handler_fn.return_value = mock_handler

            await start_game_command(ctx)

        # Should NOT have called error_mirror_only_leader
        for call in mock_t.get.call_args_list:
            assert call.args[0] != "commands.error_mirror_only_leader"

    async def test_language_status_allowed_from_mirror(self):
        """No-args language query (read-only) must not be blocked from mirror."""
        ctx = _make_ctx(MIRROR_ID, args=[])
        with _patch_mirror(LEADER_ID), \
             patch("src.handlers.commands.state_manager") as mock_sm, \
             patch("src.handlers.commands.translation_manager") as mock_t, \
             patch("src.handlers.commands.settings") as mock_settings, \
             patch("src.handlers.commands.SUPPORTED_LANGUAGES", ["en-US"]):
            mock_sm.get_or_create_chat_config.return_value = MagicMock(language=None)
            mock_settings.default_language = "en-US"
            mock_t.get.return_value = "info"

            await language_command(ctx)

        for call in mock_t.get.call_args_list:
            assert call.args[0] != "commands.error_mirror_only_leader"
        # Should have sent the status (3 sends merged into one send_text)
        ctx.adapter.send_text.assert_called_once()

    async def test_maintenance_status_allowed_from_mirror(self):
        """No-args maintenance query (read-only) must not be blocked from mirror."""
        ctx = _make_ctx(MIRROR_ID, args=[])
        with _patch_mirror(LEADER_ID), _patch_admin_ok(), \
             patch("src.handlers.commands.state_manager") as mock_sm, \
             patch("src.handlers.commands.translation_manager") as mock_t:
            mock_sm.get_or_create_chat_config.return_value = MagicMock(maintenance_mode=False)
            mock_t.get.return_value = "status info"

            await maintenance_command(ctx)

        for call in mock_t.get.call_args_list:
            assert call.args[0] != "commands.error_mirror_only_leader"
        ctx.adapter.send_text.assert_called_once_with(MIRROR_ID, "status info")
