# Game Modifier Buttons Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the hardcoded `running_mode`/`GameButton.RUN` system with a generic `game_modifier_buttons` plugin layer that loads game-specific modifier button specs at runtime.

**Architecture:** A new `src/game_modifier_buttons/` package mirrors `src/game_hooks/`: `GameController` loads it by cartridge title at initialize time and exposes `get_modifier_specs()`. `ChatConfig` stores a `modifier_states: dict[str, bool]` JSON map instead of a single `running_mode` bool. The keyboard builder receives `chat_config` + `modifier_specs` and dynamically appends a modifier row.

**Tech Stack:** Python 3.11, SQLite3 (via existing migration system), python-telegram-bot, pytest

---

### Task 1: Add `ModifierButtonSpec` dataclass

**Files:**
- Modify: `src/models/game_state.py`
- Modify: `tests/test_models.py`

**Step 1: Write failing test**

Add to `tests/test_models.py` (after the imports block, add `ModifierButtonSpec` to the import):

```python
from src.models.game_state import (
    BUTTON_LAYOUT,
    ChatConfig,
    ChatGameState,
    GameButton,
    GameSession,
    ModifierButtonSpec,
    SaveSlotInfo,
)
```

Add this test class at the end of the file:

```python
class TestModifierButtonSpec:
    """Test ModifierButtonSpec dataclass."""

    def test_basic_creation(self):
        """Test creation with all required fields."""
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        assert spec.key == "run"
        assert spec.modifier_button == GameButton.B
        assert GameButton.UP in spec.applies_to
        assert spec.active_label_key == "keyboard.buttons.running"
        assert spec.inactive_label_key == "keyboard.buttons.walking"

    def test_applies_to_is_list(self):
        """Test applies_to stores a list of GameButtons."""
        spec = ModifierButtonSpec(
            key="test",
            modifier_button=GameButton.A,
            applies_to=[GameButton.UP],
            active_label_key="a",
            inactive_label_key="b",
        )
        assert isinstance(spec.applies_to, list)
        assert spec.applies_to[0] == GameButton.UP
```

**Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_models.py::TestModifierButtonSpec -v
```
Expected: `ImportError: cannot import name 'ModifierButtonSpec'`

**Step 3: Implement — add dataclass to `src/models/game_state.py`**

After the `GameButton` class and before `ChatGameState`, add:

```python
@dataclass
class ModifierButtonSpec:
    """Spec for a game-specific modifier button.

    A modifier button is displayed in the keyboard and, when active,
    causes a modifier button to be held alongside specified inputs.

    Attributes:
        key: Unique identifier used in modifier_states map (e.g. "run")
        modifier_button: Button held during input (e.g. GameButton.B)
        applies_to: Inputs that get the modifier (e.g. directional buttons)
        active_label_key: i18n key for label when modifier is ON
        inactive_label_key: i18n key for label when modifier is OFF
    """

    key: str
    modifier_button: GameButton
    applies_to: list[GameButton]
    active_label_key: str
    inactive_label_key: str
```

**Step 4: Run tests to verify they pass**

```bash
poetry run pytest tests/test_models.py::TestModifierButtonSpec -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/models/game_state.py tests/test_models.py
git commit -m "feat: add ModifierButtonSpec dataclass"
```

---

### Task 2: Create `game_modifier_buttons` package

**Files:**
- Create: `src/game_modifier_buttons/__init__.py`
- Create: `src/game_modifier_buttons/pkpcrystal.py`
- Create: `tests/test_game_modifier_buttons.py`

**Step 1: Write failing test**

Create `tests/test_game_modifier_buttons.py`:

```python
"""Tests for game modifier button modules."""

import pytest
from src.models.game_state import GameButton, ModifierButtonSpec


class TestPkpcrystalModifierButtons:
    """Test Polished Crystal modifier button specs."""

    def test_module_exports_modifier_buttons(self):
        """Test that pkpcrystal module exports MODIFIER_BUTTONS list."""
        from src.game_modifier_buttons import pkpcrystal
        assert hasattr(pkpcrystal, "MODIFIER_BUTTONS")
        assert isinstance(pkpcrystal.MODIFIER_BUTTONS, list)

    def test_run_modifier_spec_present(self):
        """Test that the run modifier spec is present."""
        from src.game_modifier_buttons import pkpcrystal
        keys = [spec.key for spec in pkpcrystal.MODIFIER_BUTTONS]
        assert "run" in keys

    def test_run_modifier_spec_structure(self):
        """Test the run modifier spec has correct structure."""
        from src.game_modifier_buttons import pkpcrystal
        spec = next(s for s in pkpcrystal.MODIFIER_BUTTONS if s.key == "run")
        assert isinstance(spec, ModifierButtonSpec)
        assert spec.modifier_button == GameButton.B
        assert GameButton.UP in spec.applies_to
        assert GameButton.DOWN in spec.applies_to
        assert GameButton.LEFT in spec.applies_to
        assert GameButton.RIGHT in spec.applies_to
        assert spec.active_label_key == "keyboard.buttons.running"
        assert spec.inactive_label_key == "keyboard.buttons.walking"

    def test_non_directional_not_in_applies_to(self):
        """Test that non-directional buttons are not in applies_to."""
        from src.game_modifier_buttons import pkpcrystal
        spec = next(s for s in pkpcrystal.MODIFIER_BUTTONS if s.key == "run")
        assert GameButton.A not in spec.applies_to
        assert GameButton.B not in spec.applies_to
        assert GameButton.START not in spec.applies_to
