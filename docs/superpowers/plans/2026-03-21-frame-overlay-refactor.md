# Frame Overlay Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move frame overlay compositing (date + input sidebar) from the timelapse encoder into `_process_batch`, so it appears in every game message animation as well as the recap.

**Architecture:** After `controller.end_capture()`, frames are scaled 2x, TBC frames are appended to the scaled frames, then `apply_overlay_composite` (new function) applies the sidebar to all frames. The resulting composited frames flow to both `broadcast_game_update` and the timelapse queue unchanged. The timelapse encoder loses all overlay/transform machinery and simply encodes what it receives.

**Tech Stack:** Python 3.11, numpy, Pillow, FFmpeg, pytest, pytest-asyncio

---

## File Map

| File | Change |
|------|--------|
| `src/utils/frame_utils.py` | Add `_make_frame_transform` + `apply_overlay_composite`; remove 2x scale from `save_frames_as_mp4`, `save_frames_as_avif`; remove `frame_transform` param from `save_frames_as_mp4_optimized`, `save_frames_as_mp4_with_audio` |
| `src/handlers/input_handler.py` | `_process_batch`: add 2x scale → TBC → `apply_overlay_composite`; update timelapse enqueue call |
| `src/tasks/timelapse_encoder.py` | Delete `make_frame_transform`; remove `frame_transform` from 4 private helpers + their callers; remove pre-scaling loop from `_do_encode_and_append`; drop `pre_existing_inputs`/`new_inputs_with_offsets` from `TimelapseJob` + `enqueue`; clean up unused imports |
| `tests/test_frame_utils.py` | Update `TestSaveFramesAsMp4` + `TestSaveFramesAsGif` to pass pre-scaled frames |
| `tests/test_frame_utils_overlay.py` | Add `TestApplyOverlayComposite` class |
| `tests/test_timelapse_encoder_overlay.py` | Remove field tests for dropped `TimelapseJob` fields; update `make_frame_transform` tests to use `apply_overlay_composite` from `frame_utils` |
| `tests/test_input_handler_overlay.py` | Replace enqueue-overlay-params tests with tests that verify composited frames go to broadcast and timelapse receives no overlay params |

---

## Task 1: Add `apply_overlay_composite` + `_make_frame_transform` to `frame_utils.py`

**Files:**
- Modify: `src/utils/frame_utils.py`
- Modify: `tests/test_frame_utils_overlay.py`

- [ ] **Step 1: Write failing tests for `apply_overlay_composite`**

Append to `tests/test_frame_utils_overlay.py`:

```python
class TestApplyOverlayComposite:
    def test_output_length_matches_input(self):
        """Returns same number of frames as input."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(5)]
        result = apply_overlay_composite(frames, [], [])
        assert len(result) == 5

    def test_output_shape_is_composited(self):
        """Each output frame has sidebar width added (288×320 → 288×512)."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(3)]
        result = apply_overlay_composite(frames, [], [])
        for f in result:
            assert f.shape == (288, 512, 3)

    def test_sidebar_empty_before_offset(self):
        """Sidebar area is all-black on frames before an input's offset."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(3)]
        new_input = {
            "user_name": "Alice", "button": "a",
            "user_id": 1, "timestamp": "2026-01-01T00:00:00",
        }
        result = apply_overlay_composite(frames, [], [(new_input, 2)])

        # Before offset: sidebar (columns 320+) below date row should be black
        assert not np.any(result[0][24:, 320:, :] > 10)
        assert not np.any(result[1][24:, 320:, :] > 10)

    def test_sidebar_has_text_at_and_after_offset(self):
        """Sidebar area has white pixels on the frame where input arrives."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(3)]
        new_input = {
            "user_name": "Alice", "button": "a",
            "user_id": 1, "timestamp": "2026-01-01T00:00:00",
        }
        result = apply_overlay_composite(frames, [], [(new_input, 2)])
        assert np.any(result[2][24:, 320:, :] > 10)

    def test_pre_existing_inputs_visible_from_frame_0(self):
        """Pre-existing inputs appear in the sidebar from frame 0."""
        from src.utils.frame_utils import apply_overlay_composite
        frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(2)]
        pre = [{"user_name": "Bob", "button": "b", "user_id": 2, "timestamp": "2026-01-01T00:00:00"}]
        result = apply_overlay_composite(frames, pre, [])
        # Frame 0 sidebar should already have text
        assert np.any(result[0][24:, 320:, :] > 10)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
poetry run pytest tests/test_frame_utils_overlay.py::TestApplyOverlayComposite -v
```
Expected: `ImportError` or `AttributeError` — `apply_overlay_composite` does not exist yet.

- [ ] **Step 3: Add `_make_frame_transform` and `apply_overlay_composite` to `frame_utils.py`**

Add after the `composite_overlay` function (around line 244), before `save_frames_as_mp4`:

