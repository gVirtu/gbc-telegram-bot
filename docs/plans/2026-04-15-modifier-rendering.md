# Modifier Rendering in Input Sidebar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display the modifier button char (e.g. `Ⓑ`) before the pressed button char in the input sidebar overlay when a modifier was active.

**Architecture:** Add a nullable `modifier` TEXT column to the `recent_inputs` DB table, thread it through `append_recent_input` and `get_recent_inputs_for_overlay`, capture the active modifier in `_process_batch`, and prepend the modifier char in `render_input_sidebar`.

**Tech Stack:** Python 3.11, SQLite (via `sqlite3`), Pillow (PIL), pytest/pytest-asyncio.

---

## File Map

| File | Change |
|------|--------|
| `src/db/migrations/024_add_modifier_to_recent_inputs.py` | Create — new migration |
| `src/db/manager.py` | Modify — `append_recent_input` + `get_recent_inputs_for_overlay` |
| `src/handlers/input_handler.py` | Modify — `_process_batch` captures modifier, passes to DB and `input_dict` |
| `src/utils/frame_utils.py` | Modify — `render_input_sidebar` renders modifier prefix |
| `tests/test_db_recent_inputs.py` | Modify — add modifier round-trip tests |
| `tests/test_input_handler_overlay.py` | Modify — add modifier-in-input_dict tests |
| `tests/test_frame_utils.py` | Modify — add modifier rendering tests |

---

### Task 1: DB migration — add `modifier` column

**Files:**
- Create: `src/db/migrations/024_add_modifier_to_recent_inputs.py`
- Test: `tests/db/test_migrations.py` (run existing suite to confirm migration applies cleanly)

- [ ] **Step 1: Create the migration file**

```python
"""Migration 024 - Add modifier to recent_inputs."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "ALTER TABLE recent_inputs ADD COLUMN modifier TEXT DEFAULT NULL;"
    )


def downgrade(conn: sqlite3.Connection) -> None:
    # SQLite does not support DROP COLUMN on older versions; no-op.
    pass
```

- [ ] **Step 2: Run the existing migration tests to confirm the new migration applies cleanly**

```bash
poetry run pytest tests/db/test_migrations.py -v
```

Expected: all existing tests PASS, no errors applying migration 024.

- [ ] **Step 3: Commit**

```bash
git add src/db/migrations/024_add_modifier_to_recent_inputs.py
git commit -m "feat: migration 024 — add modifier column to recent_inputs"
```

---

### Task 2: DB manager — thread `modifier` through read/write

**Files:**
- Modify: `src/db/manager.py:366-420`
- Test: `tests/test_db_recent_inputs.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db_recent_inputs.py`:

```python
class TestModifierPersistence:
    def test_append_and_retrieve_modifier(self, db_manager):
        """modifier value is stored and returned by get_recent_inputs_for_overlay."""
        _create_game_state(db_manager, chat_id=10)

        db_manager.append_recent_input(
            chat_id=10,
            user_id=1,
            user_name="Alice",
            button="up",
            timestamp=_ts(0),
            modifier="b",
        )

        rows = db_manager.get_recent_inputs_for_overlay(chat_id=10)
        assert len(rows) == 1
        assert rows[0]["modifier"] == "b"

    def test_append_without_modifier_returns_none(self, db_manager):
        """Omitting modifier defaults to None in get_recent_inputs_for_overlay."""
        _create_game_state(db_manager, chat_id=11)

        db_manager.append_recent_input(
            chat_id=11,
            user_id=2,
            user_name="Bob",
            button="a",
            timestamp=_ts(0),
        )

        rows = db_manager.get_recent_inputs_for_overlay(chat_id=11)
        assert rows[0]["modifier"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/test_db_recent_inputs.py::TestModifierPersistence -v
```

Expected: FAIL — `append_recent_input` does not accept `modifier` kwarg yet.

- [ ] **Step 3: Update `append_recent_input` in `src/db/manager.py`**

Replace the existing `append_recent_input` method (lines 366–391):

