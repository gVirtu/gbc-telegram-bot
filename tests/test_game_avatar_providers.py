"""Tests for game avatar provider modules."""


class TestAvatarProviderModuleLoading:
    """Test loading of game avatar provider modules via GameController."""

    def test_load_avatar_provider_module_exists(self):
        """Loading an existing avatar provider module succeeds."""
        from src.game import GameController
        controller = GameController(123456)
        module = controller._load_avatar_provider_module("PKPCRYSTAL")
        assert module is not None
        assert hasattr(module, "get_avatar")

    def test_load_avatar_provider_module_not_found(self):
        """Loading a non-existent avatar provider module returns None."""
        from src.game import GameController
        controller = GameController(123456)
        module = controller._load_avatar_provider_module("NONEXISTENT_GAME")
        assert module is None

    def test_load_avatar_provider_module_lowercase_conversion(self):
        """Cartridge title is lowercased when forming module name."""
        from src.game import GameController
        controller = GameController(123456)
        module = controller._load_avatar_provider_module("PKPCRYSTAL")
        assert module is not None
        assert module.__name__ == "src.game_avatar_providers.pkpcrystal"

    def test_load_avatar_provider_module_empty_title(self):
        """Empty cartridge title returns None."""
        from src.game import GameController
        controller = GameController(123456)
        module = controller._load_avatar_provider_module("")
        assert module is None


class TestGetAvatarFn:
    """Test GameController.get_avatar_fn()."""

    def test_returns_none_when_no_module(self):
        """get_avatar_fn returns None when no module is loaded."""
        from src.game import GameController
        controller = GameController(123456)
        controller._avatar_provider_module = None
        assert controller.get_avatar_fn() is None

    def test_returns_callable_when_module_loaded(self):
        """get_avatar_fn returns the module's get_avatar callable."""
        from src.game import GameController
        from unittest.mock import MagicMock
        controller = GameController(123456)
        mock_module = MagicMock()
        controller._avatar_provider_module = mock_module
        result = controller.get_avatar_fn()
        assert result is mock_module.get_avatar

    def test_returns_none_when_module_lacks_get_avatar(self):
        """get_avatar_fn returns None when module has no get_avatar attribute."""
        from src.game import GameController
        from unittest.mock import MagicMock
        controller = GameController(123456)
        mock_module = MagicMock(spec=[])  # no attributes
        controller._avatar_provider_module = mock_module
        assert controller.get_avatar_fn() is None