```python
def _make_frame_transform(
    pre_existing: list,
    new_inputs_with_offsets: list,
) -> Callable[[np.ndarray], np.ndarray]:
    """Build a stateful per-frame transform that composites the input sidebar.

    Returns a callable that, when called once per frame in sequence, composites
    an input sidebar reflecting accumulated inputs up to that frame.

    Args:
        pre_existing: Input dicts already visible at frame 0.
        new_inputs_with_offsets: List of (input_dict, frame_offset) pairs.

    Returns:
        A callable ``transform(frame) -> composited_frame``.
    """
    state: dict = {"frame_index": 0, "current_inputs": list(pre_existing)}
    sorted_new = sorted(new_inputs_with_offsets, key=lambda x: x[1])
    sorted_new_iter = iter(sorted_new)
    next_new: list = [next(sorted_new_iter, None)]

    def transform(frame: np.ndarray) -> np.ndarray:
        fi = state["frame_index"]
        state["frame_index"] += 1

        while next_new[0] is not None and next_new[0][1] <= fi:
            state["current_inputs"].append(next_new[0][0])
            next_new[0] = next(sorted_new_iter, None)

        sidebar = render_input_sidebar(state["current_inputs"])
        return composite_overlay(frame, sidebar)

    return transform


def apply_overlay_composite(
    frames: list[np.ndarray],
    pre_existing_inputs: list,
    new_inputs_with_offsets: list,
) -> list[np.ndarray]:
    """Composite the input sidebar onto a sequence of already-2x-scaled frames.

    Applies a stateful per-frame transform that adds new inputs to the sidebar
    at the specified frame offsets.

    Args:
        frames: List of 2x-scaled numpy arrays (H, W, 3). Must be pre-scaled;
            no internal scaling is applied.
        pre_existing_inputs: Input dicts visible from frame 0.
        new_inputs_with_offsets: List of (input_dict, frame_offset) pairs.

    Returns:
        List of composited frames, each wider by the sidebar width (H, W+192, 3).
    """
    transform = _make_frame_transform(pre_existing_inputs, new_inputs_with_offsets)
    return [transform(f) for f in frames]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
poetry run pytest tests/test_frame_utils_overlay.py::TestApplyOverlayComposite -v
```
Expected: All 5 tests PASS.

- [ ] **Step 5: Run the full test suite to verify no regressions**

```bash
poetry run pytest tests/test_frame_utils_overlay.py -v
```
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/utils/frame_utils.py tests/test_frame_utils_overlay.py
git commit -m "feat: add apply_overlay_composite and _make_frame_transform to frame_utils"
```

---

## Task 2: Remove internal 2x scaling from `save_frames_as_mp4` and `save_frames_as_avif`

**Files:**
- Modify: `src/utils/frame_utils.py`
- Modify: `tests/test_frame_utils.py`

These functions currently receive raw 144×160 frames and scale 2x internally. After this task they encode at whatever dimensions they receive.

- [ ] **Step 1: Update `TestSaveFramesAsMp4` tests to pass pre-scaled frames**

In `tests/test_frame_utils.py`, update the `TestSaveFramesAsMp4` class:

```python
class TestSaveFramesAsMp4:
    """Test MP4 encoding functionality."""

    def test_mp4_output_valid(self):
        """Test that MP4 output is valid."""
        # Pass pre-scaled 288×320 frames (callers are responsible for scaling)
        frames = [create_empty_frame(width=320, height=288, color=(i * 50, 0, 0)) for i in range(5)]

        mp4_buffer = save_frames_as_mp4(frames, fps=10)

        mp4_buffer.seek(0)
        header = mp4_buffer.read(12)
        assert header[4:8] == b'ftyp'

    def test_mp4_empty_frames_raises(self):
        """Test that empty frames raises ValueError."""
        with pytest.raises(ValueError, match="No frames provided"):
            save_frames_as_mp4([])

    def test_mp4_different_fps(self):
        """Test MP4 encoding with different frame rates."""
        frames = [create_empty_frame(width=320, height=288) for _ in range(3)]

        for fps in [5, 10, 15, 30]:
            mp4_buffer = save_frames_as_mp4(frames, fps=fps)
            assert len(mp4_buffer.getvalue()) > 0

    def test_mp4_encodes_at_received_dimensions(self):
        """Frames are encoded at their received size — no internal upscaling."""
        # Pass already-scaled 288×320 frames; function must NOT double them
        frames = [create_empty_frame(width=320, height=288) for _ in range(3)]

        mp4_buffer = save_frames_as_mp4(frames, fps=10)

        assert len(mp4_buffer.getvalue()) > 0
        mp4_buffer.seek(4)
        assert mp4_buffer.read(4) == b'ftyp'

    def test_mp4_crf_settings(self):
        """Test different CRF quality settings."""
        frames = [create_empty_frame(width=320, height=288) for _ in range(3)]

        for crf in [18, 23, 28, 35]:
            mp4_buffer = save_frames_as_mp4(frames, crf=crf)
            assert len(mp4_buffer.getvalue()) > 0

    def test_mp4_preset_settings(self):
        """Test different preset settings."""
        frames = [create_empty_frame(width=320, height=288) for _ in range(3)]

        for preset in ["ultrafast", "fast", "medium"]:
            mp4_buffer = save_frames_as_mp4(frames, preset=preset)
            assert len(mp4_buffer.getvalue()) > 0
