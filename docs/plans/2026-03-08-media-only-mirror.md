# media_only_mirror Feature Flag Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `media_only_mirror` feature flag that makes a mirror chat receive only on-demand commands (`/print`, `/gif`, `/recap`, `/status`) and never game frame broadcasts, text broadcasts, button inputs, or `/resume`.

**Architecture:** Add the flag name to `KNOWN_FEATURE_FLAGS`, add an `is_media_only_mirror(chat_id)` helper to `mirror_utils.py`, then call it at four enforcement sites: `broadcast_game_update`, `broadcast_text`, `resume_command`, and `handle_button_press`. No DB migration needed — the `feature_flags` JSON column already exists.

**Tech Stack:** Python 3.11, pytest, pytest-asyncio, unittest.mock

---

### Task 1: Add `media_only_mirror` to `KNOWN_FEATURE_FLAGS`

**Files:**
- Modify: `src/models/game_state.py:15`
- Test: `tests/test_feature_flags.py`

**Step 1: Write the failing test**

In `tests/test_feature_flags.py`, add to the `TestChatConfigFeatureFlags` class:

```python
def test_known_feature_flags_contains_media_only_mirror(self):
    assert "media_only_mirror" in KNOWN_FEATURE_FLAGS
```

**Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_feature_flags.py::TestChatConfigFeatureFlags::test_known_feature_flags_contains_media_only_mirror -v
```
Expected: FAIL with `AssertionError`

**Step 3: Add the flag**

In `src/models/game_state.py`, change line 15:

```python
KNOWN_FEATURE_FLAGS: frozenset[str] = frozenset({"update_group_avatar", "media_only_mirror"})
```

**Step 4: Run test to verify it passes**

```bash
poetry run pytest tests/test_feature_flags.py::TestChatConfigFeatureFlags::test_known_feature_flags_contains_media_only_mirror -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/models/game_state.py tests/test_feature_flags.py
git commit -m "feat: add media_only_mirror to KNOWN_FEATURE_FLAGS"
```

---

### Task 2: Add `is_media_only_mirror` helper to `mirror_utils.py`

**Files:**
- Modify: `src/utils/mirror_utils.py`
- Test: `tests/test_mirror_utils.py`

**Step 1: Write the failing tests**

In `tests/test_mirror_utils.py`, add a new test class after the existing imports. The import at the top already has `from src.utils.mirror_utils import broadcast_game_update, broadcast_text, get_leader_chat_id` — extend it to also import `is_media_only_mirror`:

```python
from src.utils.mirror_utils import broadcast_game_update, broadcast_text, get_leader_chat_id, is_media_only_mirror
```

Then add:

```python
class TestIsMediaOnlyMirror:
    def _make_config(self, chat_id, mirrors_chat_id=None, flag_value=None):
        flags = {}
        if flag_value is not None:
            flags["media_only_mirror"] = flag_value
        return ChatConfig(chat_id=chat_id, mirrors_chat_id=mirrors_chat_id, feature_flags=flags)

    def test_returns_false_for_leader_chat(self):
        config = self._make_config(10, mirrors_chat_id=None, flag_value=True)
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = config
            assert is_media_only_mirror(10) is False

    def test_returns_false_for_mirror_without_flag(self):
        config = self._make_config(20, mirrors_chat_id=10, flag_value=None)
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = config
            assert is_media_only_mirror(20) is False

    def test_returns_false_for_mirror_with_flag_disabled(self):
        config = self._make_config(20, mirrors_chat_id=10, flag_value=False)
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = config
            assert is_media_only_mirror(20) is False

    def test_returns_true_for_mirror_with_flag_enabled(self):
        config = self._make_config(20, mirrors_chat_id=10, flag_value=True)
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = config
            assert is_media_only_mirror(20) is True

    def test_returns_false_when_no_config(self):
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = None
            assert is_media_only_mirror(99) is False
```

**Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/test_mirror_utils.py::TestIsMediaOnlyMirror -v
```
Expected: FAIL with `ImportError` (function does not exist yet)

**Step 3: Implement the helper**

In `src/utils/mirror_utils.py`, add after the `get_leader_chat_id` function (around line 41):

```python
def is_media_only_mirror(chat_id: int) -> bool:
    """Return True if this chat is a mirror with media_only_mirror flag enabled.

    A media-only mirror never receives game frame broadcasts, text broadcasts,
    button inputs, or /resume. It may still use /print, /gif, /recap, /status.
    Has no effect on leader chats.

    Args:
        chat_id: The chat ID to check

    Returns:
        True if the chat is a mirror with media_only_mirror feature flag set
    """
    config = state_manager.load_chat_config(chat_id)
    if config is None:
        return False
    if config.mirrors_chat_id is None:
        return False
    return bool(config.feature_flags.get("media_only_mirror", False))
```

**Step 4: Run tests to verify they pass**

```bash
poetry run pytest tests/test_mirror_utils.py::TestIsMediaOnlyMirror -v
```
Expected: all 5 PASS