```

**Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_game_modifier_buttons.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.game_modifier_buttons'`

**Step 3: Create the package**

Create `src/game_modifier_buttons/__init__.py`:

```python
"""Game-specific modifier button modules.

Each module is named after the lowercase cartridge title and exports:
- MODIFIER_BUTTONS: list[ModifierButtonSpec] — modifier buttons for this game
"""
```

Create `src/game_modifier_buttons/pkpcrystal.py`:

```python
"""Modifier buttons for Polished Crystal (PKPCRYSTAL).

Provides game-specific modifier buttons:
- run: Holds B during directional inputs for running
"""

from src.models.game_state import GameButton, ModifierButtonSpec

MODIFIER_BUTTONS = [
    ModifierButtonSpec(
        key="run",
        modifier_button=GameButton.B,
        applies_to=[GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT],
        active_label_key="keyboard.buttons.running",
        inactive_label_key="keyboard.buttons.walking",
    )
]
```

**Step 4: Run tests to verify they pass**

```bash
poetry run pytest tests/test_game_modifier_buttons.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/game_modifier_buttons/ tests/test_game_modifier_buttons.py
git commit -m "feat: add game_modifier_buttons package with pkpcrystal module"
```

---

### Task 3: Add modifier module loading to `GameController`

**Files:**
- Modify: `src/game.py`
- Modify: `tests/test_game_hooks.py`

**Step 1: Write failing tests**

Add to `tests/test_game_hooks.py` (at the end of the file):

```python
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
```

**Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/test_game_hooks.py::TestModifierModuleLoading -v
```
Expected: `AttributeError: 'GameController' object has no attribute '_load_modifier_module'`

**Step 3: Implement in `src/game.py`**

In `GameController.__init__`, add after `self._initialized = False`:
```python
self._modifier_module: Optional[ModuleType] = None
```

In `GameController.initialize()`, after the line `self._hook_module = self._load_hook_module(self.pyboy.cartridge_title)`, add:
```python
self._modifier_module = self._load_modifier_module(self.pyboy.cartridge_title)
```

Add the import at the top of `src/game.py` (add `ModifierButtonSpec` to the existing game_state import):
```python
from src.models.game_state import GameButton, ModifierButtonSpec
```

After `_load_hook_module()`, add:

```python
def _load_modifier_module(self, cartridge_title: str) -> Optional[ModuleType]:
    """Dynamically load modifier button module for a cartridge.

    Args:
        cartridge_title: PyBoy cartridge title (e.g., "PKPCRYSTAL")

    Returns:
        Module if found, None otherwise
    """
    if not cartridge_title:
        return None

    module_name = f"src.game_modifier_buttons.{cartridge_title.lower()}"

    try:
        import importlib
        module = importlib.import_module(module_name)
        logger.debug(f"Loaded modifier module: {module_name}")
        return module
    except ImportError:
        logger.debug(f"No modifier module found for: {cartridge_title}")
        return None

def get_modifier_specs(self) -> list[ModifierButtonSpec]:
    """Get the modifier button specs for the loaded game.

    Returns:
        List of ModifierButtonSpec for this game, or empty list if none
    """
    if self._modifier_module and hasattr(self._modifier_module, "MODIFIER_BUTTONS"):
        return self._modifier_module.MODIFIER_BUTTONS
    return []
```

**Step 4: Run tests to verify they pass**

```bash
poetry run pytest tests/test_game_hooks.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/game.py tests/test_game_hooks.py
git commit -m "feat: add modifier module loading to GameController"
```

---

### Task 4: Replace `running_mode` with `modifier_states` in `ChatConfig` and remove `GameButton.RUN`

This task has two parts: updating `ChatConfig` and cleaning up `GameButton`/`BUTTON_LAYOUT`. Several existing tests will need fixes.

**Files:**
- Modify: `src/models/game_state.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_chat_config.py`
- Modify: `tests/test_game.py`

**Step 1: Write failing tests for new `ChatConfig` behavior**

In `tests/test_chat_config.py`, replace ALL content with:

```python
import pytest
from src.models.game_state import ChatConfig


def test_chat_config_has_modifier_states_field():
    """Test that ChatConfig has modifier_states field defaulting to empty dict."""
    config = ChatConfig(chat_id=123)
    assert hasattr(config, 'modifier_states')
    assert config.modifier_states == {}


