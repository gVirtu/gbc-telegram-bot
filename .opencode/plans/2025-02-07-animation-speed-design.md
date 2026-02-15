# Plan: Remove Real-Time Waiting from Animation Generation

## Problem Statement

Currently, `_process_sequence()` in `input_handler.py` generates animation frames using `asyncio.sleep()` between captures. This means:
- A 5-second animation takes 5+ seconds of real server time to generate
- Multiple button sequences compound the delay
- User experience suffers from unnecessary waiting

## Current Implementation Issues

The current code (lines 422-451 in `input_handler.py`) has three phases with real-time delays:

1. **Button execution**: Holds button for `input_hold_frames` (no sleep here, good)
2. **Inter-button delay**: Sleeps for `sequence_delay_seconds` while ticking frames
3. **Animation phase**: Sleeps for `animation_duration` while capturing frames

Example timing for a 3-button sequence:
```
Current: button_hold(0.17s) + sleep(1s) + button_hold(0.17s) + sleep(1s) + button_hold(0.17s) + sleep(5s) = ~7.5 seconds
Optimized: Same frames generated at CPU max speed = ~0.1-0.5 seconds
```

## Proposed Solution

Convert all timing to frame counts and generate frames synchronously at maximum CPU speed.

### Frame Rate Assumptions

- GameBoy runs at **60 FPS** (standard)
- Capture rate remains **10 FPS** (every 6th frame)

### Phase Calculations

**1. Button Execution (per button):**
- Hold input for `settings.input_hold_frames` (default: 10 = ~0.17s)
- Capture 1 frame after execution

**2. Inter-Button Delay:**
- Convert `sequence_delay_seconds` to frames: `delay_frames = int(sequence_delay_seconds * 60)`
- Tick `delay_frames` frames
- Capture frames every 6 ticks (at 10 FPS capture rate)

**3. Post-Sequence Animation:**
- Convert `animation_duration` to frames: `animation_frames = animation_duration * 60`
- Tick `animation_frames` frames  
- Capture frames every 6 ticks (at 10 FPS capture rate)

### Implementation Changes

**File: `src/handlers/input_handler.py`**

The `_process_sequence()` method will be refactored:

1. **Remove all `asyncio.sleep()` calls** from frame generation loops
2. **Pre-calculate frame counts** for each phase based on settings
3. **Generate all frames synchronously** using nested loops:
   ```python
   # Example structure
   frames = []
   
   for button in buttons:
       # Execute button (synchronous)
       controller.send_input(button, frames=settings.input_hold_frames)
       frames.append(controller.get_frame().copy())
       
       # Inter-button delay (synchronous)
       if not last_button:
           delay_frames = int(settings.sequence_delay_seconds * 60)
           capture_interval = 6  # 60fps / 10fps
           for frame_num in range(delay_frames):
               controller.tick(1)
               if frame_num % capture_interval == 0:
                   frames.append(controller.get_frame().copy())
   
   # Animation phase (synchronous)
   animation_frames = settings.animation_duration * 60
   for frame_num in range(animation_frames):
       controller.tick(1)
       if frame_num % capture_interval == 0:
           frames.append(controller.get_frame().copy())
   ```
4. **Keep Telegram operations async** (message editing)

### Benefits

1. **Speed**: Animations generate in milliseconds instead of seconds
2. **Consistency**: Same visual output (same frame count, same FPS in MP4)
3. **Simplicity**: No complex timing logic, pure frame counting
4. **Predictability**: Frame generation time depends only on CPU, not real-time

### Testing Strategy

1. **Unit tests**: Verify frame count matches expected calculations
2. **Integration tests**: Ensure MP4 output is visually identical
3. **Performance tests**: Measure generation time improvement

### Settings Impact

No settings changes required. All existing timing configurations work as-is:
- `input_hold_frames`: Still controls button hold duration (in frames)
- `animation_duration`: Still controls animation length (converted to frames)
- `sequence_delay_seconds`: Still controls inter-button delay (converted to frames)

### Backwards Compatibility

The MP4 output will be identical to the current implementation:
- Same number of frames
- Same duration
- Same visual content
- Same file format

Only the generation speed changes.

## Files to Modify

1. **`src/handlers/input_handler.py`** - Refactor `_process_sequence()` method (lines 396-494)

## Implementation Notes

- Remove `capture_interval` and `capture_fps` variables (replaced by direct frame math)
- Keep `frames_per_tick = 6` logic but inline it
- All frame generation becomes synchronous (no `await`)
- Only `await` for Telegram API calls (`_edit_message_keyboard`, `_edit_message_media`)

## Success Criteria

1. A 5-second animation generates in under 1 second of server time
2. Visual output is identical to current implementation
3. All existing tests pass
4. No regression in game behavior or timing