```

Also update the `TestSaveFramesAsGif` (AVIF) tests to pass pre-scaled frames:

```python
class TestSaveFramesAsGif:
    """Test AVIF encoding functionality."""

    def test_gif_magic_bytes(self):
        frames = [create_empty_frame(width=320, height=288, color=(i * 80, 0, 0)) for i in range(3)]
        gif_buffer = save_frames_as_avif(frames, fps=10)
        gif_buffer.seek(4)
        header = gif_buffer.read(8)
        assert header == b"ftypavis"

    def test_gif_non_empty_output(self):
        frames = [create_empty_frame(width=320, height=288) for _ in range(3)]
        gif_buffer = save_frames_as_avif(frames, fps=10)
        assert len(gif_buffer.getvalue()) > 0

    def test_gif_empty_frames_raises(self):
        with pytest.raises(ValueError, match="No frames provided"):
            save_frames_as_avif([])

    def test_gif_buffer_seeked_to_zero(self):
        frames = [create_empty_frame(width=320, height=288) for _ in range(2)]
        gif_buffer = save_frames_as_avif(frames, fps=10)
        assert gif_buffer.tell() == 0

    def test_gif_black_pixels_not_transparent(self):
        """Regression: black pixels must not render as transparent in multi-frame AVIF."""
        black = create_empty_frame(width=320, height=288, color=(0, 0, 0))
        white = create_empty_frame(width=320, height=288, color=(255, 255, 255))
        frames = [black, white, black]

        gif_buffer = save_frames_as_avif(frames, fps=10)
        gif_buffer.seek(0)
        gif = Image.open(gif_buffer)

        for frame_idx in range(3):
            gif.seek(frame_idx)
            rgba = gif.convert("RGBA")
            pixels = np.array(rgba)
            if frame_idx % 2 == 0:
                assert np.all(pixels[:, :, 3] == 255), (
                    f"Frame {frame_idx}: black pixels have unexpected transparency"
                )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
poetry run pytest tests/test_frame_utils.py::TestSaveFramesAsMp4 tests/test_frame_utils.py::TestSaveFramesAsGif -v
```
Expected: `test_mp4_encodes_at_received_dimensions` may pass (the file is valid MP4), but `test_mp4_upscaling` is gone. The AVIF tests with 320×288 frames should still produce valid output. At this point the tests should pass since we're just changing the input frames — the scaling tests that previously checked for upscaling are removed.

Actually — verify at this point that the **old** `test_mp4_upscaling` test is completely replaced by `test_mp4_encodes_at_received_dimensions` (the old one no longer exists in the file). Confirm no test refers to the old test name.

- [ ] **Step 3: Remove the 2x scale from `save_frames_as_mp4`**

In `src/utils/frame_utils.py`, replace the body of `save_frames_as_mp4` starting at line 277:

```python
def save_frames_as_mp4(
    frames: list[np.ndarray],
    fps: int = 10,
    crf: int = 28,
    preset: str = "ultrafast",
) -> BytesIO:
    """Save a sequence of frames as an MP4 video using FFmpeg rawvideo piping.

    Encodes frames at their received dimensions — no internal scaling is applied.
    Callers are responsible for scaling frames before passing them.

    Args:
        frames: List of NumPy arrays (H, W, 3) in RGB format, already at final size
        fps: Frames per second for the output video
        crf: Constant Rate Factor (quality, lower=better, 0-51)
        preset: Encoding speed preset (ultrafast to veryslow)

    Returns:
        BytesIO object containing MP4 data

    Raises:
        ValueError: If no frames provided
        RuntimeError: If FFmpeg encoding fails
    """
    if not frames:
        raise ValueError("No frames provided")

    h, w = frames[0].shape[:2]

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_out:
        output_path = tmp_out.name

    try:
        cmd = [
            'ffmpeg', '-y',
            '-an',
            '-f', 'rawvideo',
            '-pix_fmt', 'rgb24',
            '-s', f'{w}x{h}',
            '-framerate', str(fps),
            '-i', 'pipe:0',
            '-vcodec', 'libx264',
            '-profile:v', 'baseline',
            '-pix_fmt', 'yuv420p',
            '-crf', str(crf),
            '-preset', preset,
            '-movflags', '+faststart+frag_keyframe+empty_moov',
            output_path,
        ]

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        for frame in frames:
            process.stdin.write(np.array(frame).tobytes())

        process.stdin.close()
        process.wait()
        return_code = process.returncode

        if return_code != 0:
            stderr = process.stderr.read().decode() if process.stderr else ""
            logger.error(f"FFmpeg encoding failed: {stderr}")
            raise RuntimeError(f"FFmpeg encoding failed with return code {return_code}")

        with open(output_path, 'rb') as f:
            buffer = BytesIO(f.read())

        buffer.seek(0)
        return buffer

    finally:
        if os.path.exists(output_path):
            os.remove(output_path)
