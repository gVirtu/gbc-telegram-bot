"""Tests for dynamic game hook loading."""

import pytest
from unittest.mock import MagicMock, patch
import sys


class TestHookModuleLoading:
    """Test loading of game hook modules."""

    def test_load_hook_module_exists(self):
        """Test loading an existing hook module."""
        from src.game import GameController

        controller = GameController(123456)
        module = controller._load_hook_module("PKPCRYSTAL")

        assert module is not None
        assert hasattr(module, "begin_hooks")
        assert hasattr(module, "end_hooks")

    def test_load_hook_module_not_found(self):
        """Test loading a non-existent hook module returns None."""
        from src.game import GameController

        controller = GameController(123456)
        module = controller._load_hook_module("NONEXISTENT_GAME")

        assert module is None

    def test_load_hook_module_lowercase_conversion(self):
        """Test that cartridge title is converted to lowercase."""
        from src.game import GameController

        controller = GameController(123456)
        # PKPCRYSTAL should load pkpcrystal.py
        module = controller._load_hook_module("PKPCRYSTAL")

        assert module is not None
        assert module.__name__ == "src.game_hooks.pkpcrystal"


class TestBeginHooksNoModule:
    """Test begin_hooks when no module is loaded."""

    def test_begin_hooks_no_module(self):
        """Test begin_hooks returns empty dict when no module."""
        from src.game import GameController

        controller = GameController(123456)
        controller._hook_module = None

        result = controller.begin_hooks()

        assert result == {}

    def test_end_hooks_no_module(self):
        """Test end_hooks is no-op when no module."""
        from src.game import GameController

        controller = GameController(123456)
        controller._hook_module = None

        # Should not raise
        controller.end_hooks({})


class TestBeginHooksWithModule:
    """Test begin_hooks with a loaded module."""

    def test_begin_hooks_calls_module(self):
        """Test begin_hooks calls the module function."""
        from src.game import GameController

        controller = GameController(123456)

        mock_pyboy = MagicMock()
        controller.pyboy = mock_pyboy
        controller._initialized = True

        # Load the real module
        controller._hook_module = controller._load_hook_module("PKPCRYSTAL")

        result = controller.begin_hooks()

        assert "dangerousActions" in result
        assert "inputWaitCalls" in result
        assert "_total" in result["dangerousActions"]

    def test_end_hooks_calls_module(self):
        """Test end_hooks calls the module function."""
        from src.game import GameController

        controller = GameController(123456)

        mock_pyboy = MagicMock()
        controller.pyboy = mock_pyboy
        controller._initialized = True

        controller._hook_module = controller._load_hook_module("PKPCRYSTAL")

        context = {
            "dangerousActions": {"TossMenu": 0, "_total": 0},
            "inputWaitCalls": {"WaitButton": 0, "_total": 0}
        }

        # Should not raise
        controller.end_hooks(context)


class TestBeginHooksModuleMissingFunction:
    """Test graceful handling when module is missing required functions."""

    def test_begin_hooks_missing_function(self):
        """Test begin_hooks handles missing function gracefully."""
        from src.game import GameController

        controller = GameController(123456)
        controller.pyboy = MagicMock()

        # Create a mock module without begin_hooks
        mock_module = MagicMock(spec=[])  # No attributes
        controller._hook_module = mock_module

        result = controller.begin_hooks()

        assert result == {}

    def test_end_hooks_missing_function(self):
        """Test end_hooks handles missing function gracefully."""
        from src.game import GameController

        controller = GameController(123456)
        controller.pyboy = MagicMock()

        # Create a mock module without end_hooks
        mock_module = MagicMock(spec=[])
        controller._hook_module = mock_module

        # Should not raise
        controller.end_hooks({})