**Step 5: Commit**

```bash
git add src/utils/mirror_utils.py tests/test_mirror_utils.py
git commit -m "feat: add is_media_only_mirror helper to mirror_utils"
```

---

### Task 3: Skip media-only mirrors in `broadcast_game_update`

**Files:**
- Modify: `src/utils/mirror_utils.py`
- Test: `tests/test_mirror_utils.py`

**Step 1: Write the failing test**

In `tests/test_mirror_utils.py`, add to `TestBroadcastGameUpdate`:

```python
async def test_skips_media_only_mirror_in_broadcast_game_update(self):
    leader_id = 10
    mirror_id = 20
    mock_adapter = _make_mock_adapter()
    leader_state = ChatGameState(chat_id=leader_id, message_id=50)
    leader_config = ChatConfig(chat_id=leader_id, platform="telegram")
    mirror_config = ChatConfig(
        chat_id=mirror_id,
        platform="telegram",
        mirrors_chat_id=leader_id,
        feature_flags={"media_only_mirror": True},
    )
    fake_buffer = BytesIO(b"fake_video_data")

    with (
        patch("src.utils.mirror_utils.state_manager") as mock_sm,
        patch("src.utils.mirror_utils.get_adapter", return_value=mock_adapter),
        patch("src.utils.mirror_utils.game_controller_manager"),
        patch("src.utils.mirror_utils.save_frames_as_mp4", return_value=fake_buffer),
        patch("src.utils.mirror_utils.is_media_only_mirror", side_effect=lambda cid: cid == mirror_id),
    ):
        mock_sm.get_mirror_chat_ids.return_value = [mirror_id]
        mock_sm.get_or_create_chat_config.side_effect = lambda cid: (
            leader_config if cid == leader_id else mirror_config
        )
        mock_sm.load_game_state.return_value = leader_state

        await broadcast_game_update(leader_id, "caption", [], 15, [])

    # Only leader should receive the update
    assert mock_adapter.edit_game_message.call_count == 1
    assert mock_adapter.edit_game_message.call_args.args[0] == leader_id
```

**Step 2: Run test to verify it fails**

```bash
poetry run pytest "tests/test_mirror_utils.py::TestBroadcastGameUpdate::test_skips_media_only_mirror_in_broadcast_game_update" -v
```
Expected: FAIL (mirror still receives broadcast)

**Step 3: Add the skip in `broadcast_game_update`**

In `src/utils/mirror_utils.py`, inside `broadcast_game_update`, at the start of the `for target_id in all_targets:` loop, add the guard as the very first line of the loop body:

```python
    for target_id in all_targets:
        if target_id != leader_chat_id and is_media_only_mirror(target_id):
            logger.debug(f"Skipping media-only mirror {target_id} in broadcast_game_update")
            continue
        # ... existing code unchanged
```

**Step 4: Run test to verify it passes**

```bash
poetry run pytest tests/test_mirror_utils.py::TestBroadcastGameUpdate -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/utils/mirror_utils.py tests/test_mirror_utils.py
git commit -m "feat: skip media_only_mirror chats in broadcast_game_update"
```

---

### Task 4: Skip media-only mirrors in `broadcast_text`

**Files:**
- Modify: `src/utils/mirror_utils.py`
- Test: `tests/test_mirror_utils.py`

**Step 1: Write the failing test**

In `tests/test_mirror_utils.py`, add to `TestBroadcastText`:

```python
async def test_skips_media_only_mirror_in_broadcast_text(self):
    leader_id = 10
    mirror_id = 20
    mock_adapter = _make_mock_adapter()

    with (
        patch("src.utils.mirror_utils.state_manager") as mock_sm,
        patch("src.utils.mirror_utils.get_adapter", return_value=mock_adapter),
        patch("src.utils.mirror_utils.is_media_only_mirror", side_effect=lambda cid: cid == mirror_id),
    ):
        mock_sm.get_mirror_chat_ids.return_value = [mirror_id]
        mock_sm.get_or_create_chat_config.side_effect = lambda cid: ChatConfig(
            chat_id=cid, platform="telegram"
        )

        await broadcast_text(leader_id, "hello")

    # Only leader receives the text
    mock_adapter.send_text.assert_called_once_with(leader_id, "hello")
```

**Step 2: Run test to verify it fails**

```bash
poetry run pytest "tests/test_mirror_utils.py::TestBroadcastText::test_skips_media_only_mirror_in_broadcast_text" -v
```
Expected: FAIL (mirror still receives text)

**Step 3: Add the skip in `broadcast_text`**

In `src/utils/mirror_utils.py`, inside `broadcast_text`, at the start of the `for target_id in all_targets:` loop:

```python
    for target_id in all_targets:
        if target_id != leader_chat_id and is_media_only_mirror(target_id):
            logger.debug(f"Skipping media-only mirror {target_id} in broadcast_text")
            continue
        # ... existing code unchanged
```