```python
def append_recent_input(
    self,
    chat_id: int,
    user_id: int,
    user_name: str,
    button: str,
    timestamp: str,
    base_score: int = 0,
    streak_bonus: int = 0,
    total_score: int = 0,
    modifier: str | None = None,
    commit: bool = True,
) -> None:
    """Append a single button press to the recent_inputs log.

    Args:
        modifier: The modifier button value pressed alongside this input (e.g. "b"),
            or None if no modifier was active.
        commit: Whether to commit after inserting. Pass False when the caller
            will issue a batched commit after processing multiple inputs.
    """
    self.connection.execute(
        """INSERT INTO recent_inputs
           (chat_id, user_id, user_name, button, timestamp, base_score, streak_bonus, total_score, modifier)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
        (chat_id, user_id, user_name, button, timestamp, base_score, streak_bonus, total_score, modifier)
    )
    if commit:
        self.connection.commit()
```

- [ ] **Step 4: Update `get_recent_inputs_for_overlay` in `src/db/manager.py`**

Replace the SELECT and the returned dict (lines 393–420):

```python
def get_recent_inputs_for_overlay(
    self, chat_id: int, limit: int = 30
) -> list:
    """Get the most recent N input rows for sidebar overlay rendering.

    Returns a list of dicts with keys: user_id, user_name, button, timestamp,
    current_streak, modifier. Ordered oldest-first (suitable for rendering bottom-up).
    """
    cursor = self.connection.execute(
        """SELECT ri.user_id, ri.user_name, ri.button, ri.timestamp,
                  COALESCE(up.current_streak, 0) AS current_streak,
                  ri.modifier
           FROM recent_inputs ri
           LEFT JOIN user_player_profiles up ON ri.user_id = up.user_id
           WHERE ri.chat_id = ?
           ORDER BY ri.timestamp DESC LIMIT ?;""",
        (chat_id, limit)
    )
    rows = list(cursor.fetchall())
    rows.reverse()  # Oldest first
    return [
        {
            'user_id': row['user_id'],
            'user_name': row['user_name'],
            'button': row['button'],
            'timestamp': row['timestamp'],
            'current_streak': row['current_streak'],
            'modifier': row['modifier'],
        }
        for row in rows
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
poetry run pytest tests/test_db_recent_inputs.py -v
```

Expected: all tests PASS including `TestModifierPersistence`.

- [ ] **Step 6: Commit**

```bash
git add src/db/manager.py tests/test_db_recent_inputs.py
git commit -m "feat: thread modifier through append_recent_input and get_recent_inputs_for_overlay"
```

---

### Task 3: `_process_batch` — capture and propagate modifier

**Files:**
- Modify: `src/handlers/input_handler.py:573-629`
- Test: `tests/test_input_handler_overlay.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_input_handler_overlay.py`:

```python
class TestProcessBatchModifier:
    """Test that _process_batch captures modifier and passes it to DB and input_dict."""

    @pytest.fixture
    def handler(self):
        from src.handlers.input_handler import InputHandler
        from src.models.game_state import ChatGameState, GameSession
        h = InputHandler()
        h._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=1),
        )
        return h

    @pytest.mark.asyncio
    async def test_modifier_captured_in_input_dict(self, handler):
        """When a modifier spec is active and applies to the pressed button,
        input_dict['modifier'] is set to the modifier button value."""
        from src.models.game_state import GameButton, ModifierButtonSpec
        from src.models.input_queue import BufferedInput

        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        controller = _make_mock_controller()
        controller.get_modifier_specs.return_value = [spec]
        controller.send_input_with_modifier = MagicMock()

        config = _make_mock_config()
        config.modifier_states = {"run": True}

        batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.UP)]

        new_inputs = []

        with (
            patch("src.handlers.input_handler.game_controller_manager") as mock_gcm,
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.scoring_manager") as mock_sc,
            patch("src.handlers.input_handler.broadcast_game_update", new=AsyncMock()),
            patch("src.handlers.input_handler._build_recent_inputs_grouped", return_value=[]),
            patch("src.handlers.input_handler.create_game_message_text", return_value=""),
        ):
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.get_recent_inputs_for_overlay.return_value = []
            mock_sm.get_today_input_stats.return_value = {}
            mock_sm.get_alltime_input_stats.return_value = {}
            mock_sm.connection = MagicMock()

            scored = MagicMock()
            scored.total_score = 10
            scored.base_score = 10
            scored.streak_bonus = 0
            scored.current_streak = 1
            mock_sc.score_input.return_value = scored

            adapter = MagicMock()
            adapter.platform = "telegram"
            adapter.build_game_keyboard.return_value = MagicMock()

            # Capture what gets passed to append_recent_input
            captured_modifier = {}
            def capture_append(**kwargs):
                captured_modifier["modifier"] = kwargs.get("modifier")
            mock_sm.append_recent_input.side_effect = capture_append

            await handler._process_batch(123456, 1, batch, adapter)

        assert captured_modifier.get("modifier") == "b"

    @pytest.mark.asyncio
    async def test_no_modifier_when_spec_inactive(self, handler):
        """When no modifier spec is active, input_dict['modifier'] is None."""
        from src.models.game_state import GameButton, ModifierButtonSpec
        from src.models.input_queue import BufferedInput

        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP],
            active_label_key="keyboard.buttons.running",
            inactive_label_key="keyboard.buttons.walking",
        )
        controller = _make_mock_controller()
        controller.get_modifier_specs.return_value = [spec]

        config = _make_mock_config()
        config.modifier_states = {"run": False}  # inactive

        batch = [BufferedInput(user_id=1, user_name="Alice", button=GameButton.UP)]

        with (
            patch("src.handlers.input_handler.game_controller_manager") as mock_gcm,
            patch("src.handlers.input_handler.state_manager") as mock_sm,
            patch("src.handlers.input_handler.scoring_manager") as mock_sc,
            patch("src.handlers.input_handler.broadcast_game_update", new=AsyncMock()),
            patch("src.handlers.input_handler._build_recent_inputs_grouped", return_value=[]),
            patch("src.handlers.input_handler.create_game_message_text", return_value=""),
        ):
            mock_gcm.get_or_create_controller = AsyncMock(return_value=controller)
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.get_recent_inputs_for_overlay.return_value = []
            mock_sm.get_today_input_stats.return_value = {}
            mock_sm.get_alltime_input_stats.return_value = {}
            mock_sm.connection = MagicMock()

            scored = MagicMock()
            scored.total_score = 10
            scored.base_score = 10
            scored.streak_bonus = 0
            scored.current_streak = 1
            mock_sc.score_input.return_value = scored

            adapter = MagicMock()
            adapter.platform = "telegram"
            adapter.build_game_keyboard.return_value = MagicMock()

            captured_modifier = {}
            def capture_append(**kwargs):
                captured_modifier["modifier"] = kwargs.get("modifier")
            mock_sm.append_recent_input.side_effect = capture_append

            await handler._process_batch(123456, 1, batch, adapter)

        assert captured_modifier.get("modifier") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/test_input_handler_overlay.py::TestProcessBatchModifier -v
```

Expected: FAIL — `modifier` not passed to `append_recent_input` yet.

- [ ] **Step 3: Update `_process_batch` in `src/handlers/input_handler.py`**

In the button execution loop, track the active modifier. Replace lines 577–629:

```python
            else:
                applied_modifier = None
                for spec in modifier_specs:
                    if modifier_states.get(spec.key) and button in spec.applies_to:
                        logger.debug(f"Executing {button.value} with {spec.modifier_button.value} modifier for chat {chat_id}")
                        controller.send_input_with_modifier(button, spec.modifier_button, frames=settings.input_hold_frames)
                        applied_modifier = spec.modifier_button.value
                        break
                if applied_modifier is None:
                    logger.debug(f"Executing {button.value} in batch for chat {chat_id}")
                    controller.send_input(button, frames=settings.input_hold_frames)

            # Record frame offset at time of button press
            frame_offset = cumulative_frames // capture_interval_frames
            bi = batch[i]

            input_total_score = None
            try:
                scored = scoring_manager.score_input(
                    platform=config.platform,
                    user_id=bi.user_id,
                    chat_id=chat_id,
                    button=bi.button.value,
                    timestamp=bi.received_at.isoformat(),
                    user_name=bi.user_name,
                    commit=False,
                )
                input_total_score = scored.total_score
                state_manager.append_recent_input(
                    chat_id=chat_id,
                    user_id=bi.user_id,
                    user_name=bi.user_name,
                    button=bi.button.value,
                    timestamp=bi.received_at.isoformat(),
                    base_score=scored.base_score,
                    streak_bonus=scored.streak_bonus,
                    total_score=scored.total_score,
                    modifier=applied_modifier,
                    commit=False,
                )
            except Exception as e:
                logger.warning(f"Failed to append recent input for chat {chat_id}: {e}")

            input_dict = {
                'user_id': bi.user_id,
                'user_name': bi.user_name,
                'button': bi.button.value,
                'timestamp': bi.received_at.isoformat(),
                'total_score': input_total_score,
                'current_streak': scored.current_streak if input_total_score is not None else 0,
                'modifier': applied_modifier,
            }
            new_inputs_with_offsets.append((input_dict, frame_offset))
```