```

- [ ] **Step 4: Remove the 2x scale from `save_frames_as_avif`**

Replace `save_frames_as_avif` with:

```python
def save_frames_as_avif(
    frames: list[np.ndarray],
    fps: int = 10,
) -> BytesIO:
    """Save frames as an animated AVIF using Pillow.

    Encodes frames at their received dimensions — no internal scaling is applied.
    Callers are responsible for scaling frames before passing them.

    Args:
        frames: List of NumPy arrays (H, W, 3) in RGB format, already at final size
        fps: Frames per second (converted to ms duration per frame)

    Returns:
        BytesIO object containing AVIF data, seeked to 0

    Raises:
        ValueError: If no frames provided
    """
    if not frames:
        raise ValueError("No frames provided")

    duration_ms = int(1000 / fps)

    pil_frames = [Image.fromarray(frame) for frame in frames]

    buffer = BytesIO()
    pil_frames[0].save(
        buffer,
        format="AVIF",
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )
    buffer.seek(0)
    return buffer
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest tests/test_frame_utils.py -v
```
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/utils/frame_utils.py tests/test_frame_utils.py
git commit -m "refactor: remove internal 2x scaling from save_frames_as_mp4 and save_frames_as_avif"
```

---

## Task 3: Remove `frame_transform` from `save_frames_as_mp4_optimized` and `save_frames_as_mp4_with_audio`

**Files:**
- Modify: `src/utils/frame_utils.py`

These functions expose `frame_transform` only for the timelapse encoder, which will no longer use it after Task 5. Removing it now keeps the changes atomic per file.

- [ ] **Step 1: Search for any tests using `frame_transform` with these functions**

```bash
poetry run grep -r "frame_transform" tests/ --include="*.py" -l
```

If any test passes `frame_transform` to `save_frames_as_mp4_optimized` or `save_frames_as_mp4_with_audio`, update those tests to remove the parameter before proceeding. (Tests in `test_timelapse_encoder.py` that mock these functions should not be affected.)

- [ ] **Step 2: Update `save_frames_as_mp4_optimized` — remove `frame_transform` param and collapse dimension probe**

Replace the signature and dimension-probe block. The key changes:
- Remove `frame_transform: Optional[Callable[[np.ndarray], np.ndarray]] = None` from the signature
- Replace the `if frame_transform: first_frame = frame_transform(frames[0]) else: first_frame = frames[0]` block with `first_frame = frames[0]`
- Replace the frame-writing loop that called `frame_transform` with a direct write

```python
async def save_frames_as_mp4_optimized(
    frames: list[np.ndarray],
    output_path: str,
    fps: int = 10,
    crf: int = 28,
    preset: str = "medium",
) -> None:
    """Save a sequence of frames as an MP4 video with optimized compression.

    Designed for timelapse storage. Encodes frames at their received dimensions.
    Callers are responsible for any pre-processing (scaling, overlay).

    Args:
        frames: List of NumPy arrays (H, W, 3) in RGB format, already at final size
        output_path: Path where to save the MP4 file
        fps: Frames per second for the output video
        crf: Constant Rate Factor (quality, lower=better, 0-51)
        preset: Encoding speed preset (medium for balanced compression)

    Raises:
        ValueError: If no frames provided
        RuntimeError: If FFmpeg encoding fails
    """
    import asyncio

    if not frames:
        raise ValueError("No frames provided")

    first_frame = frames[0]
    h, w = first_frame.shape[:2]

    cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo',
        '-pix_fmt', 'rgb24',
        '-s', f'{w}x{h}',
        '-framerate', str(fps),
        '-i', 'pipe:0',
        '-vcodec', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-crf', str(crf),
        '-preset', preset,
        output_path,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    for frame in frames:
        img = Image.fromarray(frame)
        process.stdin.write(np.array(img).tobytes())

    process.stdin.close()

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        logger.error(f"FFmpeg encoding failed: {stderr.decode()}")
        raise RuntimeError(f"FFmpeg encoding failed with return code {process.returncode}")

    logger.debug(f"Encoded {len(frames)} frames to {output_path}")
```

- [ ] **Step 3: Update `save_frames_as_mp4_with_audio` — remove `frame_transform` param and collapse dimension probe**

Same changes: remove `frame_transform` parameter, replace `if frame_transform` block with `first_frame = frames[0]`, and simplify the frame-writing loop to write `frame` directly instead of calling `frame_transform(f)`.

