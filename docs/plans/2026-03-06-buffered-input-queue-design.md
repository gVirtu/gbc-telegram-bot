# Buffered Input Queue Design

**Date:** 2026-03-06

## Problem

With enough concurrent players, the bot hits Telegram's rate limits. The current queue drains immediately and produces one API call (animated message edit) per player input round — there is no batching across players and no minimum interval between edits.

## Goal

Reduce API call frequency while keeping gameplay feeling responsive: buffer incoming inputs for a short window, batch them together into a single animation, and enforce a minimum gap between message edits.

## Design Decisions

- **Execution order:** Strict FIFO across all players (no per-user grouping).
- **Buffer timer:** Starts immediately on first input; resets on each subsequent input. Drain fires when timer expires *or* total buffered buttons reaches `max_sequence_length`.
- **During active animation:** Timer runs concurrently. When animation + sleep ends, if timer already expired the next batch starts immediately; if not, we block until it fires.
- **Loop lifetime:** Exit on empty buffer, restart on next input (matches current pattern).
- **Buffer persistence:** In-memory only. Drop `input_queue_items` and `input_queue_buttons` DB tables.
- **`recent_inputs` persistence:** Consecutive inputs from the same user within a batch are collapsed into one sequence entry.
- **Sleep between rounds:** `max(animation_duration, min_update_interval_seconds)`.

---

## Data Model

### `BufferedInput` (replaces `QueueItem`)

```python
@dataclass
class BufferedInput:
    user_id: int
    user_name: str
    button: GameButton      # single button, not a list
    received_at: datetime
```

### `PendingBuffer` (replaces `InputQueue`)

```python
@dataclass
class PendingBuffer:
    items: list[BufferedInput]
    last_input_at: Optional[datetime]
    max_size: int  # from settings.max_queue_size

    def add(user_id, user_name, button) -> tuple[bool, tuple]
    def pop_batch(n: int) -> list[BufferedInput]  # FIFO, up to n
    def total_buttons() -> int
    def is_empty() -> bool
    def is_full() -> bool
```

No "mutable back" logic — every button press creates a new `BufferedInput` slot.

---

## New Configuration

| Setting | Env Var | Default | Description |
|---|---|---|---|
| `input_buffer_seconds` | `INPUT_BUFFER_SECONDS` | `1.5` | How long to wait after last input before draining |
| `maximum_inputs_per_animation` | `MAXIMUM_INPUTS_PER_ANIMATION` | `8` | Max buttons drained per animation round |
| `min_update_interval_seconds` | `MIN_UPDATE_INTERVAL_SECONDS` | `5.0` | Minimum seconds between message edits |

---

## InputHandler Changes

### New per-chat state

```python
_buffer_tasks: dict[int, asyncio.Task]   # running debounce timer per chat
_drain_events: dict[int, asyncio.Event]  # signals loop to drain
```

### `handle_button_press` flow

1. Append `BufferedInput` to `PendingBuffer`
2. If `buffer.total_buttons() >= settings.max_sequence_length`:
   - `drain_events[chat_id].set()` immediately
3. Else:
   - Cancel existing timer task (if any)
   - Create new: `asyncio.create_task(_run_buffer_timer(chat_id))`
4. If not processing: `asyncio.create_task(_process_queue_loop(...))`

### `_run_buffer_timer`

```python
async def _run_buffer_timer(self, chat_id: int) -> None:
    await asyncio.sleep(settings.input_buffer_seconds)
    self._drain_events[chat_id].set()
```

### `_process_queue_loop` (updated)

```python
while True:
    buffer = self._get_buffer(chat_id)
    if buffer.is_empty():
        break

    await self._drain_events[chat_id].wait()
    self._drain_events[chat_id].clear()

    buffer = self._get_buffer(chat_id)
    if buffer.is_empty():
        break

    batch = buffer.pop_batch(settings.maximum_inputs_per_animation)

    result = await self._process_batch(chat_id, message_id, batch, adapter)

    self._aggregate_to_recent_inputs(chat_id, batch)
    state_manager.save_game_state(session.state)

    wait_time = max(result["animation_duration"], settings.min_update_interval_seconds)
    await asyncio.sleep(wait_time)
```

### `_process_batch` (replaces `_process_queue_item`)

- Input: `list[BufferedInput]`
- Extracts buttons as flat FIFO list: `[bi.button for bi in batch]`
- Caption: groups consecutive same-user entries — e.g. `User A: ↑↓ | User B: A`
- Animation logic: unchanged (same frame capture + MP4/AVIF encoding)

### `_aggregate_to_recent_inputs`

Groups consecutive `BufferedInput` entries by same `user_id`, producing records like:
```python
{"user_id": ..., "user_name": ..., "buttons": ["up", "down"]}
```
Appends to `ChatGameState.recent_inputs` (capped at 3, FIFO).

---

## Database Changes

New migration: drop `input_queue_items` and `input_queue_buttons` tables.

Remove from `state_manager.py`:
- `_save_input_queue()`
- `_load_input_queue()`

Remove from `ChatGameState`:
- `input_queue: Optional[InputQueue]` field

---

## Files to Modify

| File | Change |
|---|---|
| `src/models/input_queue.py` | Rewrite: `BufferedInput` + `PendingBuffer` replacing `QueueItem` + `InputQueue` |
| `src/handlers/input_handler.py` | Timer tasks, drain events, new loop, `_process_batch`, `_aggregate_to_recent_inputs` |
| `src/config.py` | Add 3 new settings |
| `src/utils/state_manager.py` | Remove `_save_input_queue` / `_load_input_queue` |
| `src/models/game_state.py` | Remove `input_queue` field from `ChatGameState` |
| `src/db/migrations/` | New migration: drop queue tables |
| `tests/test_input_queue.py` | Rewrite for `PendingBuffer` / `BufferedInput` |
| `tests/test_input_handler.py` | Add timer-drain, multi-user batch, min_interval tests |
| `tests/test_config.py` | Add 3 new settings tests |

---

## Verification

1. **Unit tests:** `poetry run pytest tests/test_input_queue.py tests/test_input_handler.py tests/test_config.py`
2. **Full test suite:** `poetry run pytest`
3. **Manual test:** Start bot, send rapid button presses from two different users → verify:
   - Inputs from both users appear in the same animation
   - No animation starts until 1.5s after the last press (or max_sequence_length reached)
   - At least 5 seconds between message edits
   - `recent_inputs` correctly aggregates consecutive same-user presses
