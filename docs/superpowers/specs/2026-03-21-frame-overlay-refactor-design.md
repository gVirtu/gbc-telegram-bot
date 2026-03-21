# Frame Overlay Refactor Design

**Date:** 2026-03-21
**Status:** Approved

## Overview

Move the frame overlay (date + input sidebar) from a lazy `frame_transform` applied during timelapse encoding to an eager composite applied in `_process_batch` — so the overlay appears in both incremental game messages (mp4/avif) and the recap timelapse.

## Goals

- Overlay shows in every animated game message sent to Telegram/Discord
- Timelapse encoder receives pre-composited frames (no overlay logic there)
- TBC frames show up in game messages with overlay, but are stripped before recap (existing behaviour preserved)
- 2x scaling and overlay compositing happen exactly once, in one place

## Data Flow

### Before

```
controller.end_capture() → raw frames (144×160)
  ├─→ broadcast_game_update
  │     └─→ save_frames_as_mp4/avif  [scales 2x internally]
  └─→ timelapse_queue (raw frames + overlay metadata)
        └─→ _do_encode_and_append   [scales 2x]
              └─→ save_frames_as_mp4_optimized  [frame_transform: composites overlay]
```

### After

```
controller.end_capture() → raw frames (144×160)
  └─→ scale 2x → scaled frames (288×320)
        └─→ generate_tbc_frames(scaled_frames[-1]) → tbc_frames (288×320)
              └─→ all_frames = scaled_frames + tbc_frames
                    └─→ apply_overlay_composite() → composited frames (288×512)
                          ├─→ broadcast_game_update
                          │     └─→ save_frames_as_mp4/avif  [no internal scaling]
                          └─→ timelapse_queue (composited frames, TBC stripped)
                                └─→ _do_encode_and_append  [no pre-scaling, no frame_transform]
                                      └─→ save_frames_as_mp4_optimized
```

**Sidebar dimensions**: game frames are 144px tall → 288px after 2x scale. `render_input_sidebar` defaults to `height=288`, so heights match exactly — `composite_overlay` performs no padding.

**`frame_to_png` is not in this path.** The fallback at `input_handler.py:628` calls `controller.get_frame_as_png()` which operates on a fresh raw frame from the controller, not on the batch frames. Its internal 2x scale is unaffected and correct.

## Component Changes

### `src/utils/frame_utils.py`

1. **Move `make_frame_transform` here** from `timelapse_encoder.py`, renamed to `_make_frame_transform` (module-private). It is only called internally by `apply_overlay_composite`; no external callers should use it directly.

2. **Add `apply_overlay_composite(frames, pre_existing_inputs, new_inputs_with_offsets) -> list[np.ndarray]`**
   - Accepts already-2x-scaled frames (no internal scaling)
   - Calls `make_frame_transform(pre_existing_inputs, new_inputs_with_offsets)` to build the stateful transform
   - Applies it to each frame using the existing `render_input_sidebar` + `composite_overlay` functions
   - Returns composited frames (288×512)

3. **`save_frames_as_mp4`** — remove the internal 2x scale. Concretely: remove the `h_scaled, w_scaled = h * 2, w * 2` lines, change the FFmpeg `-s` argument from `f'{w_scaled}x{h_scaled}'` to `f'{w}x{h}'` (read directly from `frames[0].shape`), and remove the `Image.fromarray(frame).resize(...)` call inside the frame-writing loop (write raw frame bytes directly).

4. **`save_frames_as_avif`** — same: remove the 2x resize in the list comprehension. Frames are already at their final dimensions. Update the docstring which currently advertises "Scales 2x (same as save_frames_as_mp4)".

5. **`save_frames_as_mp4_optimized`** — remove the `frame_transform` parameter from the signature. Collapse the dimension-probe block:
   ```python
   # Before:
   if frame_transform:
       first_frame = frame_transform(frames[0])
   else:
       first_frame = frames[0]
   # After:
   first_frame = frames[0]
   ```
   The subsequent `h, w = first_frame.shape[:2]` then reads the pre-composited dimensions (288×512) correctly.

6. **`save_frames_as_mp4_with_audio`** — same: remove the `frame_transform` parameter and collapse the identical dimension-probe block.

### `src/handlers/input_handler.py` — `_process_batch`

Replace the current frame post-processing block with:

