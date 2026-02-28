# Game Modifier Buttons — Design

**Date:** 2026-02-28

## Problem

`GameButton.RUN` and `running_mode` in `ChatConfig` are game-specific concepts
(Polished Crystal only) hardcoded into shared infrastructure. They do not
generalize to other ROMs and clutter the models, keyboard builder, and input
handler with special-cased logic.

## Goal

Replace the hardcoded run/walk toggle with a generic `game_modifier_buttons`
plugin layer, parallel to `game_hooks`. Each game module declares the modifier
buttons it needs. The rest of the system handles them generically.

---

## Design

### 1. `ModifierButtonSpec` Dataclass

Added to `src/models/game_state.py` alongside existing models.

```python
@dataclass
class ModifierButtonSpec:
    key: str                    # unique identifier, e.g. "run"
    modifier_button: GameButton # button held during input, e.g. GameButton.B
    applies_to: list[GameButton] # inputs that get the modifier, e.g. directionals
    active_label_key: str       # i18n key when modifier is ON
    inactive_label_key: str     # i18n key when modifier is OFF
```

### 2. `game_modifier_buttons/` Directory

```
src/game_modifier_buttons/
    __init__.py       # docstring mirroring game_hooks/__init__.py
    pkpcrystal.py     # exports MODIFIER_BUTTONS: list[ModifierButtonSpec]
```

`pkpcrystal.py` defines:

```python
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

### 3. `GameController` (`src/game.py`)

At `initialize()`, after loading `_hook_module`:

```python
self._modifier_module = self._load_modifier_module(self.pyboy.cartridge_title)
```

`_load_modifier_module()` is structurally identical to `_load_hook_module()`,
looking up `src.game_modifier_buttons.{cartridge_title.lower()}`.

New public method:

```python
def get_modifier_specs(self) -> list[ModifierButtonSpec]:
    if self._modifier_module:
        return self._modifier_module.MODIFIER_BUTTONS
    return []
```

### 4. `ChatConfig` — Replace `running_mode` with `modifier_states`

`src/models/game_state.py`:
- Remove `running_mode: bool = False`
- Add `modifier_states: dict[str, bool] = field(default_factory=dict)`
- Update `to_dict()` / `from_dict()` accordingly

### 5. Database Migration (`007_replace_running_mode_with_modifier_states.py`)

1. Add `modifier_states TEXT NOT NULL DEFAULT '{}'` column to `chat_configs`
2. Migrate existing data: set `modifier_states = '{"run": true}'` where `running_mode = 1`
3. Drop `running_mode` column

`DatabaseManager.save_chat_config` / `load_chat_config` updated to
serialize/deserialize `modifier_states` as JSON.

### 6. `keyboard.py`

`GameButton.RUN` removed from `BUTTON_LAYOUT` (last row deleted).

`create_input_keyboard()` new signature:

```python
def create_input_keyboard(
    chat_config: ChatConfig | None = None,
    modifier_specs: list[ModifierButtonSpec] = [],
) -> InlineKeyboardMarkup:
```

- `chat_id` → `chat_config.chat_id` (fallback: `0`)
- `modifier_states` → `chat_config.modifier_states` (fallback: `{}`)
- Base rows from `BUTTON_LAYOUT` (no `RUN`)
- If `modifier_specs` non-empty, append one row: each button uses
  `callback_data=f"modifier_{spec.key}"` and label resolved from
  `active_label_key` / `inactive_label_key` via `translation_manager`

### 7. `InputHandler` (`src/handlers/input_handler.py`)

**Routing** in `handle_button_press()`: before parsing a `GameButton`, check
`callback_data.startswith("modifier_")`. If so, extract the key and dispatch
to `_handle_modifier_button_press(key, ...)`.

**`_handle_modifier_button_press(key, chat_id, message_id, callback_query)`**:
- Loads config, toggles `config.modifier_states[key]`, saves config
- Rebuilds keyboard with updated state and edits the message

Replaces `_handle_run_button_press()`.

**Queue processing** (around line 369): replace the `running_mode` + directional
check with a generic loop over modifier specs:

```python
for spec in modifier_specs:
    if modifier_states.get(spec.key) and button in spec.applies_to:
        controller.send_input_with_modifier(button, spec.modifier_button, ...)
        break
else:
    controller.send_input(button, ...)
```

### 8. `GameButton` Cleanup

- Remove `RUN = "run"` from the enum
- Remove from `emoji_map`
- Remove from `BUTTON_LAYOUT`

---

## What Does NOT Change

- `game_hooks` loading mechanism — `game_modifier_buttons` mirrors it exactly
- All other `ChatConfig` fields
- `InputHandler` queue logic beyond the modifier application
- Translation keys `keyboard.buttons.running` / `keyboard.buttons.walking`
  (still used, now referenced from the spec)
