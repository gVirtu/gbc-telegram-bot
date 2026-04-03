"""Tests for game status bar module loading and data retrieval."""

import pytest
from unittest.mock import MagicMock, patch


class TestStatusBarModuleLoading:
    """Test loading of game status bar modules."""

    def test_load_status_bar_module_exists(self):
        """Test loading an existing status bar module."""
        from src.game import GameController

        controller = GameController(123456)
        module = controller._load_status_bar_module("PKPCRYSTAL")

        assert module is not None
        assert hasattr(module, "get_status_bar_data")

    def test_load_status_bar_module_not_found(self):
        """Test loading a non-existent status bar module returns None."""
        from src.game import GameController

        controller = GameController(123456)
        module = controller._load_status_bar_module("NONEXISTENT_GAME")

        assert module is None

    def test_load_status_bar_module_lowercase_conversion(self):
        """Test that cartridge title is converted to lowercase."""
        from src.game import GameController

        controller = GameController(123456)
        module = controller._load_status_bar_module("PKPCRYSTAL")

        assert module is not None
        assert module.__name__ == "src.game_status_bars.pkpcrystal"

    def test_load_status_bar_module_empty_title(self):
        """Test that empty cartridge title returns None."""
        from src.game import GameController

        controller = GameController(123456)
        module = controller._load_status_bar_module("")

        assert module is None


class TestGetStatusBarData:
    """Test get_status_bar_data on GameController."""

    def test_returns_none_when_no_module(self):
        """Test get_status_bar_data returns None when no module loaded."""
        from src.game import GameController

        controller = GameController(123456)
        controller._status_bar_module = None

        result = controller.get_status_bar_data()

        assert result is None

    def test_returns_none_when_module_lacks_function(self):
        """Test get_status_bar_data returns None when module has no get_status_bar_data."""
        from src.game import GameController

        controller = GameController(123456)
        mock_module = MagicMock(spec=[])  # no attributes
        controller._status_bar_module = mock_module

        result = controller.get_status_bar_data()

        assert result is None

    def test_calls_module_function(self):
        """Test get_status_bar_data delegates to the module function."""
        from src.game import GameController

        controller = GameController(123456)
        mock_pyboy = MagicMock()
        controller.pyboy = mock_pyboy
        controller._initialized = True

        expected = {"map_group": 1, "map_number": 2, "party": [1, 2, 3, 4, 5, 6]}
        mock_module = MagicMock()
        mock_module.get_status_bar_data.return_value = expected
        controller._status_bar_module = mock_module

        result = controller.get_status_bar_data()

        assert result == expected
        mock_module.get_status_bar_data.assert_called_once_with(mock_pyboy)

    def test_returns_none_on_exception(self):
        """Test get_status_bar_data returns None when module raises."""
        from src.game import GameController

        controller = GameController(123456)
        mock_pyboy = MagicMock()
        controller.pyboy = mock_pyboy

        mock_module = MagicMock()
        mock_module.get_status_bar_data.side_effect = RuntimeError("memory error")
        controller._status_bar_module = mock_module

        result = controller.get_status_bar_data()

        assert result is None