def test_chat_config_modifier_states_can_be_set():
    """Test that modifier_states can be set."""
    config = ChatConfig(chat_id=123, modifier_states={"run": True})
    assert config.modifier_states["run"] is True


def test_chat_config_serialization_includes_modifier_states():
    """Test that to_dict includes modifier_states."""
    config = ChatConfig(chat_id=123, modifier_states={"run": True})
    data = config.to_dict()
    assert 'modifier_states' in data
    assert data['modifier_states'] == {"run": True}


def test_chat_config_deserialization_includes_modifier_states():
    """Test that from_dict correctly reads modifier_states."""
    data = {
        'chat_id': 123,
        'input_hold_frames': None,
        'animation_duration': None,
        'auto_save_enabled': True,
        'modifier_states': {"run": True},
        'message_base_text': None,
        'maintenance_mode': False,
        'created_at': '2024-01-01T00:00:00',
        'updated_at': '2024-01-01T00:00:00',
    }
    config = ChatConfig.from_dict(data)
    assert config.modifier_states == {"run": True}


def test_chat_config_from_dict_without_modifier_states_defaults_to_empty():
    """Test backward compatibility: old data without modifier_states defaults to {}."""
    data = {
        'chat_id': 123,
        'input_hold_frames': None,
        'animation_duration': None,
        'auto_save_enabled': True,
        'message_base_text': None,
        'maintenance_mode': False,
        'created_at': '2024-01-01T00:00:00',
        'updated_at': '2024-01-01T00:00:00',
    }
    config = ChatConfig.from_dict(data)
    assert config.modifier_states == {}


def test_chat_config_has_maintenance_mode_field():
    """Test that ChatConfig has maintenance_mode field defaulting to False."""
    config = ChatConfig(chat_id=123)
    assert hasattr(config, 'maintenance_mode')
    assert config.maintenance_mode is False


def test_chat_config_maintenance_mode_can_be_set():
    """Test that maintenance_mode can be set to True."""
    config = ChatConfig(chat_id=123, maintenance_mode=True)
    assert config.maintenance_mode is True


def test_chat_config_serialization_includes_maintenance_mode():
    """Test that to_dict includes maintenance_mode."""
    config = ChatConfig(chat_id=123, maintenance_mode=True)
    data = config.to_dict()
    assert 'maintenance_mode' in data
    assert data['maintenance_mode'] is True
```

**Step 2: Run to verify they fail**

```bash
poetry run pytest tests/test_chat_config.py -v
```
Expected: failures about `modifier_states` not existing

**Step 3: Update `src/models/game_state.py`**

3a. Remove `RUN = "run"` from `GameButton` enum and its entry from `emoji_map`.

3b. Remove the last row `[GameButton.RUN]` from `BUTTON_LAYOUT`, so it becomes:
```python
BUTTON_LAYOUT = [
    [GameButton.SELECT, GameButton.UP, GameButton.START],
    [GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT],
    [GameButton.WAIT, GameButton.A, GameButton.B],
]
```

3c. In `ChatConfig`:
- Replace `running_mode: bool = False` with `modifier_states: dict[str, bool] = field(default_factory=dict)`
- Remove the docstring line about `running_mode`, add: `modifier_states: Map of modifier key to active state (e.g. {"run": True})`
- In `to_dict()`, replace `"running_mode": self.running_mode,` with `"modifier_states": self.modifier_states,`
- In `from_dict()`, replace `running_mode=data.get("running_mode", False),` with `modifier_states=data.get("modifier_states", {}),`

**Step 4: Fix broken tests in `tests/test_models.py`**

Update `TestButtonLayout`:
- Remove `assert GameButton.RUN in BUTTON_LAYOUT[3]` — instead assert the layout now has 3 rows:
  ```python
  def test_layout_structure(self):
      assert isinstance(BUTTON_LAYOUT, list)
      assert all(isinstance(row, list) for row in BUTTON_LAYOUT)
      assert GameButton.SELECT in BUTTON_LAYOUT[0]
      assert GameButton.UP in BUTTON_LAYOUT[0]
      assert GameButton.START in BUTTON_LAYOUT[0]
      assert GameButton.LEFT in BUTTON_LAYOUT[1]
      assert GameButton.DOWN in BUTTON_LAYOUT[1]
      assert GameButton.RIGHT in BUTTON_LAYOUT[1]
      assert GameButton.WAIT in BUTTON_LAYOUT[2]
      assert GameButton.A in BUTTON_LAYOUT[2]
      assert GameButton.B in BUTTON_LAYOUT[2]
      assert len(BUTTON_LAYOUT) == 3
  ```
- Update `test_all_buttons_in_layout`: remove `GameButton.RUN` from expectations. Update the count: `assert len(all_buttons) == 9  # 9 active buttons (excluding SEQUENCE, ENVIAR, RUN)`