```python
# 1. Scale raw frames 2x
scaled_frames = [
    np.array(Image.fromarray(f).resize((f.shape[1]*2, f.shape[0]*2), Image.Resampling.NEAREST))
    for f in frames
]

# 2. TBC on the last 2x game frame (overlay not yet applied)
tbc_frames = generate_tbc_frames(
    scaled_frames[-1] if scaled_frames else controller.get_frame(),
    overlay_path=settings.tbc_overlay_path,
    duration_frames=settings.tbc_duration_frames,
    max_width_percent=0.7,
)
num_tbc_frames = len(tbc_frames)  # may be 0 if TBC asset is missing
all_frames = scaled_frames + tbc_frames

# 3. Composite overlay on all frames (game + TBC)
composited_frames = apply_overlay_composite(
    all_frames, pre_existing_inputs_for_overlay, new_inputs_with_offsets
)
```

- `broadcast_game_update` receives `composited_frames` (game + TBC, both with overlay).
- Timelapse enqueue receives `composited_frames[:-num_tbc_frames] if num_tbc_frames > 0 else composited_frames` (TBC stripped using the actual count, replacing the old `len(frames) > settings.tbc_duration_frames` guard which could silently include TBC frames when the asset is missing).
- `pre_existing_inputs` and `new_inputs_with_offsets` are **no longer passed** to `timelapse_queue.enqueue`.

### `src/tasks/timelapse_encoder.py`

- **`_do_encode_and_append`**: remove the explicit 2x pre-scaling loop (frames arrive pre-scaled and composited at 288×512). Remove `frame_transform` from the calls to the four private helper methods below.
- **`_create_new_timelapse`**, **`_append_frames`**, **`_create_new_realtime_timelapse`**, **`_append_realtime_frames`**: remove the `frame_transform` parameter from each method signature and from the calls they pass it to (`save_frames_as_mp4_optimized` / `save_frames_as_mp4_with_audio`).
- **Remove `frame_transform`** parameter from `save_frames_as_mp4_optimized` and `save_frames_as_mp4_with_audio` function signatures in `frame_utils.py` (dead code once no caller passes it).
- **`TimelapseJob`**: drop `pre_existing_inputs` and `new_inputs_with_offsets` fields.
- **`TimelapseEncodingQueue.enqueue`**: drop those parameters.
- **`make_frame_transform`**: delete from this file (moved to `frame_utils.py` as `_make_frame_transform`).
- **Clean up unused imports**: `Callable` from `typing` (no longer needed after `frame_transform` params removed) and `PIL.Image` (only used in the removed 2x scaling loop in `_do_encode_and_append`) become unused and should be removed.

### `src/utils/mirror_utils.py`

No changes needed. `broadcast_game_update` passes frames through to the encode functions unchanged; it will now receive pre-composited frames instead of raw frames.

## TBC Frame Behaviour

| Step | Frame state |
|------|------------|
| After `end_capture` | Raw 144×160 |
| After 2x scale | 288×320 |
| After `generate_tbc_frames` | TBC frames: 288×320, no overlay |
| After `apply_overlay_composite` | All frames: 288×512 with sidebar |
| Sent to Telegram/Discord | Game + TBC, both have overlay |
| Sent to timelapse encoder | Game only (TBC stripped using `num_tbc_frames`), overlay applied |

During TBC frames, no new inputs arrive — the sidebar displays the same accumulated inputs as the final game frame.

**Edge case**: if `generate_tbc_frames` returns an empty list (e.g. TBC asset file missing), `num_tbc_frames = 0` and the full composited frame list is sent to both broadcast and timelapse.

## Testing

- Tests for `save_frames_as_mp4` / `save_frames_as_avif` must be updated to pass already-sized frames (remove expectation of 2x output scaling from raw input).
- Tests for `save_frames_as_mp4_optimized` and `save_frames_as_mp4_with_audio` must be updated to reflect `frame_transform` parameter removal.
- New unit tests for `apply_overlay_composite`: verify output dimensions (288×512) and that sidebar is applied at each frame.
- Timelapse encoder tests must be updated: remove `pre_existing_inputs` / `new_inputs_with_offsets` from `TimelapseJob` fixtures and `enqueue` calls.
- Verify `generate_tbc_frames` still positions correctly when given a 288×320 base frame (it uses `base_frame.shape` — no code change needed, just verify in tests).
