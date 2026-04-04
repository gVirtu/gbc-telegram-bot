"""Tests for GameController init callback dispatch."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.game import GameController


def _make_controller(tmp_path):
    rom = tmp_path / "test.gbc"
    rom.write_bytes(b"\x00" * 0x200)
    sym = tmp_path / "test.sym"
    sym.write_text("")
    return GameController(chat_id=1, rom_path=rom, sym_path=sym)


@pytest.mark.asyncio
async def test_init_called_when_module_has_it(tmp_path):
    controller = _make_controller(tmp_path)
    mock_module = MagicMock()
    mock_module.init = MagicMock()

    with patch("src.game.PyBoy") as MockPyBoy:
        mock_pyboy = MagicMock()
        mock_pyboy.cartridge_title = "TESTGAME"
        MockPyBoy.return_value = mock_pyboy

        with patch.object(controller, "_load_status_bar_module", return_value=mock_module), \
             patch.object(controller, "_load_hook_module", return_value=None), \
             patch.object(controller, "_load_modifier_module", return_value=None):
            await controller.initialize()

    mock_module.init.assert_called_once_with(mock_pyboy)


@pytest.mark.asyncio
async def test_init_skipped_when_module_has_no_init(tmp_path):
    controller = _make_controller(tmp_path)
    mock_module = MagicMock(spec=[])  # no attributes

    with patch("src.game.PyBoy") as MockPyBoy:
        mock_pyboy = MagicMock()
        mock_pyboy.cartridge_title = "TESTGAME"
        MockPyBoy.return_value = mock_pyboy

        with patch.object(controller, "_load_status_bar_module", return_value=mock_module), \
             patch.object(controller, "_load_hook_module", return_value=None), \
             patch.object(controller, "_load_modifier_module", return_value=None):
            await controller.initialize()  # must not raise


@pytest.mark.asyncio
async def test_init_skipped_when_no_module(tmp_path):
    controller = _make_controller(tmp_path)

    with patch("src.game.PyBoy") as MockPyBoy:
        mock_pyboy = MagicMock()
        mock_pyboy.cartridge_title = "NONE"
        MockPyBoy.return_value = mock_pyboy

        with patch.object(controller, "_load_status_bar_module", return_value=None), \
             patch.object(controller, "_load_hook_module", return_value=None), \
             patch.object(controller, "_load_modifier_module", return_value=None):
            await controller.initialize()  # must not raise
