# Dynamic Game Hooks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace hardcoded Polished Crystal hooks with dynamically loaded hook modules based on cartridge title.

**Architecture:** Hook modules in `src/game_hooks/` export `begin_hooks(pyboy) -> dict` and `end_hooks(pyboy, context) -> None`. GameController loads the module matching the lowercase cartridge title during initialization.

**Tech Stack:** Python importlib for dynamic module loading, existing PyBoy hook API.

---

### Task 1: Create game_hooks Package

**Files:**
- Create: `src/game_hooks/__init__.py`

**Step 1: Create the package init file**

```python
"""Game-specific hook modules for PyBoy emulator.

Each module is named after the lowercase cartridge title and exports:
- begin_hooks(pyboy) -> dict: Register hooks, return context
- end_hooks(pyboy, context) -> None: Deregister hooks
"""
```

**Step 2: Verify file created**

Run: `ls src/game_hooks/`
Expected: `__init__.py` exists

**Step 3: Commit**

```bash
git add src/game_hooks/__init__.py
git commit -m "feat: create game_hooks package structure"
```

---

### Task 2: Extract Polished Crystal Hooks to Module

**Files:**
- Create: `src/game_hooks/pkpcrystal.py`

**Step 1: Create the hook module**

```python
"""Hooks for Polished Crystal (PKPCRYSTAL).

Provides game-specific hooks for:
- Blocking dangerous actions (releasing Pokemon, tossing items)
- Detecting input wait loops for early animation termination
"""

import logging

logger = logging.getLogger(__name__)


def begin_hooks(pyboy) -> dict:
    """Register Polished Crystal hooks.

    Args:
        pyboy: PyBoy emulator instance

    Returns:
        Context dict with counters for dangerous actions and input wait calls
    """
    context = {
        "dangerousActions": {
            "TossMenu": 0,
            "BillsPC_Release": 0,
            "BillsPC_ReleaseAll": 0,
            "_total": 0
        },
        "inputWaitCalls": {
            "DoPlayerMovement.GetAction": 0,
            "JoyWaitAorB": 0,
            "WaitButton": 0,
            "WaitPressAorB_BlinkCursor": 0,
            "ButtonSound.input_wait_loop": 0,
            "Do2DMenuRTCJoypad_loop": 0,
            "SummaryScreenLoop": 0,
            "NamingScreenJoypadLoop": 0,
            "_total": 0
        }
    }

    def increment_context_counter(ctx, path):
        target = ctx
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] += 1
        target["_total"] += 1
        return None

    def make_hook(category, action):
        return lambda ctx: increment_context_counter(ctx, [category, action])

    for action in context["dangerousActions"].keys():
        if action.startswith("_"):
            continue
        pyboy.hook_register(None, action, make_hook("dangerousActions", action), context)

    for action in context["inputWaitCalls"].keys():
        if action.startswith("_"):
            continue
        pyboy.hook_register(None, action, make_hook("inputWaitCalls", action), context)

    return context


def end_hooks(pyboy, context: dict) -> None:
    """Deregister Polished Crystal hooks.

    Args:
        pyboy: PyBoy emulator instance
        context: Context dict from begin_hooks
    """
    for action in context["dangerousActions"].keys():
        if action.startswith("_"):
            continue
        pyboy.hook_deregister(None, action)

    for action in context["inputWaitCalls"].keys():
        if action.startswith("_"):
            continue
        pyboy.hook_deregister(None, action)
```

**Step 2: Verify syntax**

Run: `python -m py_compile src/game_hooks/pkpcrystal.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add src/game_hooks/pkpcrystal.py
git commit -m "feat: extract Polished Crystal hooks to dedicated module"
```

---

### Task 3: Write Tests for Hook Module Loading

**Files:**
- Create: `tests/test_game_hooks.py`

**Step 1: Write failing tests**

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_game_hooks.py -v`
Expected: Multiple failures (methods don't exist yet)

**Step 3: Commit**

```bash
git add tests/test_game_hooks.py
git commit -m "test: add failing tests for dynamic hook loading"
```

---

### Task 4: Implement Hook Loading in GameController

**Files:**
- Modify: `src/game.py:52-69` (add `_hook_module` attribute)
- Modify: `src/game.py:71-112` (load hooks in `initialize()`)
- Modify: `src/game.py:311-365` (replace with new methods)

**Step 1: Add `_hook_module` attribute to `__init__`**

In `GameController.__init__`, add after `self._initialized = False`:

```python
self._hook_module: Optional[ModuleType] = None  # Loaded hook module
```

Also add import at top of file:

```python
from types import ModuleType
```

**Step 2: Add `_load_hook_module` method**

Add after `is_initialized()` method (around line 120):

```python
def _load_hook_module(self, cartridge_title: str) -> Optional[ModuleType]:
    """Dynamically load hook module for a cartridge.

    Args:
        cartridge_title: PyBoy cartridge title (e.g., "PKPCRYSTAL")

    Returns:
        Module if found, None otherwise
    """
    if not cartridge_title:
        return None

    module_name = f"src.game_hooks.{cartridge_title.lower()}"

    try:
        import importlib
        module = importlib.import_module(module_name)
        logger.debug(f"Loaded hook module: {module_name}")
        return module
    except ImportError:
        logger.debug(f"No hook module found for: {cartridge_title}")
        return None