The frame-writing loops change from:
```python
frames_to_encode = [first_frame] + [
    frame_transform(f) if frame_transform else f for f in frames[1:]
]
for actual_frame in frames_to_encode:
    img = Image.fromarray(actual_frame)
    process.stdin.write(np.array(img).tobytes())
```
to:
```python
for frame in frames:
    img = Image.fromarray(frame)
    process.stdin.write(np.array(img).tobytes())
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest tests/test_frame_utils.py tests/test_timelapse_encoder.py -v
```
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/utils/frame_utils.py
git commit -m "refactor: remove frame_transform from save_frames_as_mp4_optimized and save_frames_as_mp4_with_audio"
```

---

## Task 4: Update `input_handler.py` — centralize 2x scale, TBC, and overlay composite

**Files:**
- Modify: `src/handlers/input_handler.py`
- Modify: `tests/test_input_handler_overlay.py`

This is where the overlay moves earlier. The frame pipeline in `_process_batch` gains three steps after `end_capture`: scale → TBC → composite.

- [ ] **Step 1: Update `tests/test_input_handler_overlay.py` to match new behaviour**

The two existing tests (`test_process_batch_tracks_frame_offsets` and `test_process_batch_passes_pre_existing_inputs`) check that `timelapse_queue.enqueue` receives overlay params. After this change, those params are gone from the enqueue call. Replace those two test classes with new ones that check the correct new behaviour.

Replace `TestProcessBatchTracksFrameOffsets` with:

```python
class TestProcessBatchCallsApplyOverlayComposite:
    """Test that _process_batch calls apply_overlay_composite with the correct args."""

    @pytest.fixture
    def handler(self):
        h = InputHandler()
        h._sessions[123456] = GameSession(
            chat_id=123456,
            state=ChatGameState(chat_id=123456, message_id=789),
        )
        return h

    @pytest.mark.asyncio
    async def test_apply_overlay_composite_called_with_pre_existing(
        self, handler, mock_adapter
    ):
        """apply_overlay_composite is called with the pre_existing_inputs from the DB."""
        pre_existing = [
            {"user_id": 99, "user_name": "Old", "button": "up", "timestamp": "2026-01-01T00:00:00"},
        ]
        batch = _make_batch([(GameButton.A, 1, "Alice")])

        mock_controller = _make_mock_controller()
        mock_config = _make_mock_config()

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.apply_overlay_composite", return_value=[]) as mock_composite, \
             patch("src.handlers.input_handler.settings") as mock_settings:

            mock_settings.input_hold_frames = 10
            mock_settings.animation_duration = 0
            mock_settings.sequence_delay_seconds = 0.0
            mock_settings.tbc_duration_frames = 0
            mock_settings.tbc_overlay_path = MagicMock()
            mock_settings.timelapse_frame_skip = 1
            mock_settings.max_queue_size = 50

            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_sm.get_recent_inputs_for_overlay.return_value = pre_existing
            mock_sm.append_recent_input.return_value = None

            await handler._process_batch(123456, 789, batch, mock_adapter)

            mock_composite.assert_called_once()
            call_args = mock_composite.call_args
            assert call_args[0][1] == pre_existing  # second positional arg


    @pytest.mark.asyncio
    async def test_timelapse_enqueue_receives_no_overlay_params(
        self, handler, mock_adapter
    ):
        """timelapse_queue.enqueue is called without pre_existing_inputs or new_inputs_with_offsets."""
        batch = _make_batch([(GameButton.A, 1, "Alice")])
        mock_controller = _make_mock_controller()
        mock_config = _make_mock_config(feature_flags={"realtime_recaps": True})
        mock_enqueue = AsyncMock()
        mock_tq = MagicMock()
        mock_tq.enqueue = mock_enqueue

        with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr, \
             patch("src.handlers.input_handler.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
             patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
             patch("src.handlers.input_handler.apply_overlay_composite", return_value=[MagicMock()]), \
             patch("src.handlers.input_handler.settings") as mock_settings, \
             patch("src.tasks.timelapse_encoder.timelapse_queue", mock_tq):

            mock_settings.input_hold_frames = 10
            mock_settings.animation_duration = 0
            mock_settings.sequence_delay_seconds = 0.0
            mock_settings.tbc_duration_frames = 0
            mock_settings.tbc_overlay_path = MagicMock()
            mock_settings.timelapse_frame_skip = 1
            mock_settings.max_queue_size = 50

            mock_mgr.get_or_create_controller = AsyncMock(return_value=mock_controller)
            mock_sm.get_or_create_chat_config.return_value = mock_config
            mock_sm.get_recent_inputs_for_overlay.return_value = []
            mock_sm.append_recent_input.return_value = None

            await handler._process_batch(123456, 789, batch, mock_adapter)

            mock_enqueue.assert_called_once()
            call_kwargs = mock_enqueue.call_args.kwargs
            assert "pre_existing_inputs" not in call_kwargs
            assert "new_inputs_with_offsets" not in call_kwargs
```

Replace `TestProcessBatchPassesPreExistingInputs` with the class above (it is now covered). Keep `TestProcessBatchAppendsRecentInput` and `TestProcessBatchPreExistingCappedAt30` unchanged — they remain correct.

- [ ] **Step 2: Run tests to confirm new tests fail (old behaviour)**

```bash
poetry run pytest tests/test_input_handler_overlay.py::TestProcessBatchCallsApplyOverlayComposite -v
```
Expected: FAIL — `apply_overlay_composite` is not yet imported/called in `input_handler.py`.

- [ ] **Step 3: Update `input_handler.py` imports**

At the top of `src/handlers/input_handler.py`, update the `frame_utils` import and add PIL/numpy:

```python
import numpy as np
from PIL import Image
```

```python
from src.utils.frame_utils import (  # noqa: F401 (needed for test patching)
    apply_overlay_composite,
    generate_tbc_frames,
)
```

- [ ] **Step 4: Replace the frame-processing block in `_process_batch`**

Locate the block starting at `frames = controller.end_capture()` (around line 548) through to the `broadcast_game_update` call (around line 584). Replace:

```python
        frames = controller.end_capture()
        audio_chunks = controller.get_last_captured_audio()
        controller.end_hooks(hook_context)

        if hook_context.get("dangerousActions", {}).get("_total", 0) > 0:
            logger.info(f"Dangerous action ({str(hook_context.get('dangerousActions', {}))}) blocked for chat {chat_id}")
            controller.load_state(checkpoint)
            error_msg = translation_manager.get("game.safe_mode_blocked", chat_id)
            await self._send_error_message(chat_id, error_msg, adapter)
            return {"animation_duration": None}

        animation_duration_seconds = len(frames) / capture_fps

        # 1. Scale raw frames 2x
        scaled_frames = [
            np.array(Image.fromarray(f).resize(
                (f.shape[1] * 2, f.shape[0] * 2), Image.Resampling.NEAREST
            ))
            for f in frames
        ]

        # 2. Generate TBC from the last 2x-scaled game frame (no overlay yet)
        tbc_frames = generate_tbc_frames(
            scaled_frames[-1] if scaled_frames else controller.get_frame(),
            overlay_path=settings.tbc_overlay_path,
            duration_frames=settings.tbc_duration_frames,
            max_width_percent=0.7,
        )
        num_tbc_frames = len(tbc_frames)
        all_frames = scaled_frames + tbc_frames

        # 3. Composite overlay onto all frames (game + TBC share same final overlay state)
        composited_frames = apply_overlay_composite(
            all_frames, pre_existing_inputs_for_overlay, new_inputs_with_offsets
        )
```

- [ ] **Step 5: Update the `broadcast_game_update` call**

Change:
```python
await broadcast_game_update(
    chat_id, caption, frames, capture_fps, modifier_specs
)
```
to:
```python
await broadcast_game_update(
    chat_id, caption, composited_frames, capture_fps, modifier_specs
)
```

- [ ] **Step 6: Update the timelapse enqueue block**

Replace:
```python
frames_without_tbc = frames[:-settings.tbc_duration_frames] if len(frames) > settings.tbc_duration_frames else frames
if config.feature_flags.get("realtime_recaps"):
    timelapse_frames = frames_without_tbc  # all frames, no skip
    timelapse_audio = audio_chunks or None
    timelapse_fps = 15
else:
    timelapse_frames = frames_without_tbc[::settings.timelapse_frame_skip]
    timelapse_audio = None
    timelapse_fps = 10
timestamp = datetime.now().isoformat()
await timelapse_queue.enqueue(
    chat_id,
    timelapse_frames,
    timestamp,
    audio_chunks=timelapse_audio,
    fps=timelapse_fps,
    pre_existing_inputs=pre_existing_inputs_for_overlay,
    new_inputs_with_offsets=new_inputs_with_offsets,
)
```
with:
```python
frames_for_timelapse = (
    composited_frames[:-num_tbc_frames] if num_tbc_frames > 0 else composited_frames
)
if config.feature_flags.get("realtime_recaps"):
    timelapse_frames = frames_for_timelapse
    timelapse_audio = audio_chunks or None
    timelapse_fps = 15
else:
    timelapse_frames = frames_for_timelapse[::settings.timelapse_frame_skip]
    timelapse_audio = None
    timelapse_fps = 10
timestamp = datetime.now().isoformat()
await timelapse_queue.enqueue(
    chat_id,
    timelapse_frames,
    timestamp,
    audio_chunks=timelapse_audio,
    fps=timelapse_fps,
)
```

- [ ] **Step 7: Run the updated overlay tests**

```bash
poetry run pytest tests/test_input_handler_overlay.py -v
```
Expected: All tests PASS.

- [ ] **Step 8: Patch `apply_overlay_composite` in the two existing test classes that don't mock it**

`TestProcessBatchAppendsRecentInput` and `TestProcessBatchPreExistingCappedAt30` in `test_input_handler_overlay.py` use a mock controller whose `end_capture()` returns `[MagicMock()]`. After Task 4, `_process_batch` will call `apply_overlay_composite` on those mock frames, which will crash trying to call `Image.fromarray` on a `MagicMock`.

Add `patch("src.handlers.input_handler.apply_overlay_composite", return_value=[])` to the `with patch(...)` block in each test in both classes. Example (same pattern for both):

```python
with patch("src.handlers.input_handler.game_controller_manager") as mock_mgr, \
     patch("src.handlers.input_handler.state_manager") as mock_sm, \
     patch("src.handlers.input_handler.broadcast_game_update", new_callable=AsyncMock), \
     patch("src.handlers.input_handler.generate_tbc_frames", return_value=[]), \
     patch("src.handlers.input_handler.apply_overlay_composite", return_value=[]), \
     patch("src.handlers.input_handler.settings") as mock_settings:
```

- [ ] **Step 9: Run the broader input handler test suite**

```bash
poetry run pytest tests/test_input_handler.py tests/test_input_handler_overlay.py tests/test_input_handler_coverage.py -v
```
Expected: All tests PASS.

- [ ] **Step 10: Commit**

```bash
git add src/handlers/input_handler.py tests/test_input_handler_overlay.py
git commit -m "feat: apply frame overlay in _process_batch before broadcasting"
```

---

## Task 5: Remove overlay machinery from `timelapse_encoder.py`

**Files:**
- Modify: `src/tasks/timelapse_encoder.py`
- Modify: `tests/test_timelapse_encoder_overlay.py`

The encoder now receives pre-composited frames. All transform machinery, pre-scaling, and overlay job fields are removed.

- [ ] **Step 1: Update `tests/test_timelapse_encoder_overlay.py`**

Replace the entire file content with:

```python
"""Tests for timelapse encoder after overlay refactor.

The encoder no longer owns overlay logic. Frames arrive pre-composited.
"""

import os
import pytest
import numpy as np

os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

from src.tasks.timelapse_encoder import TimelapseJob, TimelapseEncodingQueue, TimelapseEncoder


def test_timelapse_job_has_no_overlay_fields():
    """TimelapseJob no longer has pre_existing_inputs or new_inputs_with_offsets."""
    frames = [np.zeros((288, 512, 3), dtype=np.uint8)]
    job = TimelapseJob(
        chat_id=1,
        frames=frames,
        timestamp="2026-03-21T12:00:00",
    )
    assert not hasattr(job, "pre_existing_inputs")
    assert not hasattr(job, "new_inputs_with_offsets")


@pytest.mark.asyncio
async def test_enqueue_does_not_accept_overlay_params():
    """enqueue() no longer accepts pre_existing_inputs or new_inputs_with_offsets."""
    from unittest.mock import MagicMock
    import asyncio

    db_manager = MagicMock()
    queue = TimelapseEncodingQueue(db_manager)
    frames = [np.zeros((288, 512, 3), dtype=np.uint8)]

    # Should raise TypeError if the removed params are passed
    with pytest.raises(TypeError):
        await queue.enqueue(
            chat_id=42,
            frames=frames,
            timestamp="2026-03-21T12:00:00",
            pre_existing_inputs=[],
        )

    # Cancel any started worker
    for worker in queue._workers.values():
        worker.cancel()
    await asyncio.gather(*queue._workers.values(), return_exceptions=True)


def test_video_path_uses_recap_prefix(tmp_path, monkeypatch):
    """_get_video_path returns path ending with recap_<date>.mp4."""
    from unittest.mock import MagicMock
    from src.config import settings as _settings

    monkeypatch.setattr(_settings, "data_dir", tmp_path)

    db_manager = MagicMock()
    encoder = TimelapseEncoder(db_manager)
    path = encoder._get_video_path(123, "20260313")
    assert path.name == "recap_20260313.mp4"


def test_rt_video_path_uses_recap_prefix(tmp_path, monkeypatch):
    """_get_rt_video_path returns path ending with recap_<date>_rt.mp4."""
    from unittest.mock import MagicMock
    from src.config import settings as _settings

    monkeypatch.setattr(_settings, "data_dir", tmp_path)

    db_manager = MagicMock()
    encoder = TimelapseEncoder(db_manager)
    path = encoder._get_rt_video_path(123, "20260313")
    assert path.name == "recap_20260313_rt.mp4"


def test_apply_overlay_composite_applies_sidebar():
    """apply_overlay_composite (now in frame_utils) makes frames wider."""
    from src.utils.frame_utils import apply_overlay_composite

    pre = [{"user_name": "Alice", "button": "a", "user_id": 1, "timestamp": "2026-03-21T12:00:00"}]
    frames = [np.zeros((288, 320, 3), dtype=np.uint8)]
    result = apply_overlay_composite(frames, pre, [])

    assert result[0].shape[1] > frames[0].shape[1]
    assert result[0].shape[0] >= frames[0].shape[0]


def test_apply_overlay_composite_adds_inputs_at_offset():
    """apply_overlay_composite: frames before offset have empty sidebar; at offset has text."""
    from src.utils.frame_utils import apply_overlay_composite

    new_input = {"user_name": "Bob", "button": "b", "user_id": 2, "timestamp": "2026-03-21T12:00:01"}
    frames = [np.zeros((288, 320, 3), dtype=np.uint8) for _ in range(3)]
    result = apply_overlay_composite(frames, [], [(new_input, 2)])

    def sidebar_has_white(f):
        return bool(np.any(f[24:, 320:, :] > 10))

    assert not sidebar_has_white(result[0])
    assert not sidebar_has_white(result[1])
    assert sidebar_has_white(result[2])
```

- [ ] **Step 2: Run tests to confirm failures before implementation**

```bash
poetry run pytest tests/test_timelapse_encoder_overlay.py -v
```
Expected: `test_timelapse_job_has_no_overlay_fields` FAILS (fields still exist), `test_enqueue_does_not_accept_overlay_params` FAILS (params still accepted).

- [ ] **Step 3: Update `timelapse_encoder.py` — delete `make_frame_transform`**

Delete the entire `make_frame_transform` function (lines 45–79). It has moved to `frame_utils.py` as `_make_frame_transform`.

- [ ] **Step 4: Drop `pre_existing_inputs` + `new_inputs_with_offsets` from `TimelapseJob`**

In the `TimelapseJob` dataclass, remove:
```python
pre_existing_inputs: list = field(default_factory=list)
new_inputs_with_offsets: list = field(default_factory=list)
```

- [ ] **Step 5: Remove overlay params from `TimelapseEncodingQueue.enqueue`**

Remove `pre_existing_inputs` and `new_inputs_with_offsets` parameters from `enqueue()` signature and from the `TimelapseJob(...)` construction inside it.

- [ ] **Step 6: Remove `frame_transform` from the four private `TimelapseEncoder` helpers**

For each of `_create_new_timelapse`, `_append_frames`, `_create_new_realtime_timelapse`, `_append_realtime_frames`:
- Remove `frame_transform: Optional[Callable] = None` from the method signature
- Remove `frame_transform=frame_transform` from the call to `save_frames_as_mp4_optimized` or `save_frames_as_mp4_with_audio`

- [ ] **Step 7: Remove pre-scaling loop + `frame_transform` usage from `_do_encode_and_append`**

In `_do_encode_and_append`, delete the block:
```python
h, w = job.frames[0].shape[:2]
h_scaled, w_scaled = h * 2, w * 2

frames = [
    np.array(Image.fromarray(frame).resize((w_scaled, h_scaled), Image.Resampling.NEAREST))
    for frame in job.frames
]
```
Replace with:
```python
frames = job.frames
```

Also remove:
```python
has_inputs = job.pre_existing_inputs or job.new_inputs_with_offsets
frame_transform = (
    make_frame_transform(job.pre_existing_inputs, job.new_inputs_with_offsets)
    if has_inputs
    else None
)
```
And remove `frame_transform=frame_transform` from the four helper method calls in `_do_encode_and_append`.

- [ ] **Step 8: Clean up unused imports**

In the `timelapse_encoder.py` imports, remove:
- `Callable` from `from typing import Dict, List, Optional` (keep the rest)
- `from PIL import Image`
- `composite_overlay`, `render_input_sidebar`, `save_frames_as_mp4_optimized` (the last one stays — it's still used; check before removing)

Actually verify which imports are still needed after all removals before touching the import block.

- [ ] **Step 9: Run timelapse encoder tests**

```bash
poetry run pytest tests/test_timelapse_encoder.py tests/test_timelapse_encoder_overlay.py -v
```
Expected: All tests PASS.

- [ ] **Step 10: Commit**

```bash
git add src/tasks/timelapse_encoder.py tests/test_timelapse_encoder_overlay.py
git commit -m "refactor: remove overlay machinery from timelapse_encoder — frames arrive pre-composited"
```

---

## Task 6: Full test suite verification

- [ ] **Step 1: Run the complete test suite**

```bash
poetry run pytest --tb=short -q
```
Expected: All tests PASS with no errors. Note the total count before and after — it should not decrease (no tests silently dropped).

- [ ] **Step 2: If there are failures, investigate and fix**

Common failure modes to look for:
- Tests that patch `generate_tbc_frames` but not `apply_overlay_composite` → add the new patch
- Tests that construct `TimelapseJob` with the removed fields → remove those fields from the fixture
- Tests that call `timelapse_queue.enqueue` with overlay params → remove those params from the call

- [ ] **Step 3: Final commit**

```bash
git add -p  # stage only test fixes if any
git commit -m "test: fix remaining test suite after overlay refactor"
```

---

## Reference

- Spec: `docs/superpowers/specs/2026-03-21-frame-overlay-refactor-design.md`
- Run a single test file: `poetry run pytest tests/test_frame_utils.py -v`
- Run a single test: `poetry run pytest tests/test_frame_utils.py::TestApplyOverlayComposite::test_output_shape_is_composited -v`
