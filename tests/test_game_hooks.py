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