```

**Step 3: Load hooks in `initialize()`**

In `initialize()`, after `self._initialized = True`, add:

```python
# Load game-specific hooks based on cartridge title
self._hook_module = self._load_hook_module(self.pyboy.cartridge_title)
```

**Step 4: Replace `begin_polished_crystal_hooks` with `begin_hooks`**

Replace the entire `begin_polished_crystal_hooks` method (lines 311-353) with:

```python
def begin_hooks(self) -> dict:
    """Begin hooks for the current game.

    Returns:
        Context dict from hook module, or empty dict if no hooks.
    """
    if self._hook_module is None:
        return {}

    try:
        return self._hook_module.begin_hooks(self.pyboy)
    except AttributeError:
        logger.warning(f"Hook module missing begin_hooks function")
        return {}
    except Exception as e:
        logger.error(f"Hook registration failed: {e}")
        return {}
```

**Step 5: Replace `end_polished_crystal_hooks` with `end_hooks`**

Replace the entire `end_polished_crystal_hooks` method (lines 356-364) with:

```python
def end_hooks(self, context: dict) -> None:
    """End hooks for the current game.

    Args:
        context: Context dict from begin_hooks
    """
    if self._hook_module is None:
        return

    try:
        self._hook_module.end_hooks(self.pyboy, context)
    except AttributeError:
        logger.warning(f"Hook module missing end_hooks function")
    except Exception as e:
        logger.error(f"Hook deregistration failed: {e}")
```

**Step 6: Run tests to verify they pass**

Run: `poetry run pytest tests/test_game_hooks.py -v`
Expected: All tests pass

**Step 7: Commit**

```bash
git add src/game.py
git commit -m "feat: implement dynamic hook loading in GameController"
```

---

### Task 5: Update InputHandler to Use New Methods

**Files:**
- Modify: `src/handlers/input_handler.py:314`
- Modify: `src/handlers/input_handler.py:378`

**Step 1: Update begin_hooks call (line 314)**

Change:
```python
hook_context = controller.begin_polished_crystal_hooks()
```

To:
```python
hook_context = controller.begin_hooks()
```

**Step 2: Update end_hooks call (line 378)**

Change:
```python
controller.end_polished_crystal_hooks(hook_context)
```

To:
```python
controller.end_hooks(hook_context)
```

**Step 3: Run all tests to verify no regression**

Run: `poetry run pytest -v`
Expected: All tests pass

**Step 4: Commit**

```bash
git add src/handlers/input_handler.py
git commit -m "refactor: use generic begin_hooks/end_hooks in InputHandler"
```

---

### Task 6: Add Integration Test

**Files:**
- Modify: `tests/test_game_hooks.py`

**Step 1: Add integration test**

Append to `tests/test_game_hooks.py`:

```python
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
```

**Step 2: Run tests to verify**

Run: `poetry run pytest tests/test_game_hooks.py -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/test_game_hooks.py
git commit -m "test: add integration tests for hook loading"
```

---

### Task 7: Run Full Test Suite

**Step 1: Run all tests**

Run: `poetry run pytest`
Expected: All tests pass

**Step 2: Run type checking (if configured)**

Run: `poetry run mypy src/` or `poetry run pyright src/`
Expected: No errors

**Step 3: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: resolve any remaining test issues"
```

---

## Summary

This plan creates a dynamic hook loading system:

1. `src/game_hooks/__init__.py` - Package marker
2. `src/game_hooks/pkpcrystal.py` - Extracted Polished Crystal hooks
3. `src/game.py` - `_load_hook_module()`, `begin_hooks()`, `end_hooks()`
4. `src/handlers/input_handler.py` - Use generic methods
5. `tests/test_game_hooks.py` - Comprehensive test coverage

**Adding hooks for new games:**
1. Create `src/game_hooks/<lowercase_title>.py`
2. Export `begin_hooks(pyboy) -> dict` and `end_hooks(pyboy, context) -> None`
3. No other code changes needed