Remove `ModifierButtonSpec` from the imports in `test_models.py` if it causes issues — it's now already there from Task 1.

**Step 5: Fix broken test in `tests/test_game.py`**

Find this line (around line 23):
```python
meta_actions = {GameButton.WAIT, GameButton.RUN, GameButton.SEQUENCE, GameButton.ENVIAR}
```
Remove `GameButton.RUN` from that set.

**Step 6: Run tests to verify**

```bash
poetry run pytest tests/test_chat_config.py tests/test_models.py tests/test_game.py -v
```
Expected: all PASS

**Step 7: Commit**

```bash
git add src/models/game_state.py tests/test_chat_config.py tests/test_models.py tests/test_game.py
git commit -m "feat: replace running_mode with modifier_states in ChatConfig, remove GameButton.RUN"
```

---

### Task 5: DB migration 007 + update `DatabaseManager`

**Files:**
- Create: `src/db/migrations/007_replace_running_mode_with_modifier_states.py`
- Modify: `src/db/manager.py`
- Modify: `tests/test_database_manager.py`

**Step 1: Write failing test**

Replace the content of `tests/test_database_manager.py` with:

```python
import pytest
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from src.db.manager import DatabaseManager
from src.models.game_state import ChatConfig


@pytest.fixture
def db_manager(tmp_path):
    """Create a temporary database manager for testing."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    yield manager
    manager.close()


def test_save_and_load_chat_config_with_modifier_states(db_manager):
    """Test that modifier_states is saved and loaded correctly."""
    config = ChatConfig(
        chat_id=123,
        maintenance_mode=True,
        modifier_states={"run": True},
        auto_save_enabled=True,
    )

    db_manager.save_chat_config(config)

    loaded = db_manager.load_chat_config(123)
    assert loaded is not None
    assert loaded.maintenance_mode is True
    assert loaded.modifier_states == {"run": True}
    assert loaded.chat_id == 123


def test_save_and_load_chat_config_empty_modifier_states(db_manager):
    """Test that empty modifier_states is saved and loaded correctly."""
    config = ChatConfig(chat_id=456, modifier_states={})
    db_manager.save_chat_config(config)
    loaded = db_manager.load_chat_config(456)
    assert loaded is not None
    assert loaded.modifier_states == {}


def test_get_or_create_chat_config_default_modifier_states(db_manager):
    """Test that get_or_create_chat_config defaults modifier_states to {}."""
    config = db_manager.get_or_create_chat_config(789)
    assert config.modifier_states == {}


def test_get_or_create_chat_config_default_maintenance_mode(db_manager):
    """Test that get_or_create_chat_config defaults maintenance_mode to False."""
    config = db_manager.get_or_create_chat_config(999)
    assert config.maintenance_mode is False
```

**Step 2: Run to verify they fail**

```bash
poetry run pytest tests/test_database_manager.py -v
```
Expected: failures — `modifier_states` column does not exist yet

**Step 3: Create migration file**

Create `src/db/migrations/007_replace_running_mode_with_modifier_states.py`:

```python
"""Migration 007: Replace running_mode with modifier_states in chat_configs.

Adds a modifier_states JSON column, migrates existing running_mode=1 rows
to {"run": true}, then drops the running_mode column.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add modifier_states column, migrate data, drop running_mode."""
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN modifier_states TEXT NOT NULL DEFAULT '{}';
    """)
    conn.execute("""
        UPDATE chat_configs
        SET modifier_states = '{"run": true}'
        WHERE running_mode = 1;
    """)
    conn.execute("ALTER TABLE chat_configs DROP COLUMN running_mode;")


def downgrade(conn: sqlite3.Connection) -> None:
    """Restore running_mode column from modifier_states."""
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN running_mode BOOLEAN NOT NULL DEFAULT 0;
    """)
    conn.execute("""
        UPDATE chat_configs
        SET running_mode = 1
        WHERE json_extract(modifier_states, '$.run') = 1;
    """)
    conn.execute("ALTER TABLE chat_configs DROP COLUMN modifier_states;")
```

**Step 4: Update `src/db/manager.py`**

Add `import json` at the top (after existing imports).

In `save_chat_config()`, replace the SQL and parameters:

```python
def save_chat_config(self, config: ChatConfig) -> None:
    """Save chat configuration to database."""
    sql = """
    INSERT INTO chat_configs
        (chat_id, input_hold_frames, animation_duration, auto_save_enabled, modifier_states, message_base_text, maintenance_mode, language, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(chat_id) DO UPDATE SET
        input_hold_frames = excluded.input_hold_frames,
        animation_duration = excluded.animation_duration,
        auto_save_enabled = excluded.auto_save_enabled,
        modifier_states = excluded.modifier_states,
        message_base_text = excluded.message_base_text,
        maintenance_mode = excluded.maintenance_mode,
        language = excluded.language,
        updated_at = excluded.updated_at;
    """

    self.connection.execute(sql, (
        config.chat_id,
        config.input_hold_frames,
        config.animation_duration,
        1 if config.auto_save_enabled else 0,
        json.dumps(config.modifier_states),
        config.message_base_text,
        1 if config.maintenance_mode else 0,
        config.language,
        config.created_at.isoformat() if config.created_at else datetime.utcnow().isoformat(),
        datetime.utcnow().isoformat()
    ))
    self.connection.commit()
    logger.debug(f"Saved chat config for chat {config.chat_id}")
```