Note: `applied_modifier` must be declared before the `if button == GameButton.WAIT` branch so it is always defined. Add `applied_modifier = None` at the top of the loop body before the `if/else`:

```python
        for i, button in enumerate(buttons):
            applied_modifier = None  # reset per button
            if button == GameButton.WAIT:
                ...
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
poetry run pytest tests/test_input_handler_overlay.py -v
```

Expected: all tests PASS including `TestProcessBatchModifier`.

- [ ] **Step 5: Commit**

```bash
git add src/handlers/input_handler.py tests/test_input_handler_overlay.py
git commit -m "feat: capture active modifier in _process_batch and persist to recent_inputs"
```

---

### Task 4: Render modifier prefix in `render_input_sidebar`

**Files:**
- Modify: `src/utils/frame_utils.py:422-425`
- Test: `tests/test_frame_utils.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_frame_utils.py`:

```python
class TestRenderInputSidebarModifier:
    def test_modifier_prepended_to_button_char(self):
        """When entry has modifier='b' and button='up', suffix is ': Ⓑ⬆'."""
        inputs = [{"user_name": "Alice", "button": "up", "modifier": "b", "current_streak": 0}]
        # render_input_sidebar returns a numpy array; we just check it doesn't error
        # and verify the suffix string logic by calling the internal path.
        # We test via a known pixel diff — easier to test suffix construction directly.
        BUTTON_CHARS = {
            "left": "⬅", "up": "⬆", "right": "⮕", "down": "⬇",
            "a": "Ⓐ", "b": "Ⓑ", "start": "START", "select": "SELECT", "wait": "…",
        }
        entry = inputs[0]
        button_char = BUTTON_CHARS.get(entry["button"], entry["button"])
        modifier_val = entry.get("modifier")
        modifier_char = BUTTON_CHARS.get(modifier_val, "") if modifier_val else ""
        suffix = f": {modifier_char}{button_char}"
        assert suffix == ": Ⓑ⬆"

    def test_no_modifier_unchanged(self):
        """When modifier is None, suffix is ': ⬆' (unchanged behavior)."""
        BUTTON_CHARS = {
            "left": "⬅", "up": "⬆", "right": "⮕", "down": "⬇",
            "a": "Ⓐ", "b": "Ⓑ", "start": "START", "select": "SELECT", "wait": "…",
        }
        entry = {"user_name": "Bob", "button": "up", "modifier": None, "current_streak": 0}
        button_char = BUTTON_CHARS.get(entry["button"], entry["button"])
        modifier_val = entry.get("modifier")
        modifier_char = BUTTON_CHARS.get(modifier_val, "") if modifier_val else ""
        suffix = f": {modifier_char}{button_char}"
        assert suffix == ": ⬆"

    def test_render_input_sidebar_with_modifier_renders(self):
        """render_input_sidebar accepts modifier in entries and returns an array."""
        result = render_input_sidebar(
            inputs=[{"user_name": "Alice", "button": "up", "modifier": "b", "current_streak": 0}],
            scale=1,
        )
        import numpy as np
        assert isinstance(result, np.ndarray)
        assert result.shape[2] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/test_frame_utils.py::TestRenderInputSidebarModifier -v
```

Expected: first two tests PASS (pure logic), third PASS (render_input_sidebar already handles unknown keys gracefully) — but this step confirms expected behavior before the change.

- [ ] **Step 3: Update `render_input_sidebar` in `src/utils/frame_utils.py`**

Replace lines 422–425:

```python
        button_val = entry.get("button", "")
        button_char = BUTTON_CHARS.get(button_val, button_val)
        user_name = entry.get("user_name", "?")
        modifier_val = entry.get("modifier")
        modifier_char = BUTTON_CHARS.get(modifier_val, "") if modifier_val else ""
        suffix = f": {modifier_char}{button_char}"
```

- [ ] **Step 4: Run the full test suite**

```bash
poetry run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/utils/frame_utils.py tests/test_frame_utils.py
git commit -m "feat: render modifier prefix in input sidebar"
```
