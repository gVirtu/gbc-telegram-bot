# Implicit Frame Capture via tick() — Design Spec

**Date:** 2026-03-12

## Context

The bot animates Telegram messages by capturing GameBoy frames and encoding them as MP4.
Currently, frames are sampled explicitly in `_process_batch()` using
`controller.get_frame().copy()` at specific points and at `capture_interval_frames`
intervals during tick loops.

The problem: `send_input()` and `send_input_with_modifier()` in `GameController` call
`self.pyboy.tick()` directly — bypassing the sampling logic in `InputHandler`. Frames
ticked during button execution are invisible to the animation sampler. This creates
inconsistent frame intervals that will cause audio/video desync when audio extraction is
added later.

**Goal:** Refactor so `GameController.tick()` is the single source of truth for frame
sampling. Every `capture_interval_frames` calls to `tick()` automatically append a frame
to an internal buffer, regardless of whether the tick came from `send_input()`, a sequence
delay, post-button animation, or anywhere else.

## Design

### GameController (`src/game.py`)

#### New instance fields (in `__init__`)

```python
self._capturing: bool = False
self._capture_interval: int = 1      # default 1 to avoid modulo-by-zero
self._capture_tick_count: int = 0
self._frame_buffer: list[np.ndarray] = []
```

#### Modified `tick(frames: int = 1)` (line 241)

Add per-tick capture logic inside the loop:

```python
for _ in range(frames):
    self.pyboy.tick()
    if self._capturing:
        self._capture_tick_count += 1
        if self._capture_tick_count % self._capture_interval == 0:
            self._frame_buffer.append(self.get_frame().copy())
```

#### Modified `send_input()` (lines 288–295)

Replace direct `self.pyboy.tick()` calls with `self.tick()`:
- Hold loop: `for _ in range(frames): self.pyboy.tick()` → `self.tick(frames)`
- Release tick: `self.pyboy.tick()` → `self.tick(1)`

#### Modified `send_input_with_modifier()` (lines 344–354)

Same replacements as `send_input()`.

#### New `begin_capture(capture_interval_frames: int) -> None`

Mirrors the existing `begin_hooks()` pattern:

```python
def begin_capture(self, capture_interval_frames: int) -> None:
    self._capturing = True
    self._capture_interval = capture_interval_frames
    self._capture_tick_count = 0
    self._frame_buffer = [self.get_frame().copy()]   # t=0 frame captured immediately
```

#### New `end_capture() -> list[np.ndarray]`

Mirrors `end_hooks()`. Advances the emulator to the next capture boundary (without
capturing it), then drains and returns the buffer:

```python
def end_capture(self) -> list[np.ndarray]:
    self._capturing = False
    remainder = self._capture_tick_count % self._capture_interval
    extra_ticks = (self._capture_interval - remainder) if remainder != 0 else self._capture_interval
    for _ in range(extra_ticks):
        self.pyboy.tick()          # direct — intentionally not captured
    frames = list(self._frame_buffer)
    self._frame_buffer = []
    self._capture_tick_count = 0
    return frames
```

**Alignment invariant:** after `end_capture()`, the emulator is exactly
`capture_interval_frames` ticks from the next batch's `begin_capture()` t=0 frame. The
gap between the last frame of batch N and the first frame of batch N+1 is always exactly
`capture_interval_frames` — seamless for future audio sync.

### InputHandler (`src/handlers/input_handler.py`)

#### `_process_batch()` (line 371)

- Remove `frames = []` local variable and all explicit `frames.append(controller.get_frame().copy())` calls.
- After `hook_context = controller.begin_hooks()`, add:
  ```python
  capture_interval_frames = game_fps // capture_fps
  controller.begin_capture(capture_interval_frames)
  ```
- Remove `capture_interval_frames` usage from all tick loops (the counter is inside
  `GameController` now).
- Sequence delay loop becomes a plain tick loop with only the break condition:
  ```python
  for frame_num in range(delay_frames):
      controller.tick(1)
  ```
- After the auto-press A loop, before `controller.end_hooks(hook_context)`, add:
  ```python
  frames = controller.end_capture()
  ```
- Remove `capture_interval_frames` variable (keep `game_fps` and `capture_fps` for the
  `begin_capture` call and `animation_duration_seconds` calculation).

#### `_tick_and_capture_animation_frames()` (line 136)

Remove `frames: list` and `capture_interval_frames: int` parameters. Remove the
`if frame_num % capture_interval_frames == 0: frames.append(...)` line. Only the
wait-loop-detection break condition remains:

```python
def _tick_and_capture_animation_frames(
    self,
    controller,
    animation_frames: int,
    hook_context: dict,
    game_fps: int,
) -> None:
    wait_call_threshold = hook_context.get("inputWaitCalls", {}).get("_total", 0) + game_fps
    for frame_num in range(animation_frames):
        controller.tick(1)
        if hook_context.get("inputWaitCalls", {}).get("_total", 0) > wait_call_threshold:
            ...
            break
```

Update the two call sites in `_process_batch()` accordingly.

## Testing

New tests in `tests/test_game.py`:

| Test | Assertion |
|------|-----------|
| `test_begin_capture_captures_t0` | After `begin_capture(4)` with no ticks, `_frame_buffer` has 1 entry |
| `test_tick_captures_at_interval` | After `begin_capture(4)` + 8 ticks, buffer has 3 entries (t=0, t=4, t=8) |
| `test_tick_no_capture_between_intervals` | After `begin_capture(4)` + 3 ticks, buffer has 1 entry |
| `test_end_capture_alignment_full_interval` | Tick 4 times, `end_capture()` runs 4 extra ticks; immediate `begin_capture` t=0 is 8 global ticks from batch start |
| `test_end_capture_alignment_partial` | Tick 6 times (count=6, remainder=2), `end_capture()` runs 2 extra ticks to reach count=8 |
| `test_end_capture_returns_and_clears` | `_frame_buffer` is empty after `end_capture()`, return value matches captured frames |
| `test_send_input_ticks_counted` | `begin_capture(4)` + `send_input(A, frames=10)` (11 ticks) → 2 captured frames (t=0, t=8) |
| `test_send_input_with_modifier_ticks_counted` | Same for modifier variant |

Existing `_process_batch()` integration tests should be reviewed for assertions on explicit
frame capture counts.

## Verification

```bash
# Run all tests
poetry run pytest

# Run game controller tests
poetry run pytest tests/test_game.py -v

# Run input handler tests
poetry run pytest tests/test_input_handler.py -v
```

Manual smoke test: start the bot, press a button, verify the animation is generated
correctly with no visual gaps or jumps.