In `load_chat_config()`, update the `ChatConfig(...)` construction — replace `running_mode=bool(row['running_mode']),` with:
```python
modifier_states=json.loads(row['modifier_states']) if 'modifier_states' in row.keys() and row['modifier_states'] else {},
```

**Step 5: Run tests to verify they pass**

```bash
poetry run pytest tests/test_database_manager.py -v
```
Expected: all PASS

**Step 6: Verify migration tests still pass**

```bash
poetry run pytest tests/db/test_migrations.py -v
```
Expected: all PASS (migration runner discovers the new file)

**Step 7: Commit**

```bash
git add src/db/migrations/007_replace_running_mode_with_modifier_states.py src/db/manager.py tests/test_database_manager.py
git commit -m "feat: migration 007 - replace running_mode with modifier_states JSON column"
```

---

### Task 6: Update `keyboard.py`

**Files:**
- Modify: `src/keyboard.py`
- Modify: `tests/test_keyboard.py`
- Modify: `tests/integration/test_i18n.py`

**Step 1: Write failing tests**

Replace `tests/test_keyboard.py` content with:

```python
"""Tests for keyboard layouts."""

import pytest
from unittest.mock import MagicMock, patch

from src.keyboard import (
    create_input_keyboard,
    create_game_message_text,
    create_save_slot_keyboard,
    get_button_from_callback,
    is_valid_button_callback,
    create_help_text,
)
from src.models.game_state import ChatConfig, GameButton, ModifierButtonSpec


class TestCreateInputKeyboard:
    """Test input keyboard creation."""

    def test_returns_markup(self):
        """Test that function returns InlineKeyboardMarkup."""
        keyboard = create_input_keyboard()
        assert hasattr(keyboard, 'inline_keyboard')
        assert isinstance(keyboard.inline_keyboard, (list, tuple))

    def test_no_modifier_specs_has_three_rows(self):
        """Test keyboard has 3 rows when no modifier specs provided."""
        keyboard = create_input_keyboard()
        assert len(keyboard.inline_keyboard) == 3

    def test_with_modifier_specs_appends_row(self):
        """Test that modifier specs add a fourth row."""
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        config = ChatConfig(chat_id=123, modifier_states={})
        keyboard = create_input_keyboard(chat_config=config, modifier_specs=[spec])
        assert len(keyboard.inline_keyboard) == 4

    def test_modifier_button_callback_data(self):
        """Test modifier button uses modifier_ prefix in callback_data."""
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        config = ChatConfig(chat_id=123, modifier_states={})
        keyboard = create_input_keyboard(chat_config=config, modifier_specs=[spec])
        modifier_row = keyboard.inline_keyboard[3]
        assert len(modifier_row) == 1
        assert modifier_row[0].callback_data == "modifier_run"

    def test_modifier_button_inactive_label(self):
        """Test modifier button shows inactive label when state is False."""
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        config = ChatConfig(chat_id=0, modifier_states={"run": False})
        with patch("src.keyboard.translation_manager") as mock_tm:
            mock_tm.get.return_value = "🚶"
            keyboard = create_input_keyboard(chat_config=config, modifier_specs=[spec])
            mock_tm.get.assert_any_call("keyboard.buttons.walking", 0)

    def test_modifier_button_active_label(self):
        """Test modifier button shows active label when state is True."""
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        config = ChatConfig(chat_id=0, modifier_states={"run": True})
        with patch("src.keyboard.translation_manager") as mock_tm:
            mock_tm.get.return_value = "🏃"
            keyboard = create_input_keyboard(chat_config=config, modifier_specs=[spec])
            mock_tm.get.assert_any_call("keyboard.buttons.running", 0)

    def test_base_button_order(self):
        """Test base buttons are in correct order."""
        keyboard = create_input_keyboard()
        assert keyboard.inline_keyboard[0][0].callback_data == "select"
        assert keyboard.inline_keyboard[0][1].callback_data == "up"
        assert keyboard.inline_keyboard[0][2].callback_data == "start"
        assert keyboard.inline_keyboard[1][0].callback_data == "left"
        assert keyboard.inline_keyboard[1][1].callback_data == "down"
        assert keyboard.inline_keyboard[1][2].callback_data == "right"
        assert keyboard.inline_keyboard[2][0].callback_data == "wait"
        assert keyboard.inline_keyboard[2][1].callback_data == "a"
        assert keyboard.inline_keyboard[2][2].callback_data == "b"

    def test_no_run_button_in_base_layout(self):
        """Test RUN button is no longer in base layout."""
        keyboard = create_input_keyboard()
        all_callbacks = [
            btn.callback_data
            for row in keyboard.inline_keyboard
            for btn in row
        ]
        assert "run" not in all_callbacks

    def test_chat_id_from_config(self):
        """Test that chat_id is taken from chat_config."""
        config = ChatConfig(chat_id=42)
        # Should not raise; chat_id used internally for translations
        keyboard = create_input_keyboard(chat_config=config)
        assert keyboard is not None

    def test_none_config_uses_defaults(self):
        """Test that None config uses chat_id=0 and empty modifier_states."""
        keyboard = create_input_keyboard(chat_config=None)
        assert keyboard is not None
        assert len(keyboard.inline_keyboard) == 3


class TestCreateGameMessageText:
    """Test game message text creation."""

    def test_basic_text(self):
        text = create_game_message_text()
        assert "Sua vez" in text

    def test_text_with_status(self):
        text = create_game_message_text("Processando: A...")
        assert "Processando: A..." in text
        assert "Sua vez" in text

    def test_markdown_formatting(self):
        text = create_game_message_text("Status")
        assert "Sua vez" in text
        assert "_Status_" in text


class TestCreateSaveSlotKeyboard:
    """Test save slot keyboard creation."""

    def test_correct_number_of_slots(self):
        keyboard = create_save_slot_keyboard(123456, save_slots=5)
        slot_buttons = sum(
            1
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data.startswith("load_slot_")
        )
        assert slot_buttons == 5

    def test_slot_button_format(self):
        keyboard = create_save_slot_keyboard(123456, save_slots=3)
        first_button = keyboard.inline_keyboard[0][0]
        assert "Slot 0" in first_button.text
        assert first_button.callback_data == "load_slot_0"

    def test_has_cancel_button(self):
        keyboard = create_save_slot_keyboard(123456)
        last_row = keyboard.inline_keyboard[-1]
        assert len(last_row) == 1
        assert last_row[0].callback_data == "cancel_load"
        assert "Cancel" in last_row[0].text


class TestGetButtonFromCallback:
    """Test callback data parsing."""

    def test_valid_button_callbacks(self):
        assert get_button_from_callback("up") == GameButton.UP
        assert get_button_from_callback("a") == GameButton.A
        assert get_button_from_callback("start") == GameButton.START

    def test_invalid_callback(self):
        assert get_button_from_callback("invalid") is None
        assert get_button_from_callback("") is None
        assert get_button_from_callback("modifier_run") is None


class TestIsValidButtonCallback:
    """Test callback validation."""

    def test_valid_callbacks(self):
        assert is_valid_button_callback("left") is True
        assert is_valid_button_callback("b") is True
        assert is_valid_button_callback("select") is True

    def test_invalid_callbacks(self):
        assert is_valid_button_callback("modifier_run") is False
        assert is_valid_button_callback("load") is False
        assert is_valid_button_callback("") is False


class TestCreateHelpText:
    """Test help text creation."""

    def test_contains_title(self):
        text = create_help_text(123456)
        assert "Como jogar" in text

    def test_contains_commands(self):
        text = create_help_text(123456)
        assert "/start_game" in text or "/start" in text
        assert "/help" in text
        assert "button_descriptions" not in text
```