**Step 4: Run test to verify it passes**

```bash
poetry run pytest tests/test_mirror_utils.py::TestBroadcastText -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/utils/mirror_utils.py tests/test_mirror_utils.py
git commit -m "feat: skip media_only_mirror chats in broadcast_text"
```

---

### Task 5: Silent no-op `/resume` for media-only mirrors

**Files:**
- Modify: `src/handlers/commands.py`
- Test: `tests/test_commands.py` (or a new `tests/test_media_only_mirror.py`)

**Step 1: Write the failing test**

Check `tests/test_commands.py` for existing `resume_command` tests to understand the fixture style, then add:

```python
@pytest.mark.asyncio
async def test_resume_command_noop_for_media_only_mirror(mock_adapter):
    """resume_command does nothing (no message) when called from a media-only mirror."""
    from src.handlers.commands import resume_command
    from src.adapters.base import CommandContext

    ctx = CommandContext(
        chat_id=20,
        user_id=1,
        user_name="User",
        args=[],
        adapter=mock_adapter,
        raw=None,
    )

    with patch("src.handlers.commands.is_media_only_mirror", return_value=True):
        await resume_command(ctx)

    mock_adapter.send_text.assert_not_called()
```

Add `from src.utils.mirror_utils import is_media_only_mirror` to the imports section if not already present (it is imported as `get_leader_chat_id, broadcast_text` — you'll need to add `is_media_only_mirror`).

**Step 2: Run test to verify it fails**

```bash
poetry run pytest tests/test_commands.py::test_resume_command_noop_for_media_only_mirror -v
```
Expected: FAIL (resume currently proceeds)

**Step 3: Import and guard in `resume_command`**

In `src/handlers/commands.py`, update the import on line 21:

```python
from src.utils.mirror_utils import broadcast_text, get_leader_chat_id, is_media_only_mirror
```

Then in `resume_command`, add the guard as the very first check after `chat_id = ctx.chat_id`:

```python
async def resume_command(ctx: CommandContext) -> None:
    chat_id = ctx.chat_id

    if is_media_only_mirror(chat_id):
        return

    leader_id = get_leader_chat_id(chat_id)
    # ... existing code unchanged
```

**Step 4: Run test to verify it passes**

```bash
poetry run pytest tests/test_commands.py -k "resume" -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/handlers/commands.py tests/test_commands.py
git commit -m "feat: silent no-op resume_command for media_only_mirror chats"
```

---

### Task 6: Silent no-op button inputs for media-only mirrors

**Files:**
- Modify: `src/handlers/input_handler.py`
- Test: `tests/test_input_handler_mirroring.py`

**Step 1: Write the failing test**

Open `tests/test_input_handler_mirroring.py` to understand the existing style, then add:

```python
@pytest.mark.asyncio
async def test_handle_button_press_noop_for_media_only_mirror():
    """handle_button_press silently ignores inputs from media-only mirror chats."""
    from src.handlers.input_handler import InputHandler

    handler = InputHandler()
    mock_adapter = MagicMock()
    mock_adapter.answer_interaction = AsyncMock()
    mock_adapter.send_text = AsyncMock()

    with patch("src.handlers.input_handler.is_media_only_mirror", return_value=True):
        await handler.handle_button_press(
            callback_data="a",
            chat_id=20,
            message_id=100,
            user_id=1,
            user_name="User",
            adapter=mock_adapter,
            raw=None,
        )

    mock_adapter.answer_interaction.assert_not_called()
    mock_adapter.send_text.assert_not_called()
```

**Step 2: Run test to verify it fails**

```bash
poetry run pytest "tests/test_input_handler_mirroring.py::test_handle_button_press_noop_for_media_only_mirror" -v
```
Expected: FAIL

**Step 3: Import and guard in `handle_button_press`**

In `src/handlers/input_handler.py`, update the import on line 28:

```python
from src.utils.mirror_utils import broadcast_game_update, get_leader_chat_id, is_media_only_mirror
```

Then at the very top of `handle_button_press` (line 181, before resolving the leader):

```python
    async def handle_button_press(self, ...) -> None:
        if is_media_only_mirror(chat_id):
            return

        # Resolve leader: buffer and processing are keyed to the leader chat
        leader_id = get_leader_chat_id(chat_id)
        # ... existing code unchanged
```

**Step 4: Run tests to verify they pass**

```bash
poetry run pytest tests/test_input_handler_mirroring.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/handlers/input_handler.py tests/test_input_handler_mirroring.py
git commit -m "feat: silent no-op handle_button_press for media_only_mirror chats"
```

---

### Task 7: Full test run

**Step 1: Run the entire test suite**

```bash
poetry run pytest -v
```
Expected: all tests PASS, no regressions

**Step 2: Commit if any fixups were needed**

If any test needed a small fixup, commit it:

```bash
git add -p
git commit -m "fix: test cleanup after media_only_mirror implementation"
```