class TestIntegration:
    """Integration tests for hook loading during initialization."""

    @pytest.mark.asyncio
    async def test_hooks_loaded_during_init(self, tmp_path):
        """Test that hooks are loaded during GameController initialization."""
        from src.game import GameController
        from unittest.mock import patch, MagicMock, PropertyMock
        import numpy as np

        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")

        controller = GameController(123456, rom_path=rom_path)

        with patch("src.game.PyBoy") as mock_pyboy_class:
            mock_instance = MagicMock()
            mock_instance.cartridge_title = "PKPCRYSTAL"
            mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
            mock_screen = MagicMock()
            type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
            mock_instance.screen = mock_screen
            mock_pyboy_class.return_value = mock_instance

            await controller.initialize()

            assert controller._hook_module is not None
            assert controller._hook_module.__name__ == "src.game_hooks.pkpcrystal"

    @pytest.mark.asyncio
    async def test_hooks_not_loaded_for_unknown_game(self, tmp_path):
        """Test that hooks are None for unknown games."""
        from src.game import GameController
        from unittest.mock import patch, MagicMock, PropertyMock
        import numpy as np

        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")

        controller = GameController(123456, rom_path=rom_path)

        with patch("src.game.PyBoy") as mock_pyboy_class:
            mock_instance = MagicMock()
            mock_instance.cartridge_title = "UNKNOWN_GAME"
            mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
            mock_screen = MagicMock()
            type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
            mock_instance.screen = mock_screen
            mock_pyboy_class.return_value = mock_instance

            await controller.initialize()

            assert controller._hook_module is None
            assert controller.begin_hooks() == {}


class TestModifierModuleLoading:
    """Test loading of game modifier button modules."""

    def test_load_modifier_module_exists(self):
        """Test loading an existing modifier module."""
        from src.game import GameController
        controller = GameController(123456)
        module = controller._load_modifier_module("PKPCRYSTAL")
        assert module is not None
        assert hasattr(module, "MODIFIER_BUTTONS")

    def test_load_modifier_module_not_found(self):
        """Test loading a non-existent modifier module returns None."""
        from src.game import GameController
        controller = GameController(123456)
        module = controller._load_modifier_module("NONEXISTENT_GAME")
        assert module is None

    def test_load_modifier_module_lowercase_conversion(self):
        """Test that cartridge title is converted to lowercase."""
        from src.game import GameController
        controller = GameController(123456)
        module = controller._load_modifier_module("PKPCRYSTAL")
        assert module is not None
        assert module.__name__ == "src.game_modifier_buttons.pkpcrystal"

    def test_get_modifier_specs_with_module(self):
        """Test get_modifier_specs returns specs when module loaded."""
        from src.game import GameController
        from src.models.game_state import ModifierButtonSpec
        controller = GameController(123456)
        controller._modifier_module = controller._load_modifier_module("PKPCRYSTAL")
        specs = controller.get_modifier_specs()
        assert len(specs) > 0
        assert all(isinstance(s, ModifierButtonSpec) for s in specs)

    def test_get_modifier_specs_no_module(self):
        """Test get_modifier_specs returns empty list when no module."""
        from src.game import GameController
        controller = GameController(123456)
        controller._modifier_module = None
        specs = controller.get_modifier_specs()
        assert specs == []

    @pytest.mark.asyncio
    async def test_modifier_module_loaded_during_init(self, tmp_path):
        """Test that modifier module is loaded during GameController initialization."""
        from src.game import GameController
        from unittest.mock import patch, MagicMock, PropertyMock
        import numpy as np

        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")
        controller = GameController(123456, rom_path=rom_path)

        with patch("src.game.PyBoy") as mock_pyboy_class:
            mock_instance = MagicMock()
            mock_instance.cartridge_title = "PKPCRYSTAL"
            mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
            mock_screen = MagicMock()
            type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
            mock_instance.screen = mock_screen
            mock_pyboy_class.return_value = mock_instance

            await controller.initialize()

            assert controller._modifier_module is not None
            assert controller._modifier_module.__name__ == "src.game_modifier_buttons.pkpcrystal"

    @pytest.mark.asyncio
    async def test_modifier_module_none_for_unknown_game(self, tmp_path):
        """Test that modifier module is None for unknown games."""
        from src.game import GameController
        from unittest.mock import patch, MagicMock, PropertyMock
        import numpy as np

        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")
        controller = GameController(123456, rom_path=rom_path)

        with patch("src.game.PyBoy") as mock_pyboy_class:
            mock_instance = MagicMock()
            mock_instance.cartridge_title = "UNKNOWN_GAME"
            mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
            mock_screen = MagicMock()
            type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
            mock_instance.screen = mock_screen
            mock_pyboy_class.return_value = mock_instance

            await controller.initialize()

            assert controller._modifier_module is None
            assert controller.get_modifier_specs() == []