**Step 2: Run to verify they fail**

```bash
poetry run pytest tests/test_keyboard.py -v
```
Expected: failures about wrong signature and `GameButton.RUN` still expected

**Step 3: Update `src/keyboard.py`**

Update imports at the top to add `ChatConfig` and `ModifierButtonSpec`:
```python
from src.models.game_state import BUTTON_LAYOUT, ChatConfig, GameButton, ModifierButtonSpec
```

Replace `create_input_keyboard()` with:

```python
def create_input_keyboard(
    chat_config: "ChatConfig | None" = None,
    modifier_specs: "list[ModifierButtonSpec] | None" = None,
) -> InlineKeyboardMarkup:
    """Create the inline keyboard for game input.

    Creates a 3-row base layout (D-pad, A/B, Start/Select) plus an optional
    modifier button row derived from the loaded game's modifier specs.

    Args:
        chat_config: Chat configuration providing chat_id and modifier_states.
            If None, uses chat_id=0 and empty modifier_states.
        modifier_specs: Game-specific modifier button specs. If provided and
            non-empty, appends one row of modifier toggle buttons.

    Returns:
        InlineKeyboardMarkup with game control buttons

    Example:
        >>> keyboard = create_input_keyboard()
        >>> isinstance(keyboard, InlineKeyboardMarkup)
        True
    """
    chat_id = chat_config.chat_id if chat_config else 0
    modifier_states = chat_config.modifier_states if chat_config else {}

    keyboard = []

    for row in BUTTON_LAYOUT:
        keyboard_row = [
            InlineKeyboardButton(button.emoji, callback_data=button.value)
            for button in row
        ]
        keyboard.append(keyboard_row)

    if modifier_specs:
        modifier_row = []
        for spec in modifier_specs:
            is_active = modifier_states.get(spec.key, False)
            label_key = spec.active_label_key if is_active else spec.inactive_label_key
            label = translation_manager.get(label_key, chat_id)
            modifier_row.append(
                InlineKeyboardButton(label, callback_data=f"modifier_{spec.key}")
            )
        keyboard.append(modifier_row)

    return InlineKeyboardMarkup(keyboard)
```

