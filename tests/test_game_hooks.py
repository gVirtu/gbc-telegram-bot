"""Tests for dynamic game hook loading."""

import pytest
from unittest.mock import MagicMock, patch


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
        """Test begin_hooks calls the module function with restructured context."""
        from src.game import GameController

        controller = GameController(123456)

        mock_pyboy = MagicMock()
        controller.pyboy = mock_pyboy
        controller._initialized = True

        controller._hook_module = controller._load_hook_module("PKPCRYSTAL")

        result = controller.begin_hooks()

        assert "_counters" in result
        assert "_events" in result
        assert isinstance(result["_events"], list)
        assert len(result["_events"]) == 0
        assert "dangerousActions" in result["_counters"]
        assert "inputWaitCalls" in result["_counters"]
        assert "autoPressA" in result["_counters"]
        assert "_total" in result["_counters"]["dangerousActions"]

    def test_end_hooks_calls_module(self):
        """Test end_hooks calls the module function with nested context."""
        from src.game import GameController

        controller = GameController(123456)

        mock_pyboy = MagicMock()
        controller.pyboy = mock_pyboy
        controller._initialized = True

        controller._hook_module = controller._load_hook_module("PKPCRYSTAL")

        context = {
            "_counters": {
                "dangerousActions": {"TossMenu": 0, "_total": 0},
                "inputWaitCalls": {"WaitButton": 0, "_total": 0},
            },
            "_events": [],
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
        from unittest.mock import MagicMock, PropertyMock
        import numpy as np

        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")

        controller = GameController(123456, rom_path=rom_path, sym_path=None)

        with patch("src.game.PyBoy") as mock_pyboy_class, \
             patch("src.game_status_bars.pkpcrystal.init"):
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
        from unittest.mock import MagicMock, PropertyMock
        import numpy as np

        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")

        controller = GameController(123456, rom_path=rom_path, sym_path=None)

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
        from unittest.mock import MagicMock, PropertyMock
        import numpy as np

        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")
        controller = GameController(123456, rom_path=rom_path, sym_path=None)

        with patch("src.game.PyBoy") as mock_pyboy_class, \
             patch("src.game_status_bars.pkpcrystal.init"):
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
        from unittest.mock import MagicMock, PropertyMock
        import numpy as np

        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")
        controller = GameController(123456, rom_path=rom_path, sym_path=None)

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


class TestHookContextStructure:
    """Test the restructured hook context dict."""

    def test_begin_hooks_context_structure(self):
        """Test begin_hooks returns properly nested context."""
        from src.game import GameController

        controller = GameController(123456)
        mock_pyboy = MagicMock()
        controller.pyboy = mock_pyboy
        controller._initialized = True
        controller._hook_module = controller._load_hook_module("PKPCRYSTAL")

        result = controller.begin_hooks()

        assert isinstance(result, dict)
        assert "_counters" in result
        assert "_events" in result
        assert isinstance(result["_events"], list)
        assert len(result["_events"]) == 0
        assert set(result["_counters"].keys()) == {"dangerousActions", "inputWaitCalls", "autoPressA"}

    def test_game_event_hook_creates_dict_with_title_and_score(self):
        """Test that a game event hook appends an event dict with title and awarded_score from GAME_EVENTS."""
        from src.game_hooks.pkpcrystal import register_game_event_hooks

        controller = MagicMock()
        controller.get_capture_frame_offset.return_value = 5

        context = {"_events": []}

        register_game_event_hooks(controller, context)

        assert controller.pyboy.hook_register.call_count > 0

        wild_battle_calls = [
            call for call in controller.pyboy.hook_register.call_args_list
            if call[0][1] == "DoBattle.wild"
        ]
        assert len(wild_battle_calls) == 1
        hook_fn = wild_battle_calls[0][0][2]

        def mock_read_u8(pyboy, sym):
            return 1  # wild battle

        with patch("src.game_events.pkpcrystal.symbol_read_u8", mock_read_u8):
            hook_fn(None)

        events = context["_events"]
        assert len(events) == 1
        event = events[0]
        assert event["event_type"] == "wild_battle_start"
        assert event["title"] == "Wild Battle Started"
        assert event["awarded_score"] == 5
        assert event["frame_offset"] == 5

    def test_game_event_hook_dedup_same_addr(self):
        """Two specs sharing the same addr register one hook but both fire."""
        from src.game_hooks.pkpcrystal import register_game_event_hooks
        from src.game_events.pkpcrystal import GAME_EVENTS

        controller = MagicMock()
        controller.get_capture_frame_offset.return_value = 0

        context = {"_events": []}

        register_game_event_hooks(controller, context)

        faint_calls = [
            call for call in controller.pyboy.hook_register.call_args_list
            if call[0][1] == "EnemyMonFaintedAnimation"
        ]
        assert len(faint_calls) == 1, "dedup failed: multiple registrations same addr"
        hook_fn = faint_calls[0][0][2]

        def mock_read_u8(pyboy, sym):
            return 1  # wild battle

        with patch("src.game_events.pkpcrystal.symbol_read_u8", mock_read_u8):
            hook_fn(None)

        event_types = {e["event_type"] for e in context["_events"]}
        assert "wild_defeated" in event_types
        assert "trainer_pokemon_defeated" not in event_types

    def test_game_event_hook_condition_false_skips(self):
        """A condition returning False does not append the event."""
        from src.game_hooks.pkpcrystal import register_game_event_hooks
        from src.game_events.pkpcrystal import GAME_EVENTS

        controller = MagicMock()
        controller.get_capture_frame_offset.return_value = 0

        context = {"_events": []}

        register_game_event_hooks(controller, context)

        faint_calls = [
            call for call in controller.pyboy.hook_register.call_args_list
            if call[0][1] == "EnemyMonFaintedAnimation"
        ]
        hook_fn = faint_calls[0][0][2]

        def mock_read_u8(pyboy, sym):
            return 0  # overworld — no battle

        with patch("src.game_events.pkpcrystal.symbol_read_u8", mock_read_u8):
            hook_fn(None)

        assert len(context["_events"]) == 0

    def test_game_event_hook_condition_exception_is_logged(self):
        """A condition that raises does not crash and the event is skipped."""
        from src.game_hooks.pkpcrystal import register_game_event_hooks

        controller = MagicMock()
        controller.get_capture_frame_offset.return_value = 0

        context = {"_events": []}

        register_game_event_hooks(controller, context)

        faint_calls = [
            call for call in controller.pyboy.hook_register.call_args_list
            if call[0][1] == "EnemyMonFaintedAnimation"
        ]
        hook_fn = faint_calls[0][0][2]

        def mock_read_u8(pyboy, sym):
            raise RuntimeError("boom")

        with patch("src.game_events.pkpcrystal.symbol_read_u8", mock_read_u8):
            hook_fn(None)

        assert len(context["_events"]) == 0

    def test_game_event_hook_no_condition_always_appends(self):
        """An event without a condition is always appended."""
        from src.game_hooks.pkpcrystal import register_game_event_hooks

        controller = MagicMock()
        controller.get_capture_frame_offset.return_value = 0

        context = {"_events": []}

        register_game_event_hooks(controller, context)

        hof_calls = [
            call for call in controller.pyboy.hook_register.call_args_list
            if call[0][1] == "HallOfFame"
        ]
        hook_fn = hof_calls[0][0][2]

        hook_fn(None)

        assert len(context["_events"]) == 1

    def test_game_event_hook_stores_addrs_in_context(self):
        """register_game_event_hooks stores registered (bank, addr) pairs in context."""
        from src.game_hooks.pkpcrystal import register_game_event_hooks

        controller = MagicMock()
        controller.get_capture_frame_offset.return_value = 0

        context = {"_events": []}

        register_game_event_hooks(controller, context)

        addrs = context.get("_game_event_addrs", [])
        assert len(addrs) > 0
        assert all(isinstance(a, tuple) and len(a) == 2 for a in addrs)

    def test_register_game_event_hooks_exists(self):
        """Test register_game_event_hooks is a callable."""
        from src.game_hooks.pkpcrystal import register_game_event_hooks

        assert callable(register_game_event_hooks)

    def test_deregister_game_event_hooks_exists(self):
        """Test deregister_game_event_hooks is a callable."""
        from src.game_hooks.pkpcrystal import deregister_game_event_hooks

        assert callable(deregister_game_event_hooks)

    def test_deregister_game_event_hooks_uses_context_addrs(self):
        """deregister_game_event_hooks deregisters all stored addrs."""
        from src.game_hooks.pkpcrystal import deregister_game_event_hooks

        controller = MagicMock()

        context = {"_game_event_addrs": [(None, "Foo"), (None, "Bar")]}
        deregister_game_event_hooks(controller, context)

        assert controller.pyboy.hook_deregister.call_count == 2
        called_addrs = [call[0][1] for call in controller.pyboy.hook_deregister.call_args_list]
        assert "Foo" in called_addrs
        assert "Bar" in called_addrs

    def test_deregister_game_event_hooks_empty_context(self):
        """deregister_game_event_hooks handles missing or empty addrs list."""
        from src.game_hooks.pkpcrystal import deregister_game_event_hooks

        controller = MagicMock()

        deregister_game_event_hooks(controller, {})
        controller.pyboy.hook_deregister.assert_not_called()

        deregister_game_event_hooks(controller, {"_game_event_addrs": []})
        controller.pyboy.hook_deregister.assert_not_called()