**Step 4: Fix `tests/integration/test_i18n.py`**

Find lines ~181-186 in `tests/integration/test_i18n.py`:
```python
keyboard_pt = create_input_keyboard(running_mode=True, chat_id=111)
...
keyboard_en = create_input_keyboard(running_mode=True, chat_id=222)
```

Replace with (the test only checks row count so this still works):
```python
from src.models.game_state import ChatConfig, ModifierButtonSpec
from src.game_modifier_buttons.pkpcrystal import MODIFIER_BUTTONS

config_pt = ChatConfig(chat_id=111, modifier_states={"run": True})
keyboard_pt = create_input_keyboard(chat_config=config_pt, modifier_specs=MODIFIER_BUTTONS)
...
config_en = ChatConfig(chat_id=222, modifier_states={"run": True})
keyboard_en = create_input_keyboard(chat_config=config_en, modifier_specs=MODIFIER_BUTTONS)
```

**Step 5: Run tests to verify they pass**

```bash
poetry run pytest tests/test_keyboard.py tests/integration/test_i18n.py -v
```
Expected: all PASS

**Step 6: Commit**

```bash
git add src/keyboard.py tests/test_keyboard.py tests/integration/test_i18n.py
git commit -m "feat: update keyboard to use chat_config and dynamic modifier specs"
```

---

### Task 7: Update `InputHandler`

**Files:**
- Modify: `src/handlers/input_handler.py`
- Modify: `tests/test_input_handler.py`
- Modify: `tests/test_migration_script.py`

**Step 1: Fix `tests/test_migration_script.py`**

The test at line 22 uses `running_mode=True` — update it:

```python
config = ChatConfig(chat_id=123, input_hold_frames=10, modifier_states={"run": True})
```

At line 38, replace `assert loaded.running_mode is True` with:
```python
assert loaded.modifier_states == {"run": True}
```

Run this test to verify it passes with the existing code:
```bash
poetry run pytest tests/test_migration_script.py -v
```

**Step 2: Update `src/handlers/input_handler.py`**

2a. **Update import** — add `ModifierButtonSpec` to the game_state import:
```python
from src.models.game_state import ChatGameState, GameButton, GameSession, ModifierButtonSpec
```

2b. **Update `handle_button_press()`** — insert modifier routing BEFORE the `is_valid_button_callback` check (around line 143). Replace:
```python
if not is_valid_button_callback(callback_data):
```
with:
```python
# Handle modifier button presses before GameButton validation
if callback_data.startswith("modifier_"):
    session = self._get_session(chat_id)
    if not session:
        try:
            await callback_query.answer(translation_manager.get("game.no_active_game", chat_id))
        except Exception as e:
            logger.error(f"Error processing modifier for chat {chat_id}: {e}")
        return
    if session.state.message_id != message_id:
        try:
            await callback_query.answer(translation_manager.get("game.message_outdated", chat_id))
        except Exception as e:
            logger.error(f"Error processing modifier for chat {chat_id}: {e}")
        return
    key = callback_data[len("modifier_"):]
    await self._handle_modifier_button_press(callback_query, chat_id, message_id, key)
    return

if not is_valid_button_callback(callback_data):
```

2c. **Remove the `if button == GameButton.RUN:` block** (lines ~175-178):
```python
# Handle RUN button specially
if button == GameButton.RUN:
    await self._handle_run_button_press(callback_query, session, chat_id, message_id)
    return
```
Delete these four lines entirely.

2d. **Replace `_handle_run_button_press()` with `_handle_modifier_button_press()`** (lines ~211-232). Remove the old method and add:

```python
async def _handle_modifier_button_press(
    self, callback_query, chat_id: int, message_id: int, key: str
) -> None:
    """Handle a modifier button press to toggle modifier state."""
    config = state_manager.get_or_create_chat_config(chat_id)
    config.modifier_states[key] = not config.modifier_states.get(key, False)
    state_manager.save_chat_config(config)

    controller = game_controller_manager.get_controller(chat_id)
    modifier_specs = controller.get_modifier_specs() if controller else []

    await self._edit_message_keyboard(
        chat_id, message_id, create_input_keyboard(chat_config=config, modifier_specs=modifier_specs)
    )

    spec = next((s for s in modifier_specs if s.key == key), None)
    if spec:
        is_active = config.modifier_states[key]
        label_key = spec.active_label_key if is_active else spec.inactive_label_key
        message = translation_manager.get(label_key, chat_id)
    else:
        message = ""
    try:
        await callback_query.answer(message, show_alert=False)
    except Exception as e:
        logger.error(f"Error answering modifier callback for chat {chat_id}: {e}")
```

2e. **Update `_process_queue_item()`** — around lines 343-372. Replace:
```python
# Check running mode
config = state_manager.get_or_create_chat_config(chat_id)
running_mode = config.running_mode if config else False

input_keyboard = create_input_keyboard(running_mode=running_mode, chat_id=chat_id)

logger.info(f"Executing sequence of {len(buttons)} buttons for chat {chat_id} (running_mode={running_mode})")
```
with:
```python
config = state_manager.get_or_create_chat_config(chat_id)
modifier_specs = controller.get_modifier_specs()
modifier_states = config.modifier_states if config else {}

input_keyboard = create_input_keyboard(chat_config=config, modifier_specs=modifier_specs)

logger.info(f"Executing sequence of {len(buttons)} buttons for chat {chat_id} (modifier_states={modifier_states})")
```

Remove the `directional_buttons` variable (line ~358):
```python
directional_buttons = (GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT)
```

Replace the button execution block (lines ~364-375):
```python
elif running_mode and button in directional_buttons:
    # Running mode: hold B throughout directional input
    logger.debug(f"Executing {button.value} with B in running mode for chat {chat_id}")
    controller.send_input_with_modifier(button, GameButton.B, frames=settings.input_hold_frames)
else:
    logger.debug(f"Executing {button.value} in sequence for chat {chat_id}")
    controller.send_input(button, frames=settings.input_hold_frames)
```
with:
```python
else:
    applied = False
    for spec in modifier_specs:
        if modifier_states.get(spec.key) and button in spec.applies_to:
            logger.debug(f"Executing {button.value} with {spec.modifier_button.value} modifier for chat {chat_id}")
            controller.send_input_with_modifier(button, spec.modifier_button, frames=settings.input_hold_frames)
            applied = True
            break
    if not applied:
        logger.debug(f"Executing {button.value} in sequence for chat {chat_id}")
        controller.send_input(button, frames=settings.input_hold_frames)
```

2f. **Update `start_game()` call site** (lines ~586-599). Replace:
```python
config = state_manager.get_or_create_chat_config(chat_id)
running_mode = config.running_mode if config else False
...
reply_markup=create_input_keyboard(running_mode=running_mode, chat_id=chat_id),
```
with:
```python
config = state_manager.get_or_create_chat_config(chat_id)
modifier_specs = controller.get_modifier_specs()
...
reply_markup=create_input_keyboard(chat_config=config, modifier_specs=modifier_specs),
```

2g. **Update `show_current_frame()` call sites** (lines ~629-663). Replace:
```python
config = state_manager.get_or_create_chat_config(chat_id)
running_mode = config.running_mode if config else False
```
with:
```python
config = state_manager.get_or_create_chat_config(chat_id)
controller_for_specs = game_controller_manager.get_controller(chat_id)
modifier_specs = controller_for_specs.get_modifier_specs() if controller_for_specs else []
```
Then replace all three `create_input_keyboard(running_mode=running_mode, chat_id=chat_id)` calls in that method with `create_input_keyboard(chat_config=config, modifier_specs=modifier_specs)`.

2h. **Update `resume_game()` call site** (lines ~695-719). Replace:
```python
config = state_manager.get_or_create_chat_config(chat_id)
running_mode = config.running_mode if config else False
...
reply_markup=create_input_keyboard(running_mode=running_mode, chat_id=chat_id),
```
with:
```python
config = state_manager.get_or_create_chat_config(chat_id)
controller_for_specs = game_controller_manager.get_controller(chat_id)
modifier_specs = controller_for_specs.get_modifier_specs() if controller_for_specs else []
...
reply_markup=create_input_keyboard(chat_config=config, modifier_specs=modifier_specs),
```

**Step 3: Run the full test suite**

```bash
poetry run pytest -v
```
Expected: all PASS

If there are failures in `tests/test_input_handler.py` related to `GameButton.RUN` or `running_mode`, update those tests to use `modifier_` callback data and `modifier_states` dict respectively.

**Step 4: Commit**

```bash
git add src/handlers/input_handler.py tests/test_input_handler.py tests/test_migration_script.py
git commit -m "feat: update InputHandler to use generic modifier button system"
```

---

### Task 8: Final verification

**Step 1: Run the full test suite**

```bash
poetry run pytest -v
```
Expected: all PASS, no references to `running_mode` or `GameButton.RUN` remaining

**Step 2: Grep for any remaining references**

```bash
grep -r "running_mode\|GameButton\.RUN\b" src/ tests/
```
Expected: no output (no remaining references)

**Step 3: Final commit if needed**

```bash
git add -A
git commit -m "chore: cleanup any remaining running_mode references"
```
