# Daily Timelapse Recap System - Design Document

**Date:** 2026-02-21
**Status:** Approved

## Context

The Telegram GameBoy bot currently supports a `/recap` command that resends the most recent animation. However, gameplay state can progress quickly with many incoming inputs, and players need better ways to catch up with what they missed. This design adds a new `/recap YYYYMMDD` command that generates and sends a timelapse animation of ALL gameplay from a specific day.

**Key Requirements:**
- Store daily gameplay as appendable video files (storage-efficient)
- Encode frames in the background to avoid impacting bot latency
- Skip frames to create fast timelapse (configurable skip rate)
- Ensure chronological order (no jumbled footage)
- Auto-retry failed encoding jobs
- Support both cached file_id delivery and re-upload
- Suggest nearby dates when no gameplay exists

## Architecture Overview

The timelapse system extends the existing frame capture and animation pipeline with persistent daily video storage:

### New Components

1. **`TimelapseEncodingQueue`** - Per-chat AsyncIO queues ensuring FIFO sequential processing
2. **`TimelapseEncoder`** - Handles frame skipping, FFmpeg concatenation, atomic file management
3. **`recap_files` database table** - Tracks daily timelapse videos per chat with metadata
4. **`/recap YYYYMMDD` command handler** - Retrieves and sends timelapse videos by date

### Integration Points

- **Hooks into `InputHandler._animate_frames()`** (line ~438 in `src/handlers/input_handler.py`) after animation sent to Telegram
- **Reuses `save_frames_as_mp4()` from `src/utils/frame_utils.py`** for encoding (with optimized parameters)
- **Stores daily videos** at `data/recaps/{chat_id}/YYYYMMDD.mp4` (new directory structure)
- **Background encoding task** fires after callback response sent (non-blocking)

### Key Principles

- Encoding happens asynchronously AFTER user callback response is sent (zero impact on bot latency)
- Tasks execute sequentially per chat to preserve chronological order (FIFO queue)
- Different chats can encode in parallel (separate queues)
- Atomic file operations prevent corruption
- File locking prevents concurrent access issues

## Database Schema

### New Table: `recap_files`

```sql
CREATE TABLE recap_files (
    chat_id INTEGER NOT NULL,
    date TEXT NOT NULL,           -- YYYYMMDD format
    file_id TEXT,                 -- Telegram file_id (null until uploaded/when invalidated)
    frame_count INTEGER NOT NULL DEFAULT 0,
    duration_sec REAL NOT NULL DEFAULT 0.0,
    file_size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,     -- ISO8601 timestamp
    updated_at TEXT NOT NULL,     -- ISO8601 timestamp (upserted on each append)
    PRIMARY KEY (chat_id, date)
);

CREATE INDEX idx_recap_files_chat_id ON recap_files(chat_id);
CREATE INDEX idx_recap_files_date ON recap_files(date);
```

### Update Behavior

- **After each frame append**: UPSERT record for current date
  - Increment `frame_count`
  - Update `duration_sec`, `file_size_bytes`, `updated_at`
  - **Set `file_id = NULL`** (invalidates Telegram cache - forces re-upload on next request)
- **After successful `/recap` send**: UPDATE `file_id` with new Telegram file_id (enables fast resends)

### Query Patterns

- `/recap YYYYMMDD` → `SELECT WHERE chat_id=? AND date=?`
- Find previous date → `SELECT WHERE chat_id=? AND date < ? ORDER BY date DESC LIMIT 1`
- Find next date → `SELECT WHERE chat_id=? AND date > ? ORDER BY date ASC LIMIT 1`

## Sequential Task Queue System

### Implementation: Per-Chat AsyncIO Queues

```python
# In src/tasks/timelapse_encoder.py (new file)

class TimelapseEncodingQueue:
    def __init__(self):
        self._queues: Dict[int, asyncio.Queue] = {}  # chat_id -> Queue
        self._workers: Dict[int, asyncio.Task] = {}  # chat_id -> worker task

    async def enqueue(self, chat_id: int, frames: List[np.ndarray], timestamp: str):
        """Add encoding job to chat's queue. Returns immediately."""
        if chat_id not in self._queues:
            self._queues[chat_id] = asyncio.Queue()
            self._workers[chat_id] = asyncio.create_task(self._worker(chat_id))

        await self._queues[chat_id].put((frames, timestamp))

    async def _worker(self, chat_id: int):
        """Sequential processor: pulls jobs, encodes, handles retries."""
        while True:
            frames, timestamp = await self._queues[chat_id].get()
            try:
                await self._encode_with_retry(chat_id, frames, timestamp)
            finally:
                self._queues[chat_id].task_done()
```

### Lifecycle

- Queue and worker created on-demand when first encoding job arrives for a chat
- Worker runs continuously, processing jobs sequentially (FIFO)
- Worker started during webhook lifespan startup
- Graceful shutdown: wait for in-flight jobs during FastAPI shutdown

### Guarantees

- ✅ Chronological order preserved per chat (FIFO queue)
- ✅ No concurrency issues (one encoding at a time per chat)
- ✅ Different chats can encode in parallel (separate queues)

## Frame Encoding & Appending Logic

### Frame Processing Pipeline

1. **Capture**: After `InputHandler._animate_frames()` sends animation, extract frames (already captured at 10 FPS)
2. **Filter**: Remove "To Be Continued" overlay frames (last 20 frames) - timelapse should only include gameplay
3. **Skip**: Keep every Nth frame based on `TIMELAPSE_FRAME_SKIP` env var (default: 30)
   - 10 FPS captured → skip 30 → ~0.33 FPS timelapse
   - 1 hour of gameplay = ~2 minutes of timelapse
4. **Enqueue**: Pass filtered frames to `TimelapseEncodingQueue.enqueue(chat_id, frames, timestamp)`

### Background Encoding (in queue worker)

```python
async def _encode_with_retry(self, chat_id: int, frames: List[np.ndarray], timestamp: str):
    date = datetime.now().strftime("%Y%m%d")  # Server local timezone
    video_path = f"data/recaps/{chat_id}/{date}.mp4"

    # Determine if appending to existing file or creating new
    if os.path.exists(video_path):
        await self._append_frames(video_path, frames)
    else:
        await self._create_new_timelapse(video_path, frames)

    # Update database with new metadata (upsert, reset file_id to null)
    await self._update_recap_metadata(chat_id, date, video_path)
```

### FFmpeg Append Strategy: Concat Demuxer

**Chosen for efficiency** (avoids re-encoding entire video):

1. Encode new frames to temporary segment: `{video_path}.segment.tmp`
   - Use **"medium" preset** (vs. "ultrafast" for animations) → better compression
   - Use **CRF 23** (vs. 28 for animations) → better quality
   - Remove `-movflags +faststart` (not needed for append workflow)
   - Keep: `-pix_fmt yuv420p`, `-vcodec libx264`, 10 FPS
2. Create concat file listing existing + new segment
3. Run: `ffmpeg -f concat -safe 0 -i concat.txt -c copy {video_path}.tmp`
4. Atomically replace original file with `os.replace()`

### Atomic File Replacement with Locking

```python
import fcntl  # POSIX file locking

async def _append_frames(self, video_path: str, frames: List[np.ndarray]):
    lock_path = f"{video_path}.lock"

    # Acquire exclusive lock (blocks if another process holds it)
    with open(lock_path, 'w') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        temp_segment = f"{video_path}.segment.tmp"
        temp_concat = f"{video_path}.concat.tmp"
        temp_output = f"{video_path}.tmp"

        try:
            # 1. Encode new frames to temporary segment
            await save_frames_as_mp4_optimized(frames, temp_segment)

            # 2. Create concat list: existing + new segment
            with open(temp_concat, 'w') as f:
                f.write(f"file '{video_path}'\n")
                f.write(f"file '{temp_segment}'\n")

            # 3. Concat to temporary output file
            await run_ffmpeg_concat(temp_concat, temp_output)

            # 4. ATOMIC RENAME: Replace original only after successful encoding
            os.replace(temp_output, video_path)  # Atomic on POSIX systems

        finally:
            # Clean up temporary files
            for tmp in [temp_segment, temp_concat, temp_output]:
                if os.path.exists(tmp):
                    os.remove(tmp)

        # Lock automatically released when exiting context
```

**Safety Guarantees:**
- ✅ Original file never modified during encoding (work happens in .tmp files)
- ✅ `os.replace()` is atomic on POSIX (macOS/Linux) - no partial writes visible
- ✅ File locking prevents concurrent access (encoding + `/recap` read)
- ✅ If encoding fails mid-operation, original file remains intact
- ✅ If process crashes, cleanup temp files on next run

## `/recap YYYYMMDD` Command Handler

### Command Flow

```python
async def recap_timelapse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args  # ['20260221'] or []

    # Parse date argument
    if not args:
        date = datetime.now().strftime("%Y%m%d")  # Default: today
    else:
        date = args[0]  # User-provided YYYYMMDD
        # Validate format (8 digits, valid date)

    # Query database for recap metadata
    recap_record = await db.get_recap_file(chat_id, date)

    if not recap_record:
        # No gameplay on this date - suggest nearest dates
        await send_no_gameplay_message(chat_id, date)
        return

    # Try sending via cached file_id (fast path)
    if recap_record.file_id:
        try:
            await context.bot.send_video(chat_id, video=recap_record.file_id)
            return  # Success!
        except TelegramError:
            # file_id expired/invalid, fall through to re-upload
            pass

    # Upload video file from disk
    video_path = f"data/recaps/{chat_id}/{date}.mp4"
    with open(video_path, 'rb') as video_file:
        message = await context.bot.send_video(chat_id, video=video_file)

    # Cache new file_id in database
    await db.update_recap_file_id(chat_id, date, message.video.file_id)
```

### No Gameplay Message (i18n)

```python
async def send_no_gameplay_message(chat_id: int, requested_date: str):
    prev_date = await db.get_nearest_recap_date(chat_id, requested_date, direction='before')
    next_date = await db.get_nearest_recap_date(chat_id, requested_date, direction='after')

    # Use i18n translation keys
    message = translate("recap.no_gameplay", date=requested_date)

    suggestions = []
    if prev_date:
        suggestions.append(f"← {prev_date}")
    if next_date:
        suggestions.append(f"{next_date} →")

    if suggestions:
        message += "\n\n" + translate("recap.try_dates", dates=' or '.join(suggestions))

    await bot.send_message(chat_id, message)
```

**All user-facing strings must use i18n translation system** (like existing codebase).

### Migration: Rename Current `/recap` to `/gif`

- Current `recap_command()` → rename to `gif_command()`
- Updates command registration: `/gif` instead of `/recap`
- Maintains backward compatibility (users can still resend last animation)
- Frees up `/recap` for the new timelapse feature

## Error Handling & Retry Logic

### Retry Strategy (Exponential Backoff)

```python
async def _encode_with_retry(self, chat_id: int, frames: List[np.ndarray], timestamp: str):
    max_retries = 3
    backoff_delays = [1, 2, 4]  # seconds

    for attempt in range(max_retries):
        try:
            await self._do_encode_and_append(chat_id, frames, timestamp)
            return  # Success!
        except Exception as e:
            logger.error(f"Encoding failed (attempt {attempt+1}/{max_retries}): {e}")

            if attempt < max_retries - 1:
                await asyncio.sleep(backoff_delays[attempt])
            else:
                # Final failure - save frames for manual recovery
                await self._save_failed_frames(chat_id, timestamp, frames, error=e)
```

### Failed Frame Recovery

```python
async def _save_failed_frames(self, chat_id: int, timestamp: str, frames: List[np.ndarray], error: Exception):
    failed_dir = f"data/recaps/{chat_id}/failed/{timestamp}"
    os.makedirs(failed_dir, exist_ok=True)

    # Save frames as PNGs
    for i, frame in enumerate(frames):
        frame_path = f"{failed_dir}/frame_{i:04d}.png"
        save_frame_as_png(frame, frame_path)

    # Save error log
    with open(f"{failed_dir}/error.txt", 'w') as f:
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"Error: {str(error)}\n")
        f.write(f"Frames saved: {len(frames)}\n")

    logger.critical(f"Failed to encode {len(frames)} frames for chat {chat_id}, saved to {failed_dir}")
```

### Error Categories

- **Transient**: Disk temporarily full, FFmpeg process crash → retry with backoff
- **Persistent**: Corrupted frames, invalid video format → save frames and skip
- **Fatal**: Out of memory, disk permanently full → log and continue (graceful degradation)

### Graceful Degradation

- If encoding fails 3 times, timelapse has a gap but bot continues functioning
- User can request manual recovery via saved frames in `data/recaps/{chat_id}/failed/` directory
- No impact on gameplay or other commands

## Configuration (Environment Variables)

```bash
# Timelapse frame skip rate (keep 1 out of N frames)
# Default: 30 (10 FPS capture → 0.33 FPS timelapse, 1 hour gameplay = 2 min timelapse)
TIMELAPSE_FRAME_SKIP=30
```

## Testing Strategy

### Unit Tests

1. **`tests/test_timelapse_encoder.py`**
   - Frame skipping logic (keep every Nth frame)
   - TBC frame removal (strip last 20 frames)
   - Date formatting and timezone handling (server local timezone)
   - Atomic file replacement (mock `os.replace`)
   - File locking (mock `fcntl.flock`)

2. **`tests/test_timelapse_queue.py`**
   - Sequential FIFO processing per chat
   - Parallel processing across different chats
   - Retry logic with exponential backoff
   - Failed frame recovery

3. **`tests/test_recap_command.py`**
   - Date parsing and validation (YYYYMMDD format)
   - `file_id` caching and fallback to re-upload
   - "No gameplay" message with date suggestions
   - Current day (in-progress) handling
   - i18n string translations

### Integration Tests

4. **`tests/test_timelapse_integration.py`**
   - End-to-end: Button press → frame capture → skip → enqueue → encode → append → DB update
   - Multiple inputs in sequence (verify chronological order preserved)
   - `/recap` command retrieves correct video
   - FFmpeg concat actually works (not mocked)

### Database Tests

5. **`tests/test_recap_database.py`**
   - Upsert behavior (update `frame_count`, `file_size`, reset `file_id`)
   - Index performance on `chat_id` and `date`
   - Nearest date queries (previous/next)

### Manual Testing Checklist

- [ ] Generate 30+ minutes of gameplay, verify timelapse is correctly compressed (~2-3 min video)
- [ ] Test `/recap` on current day (in-progress) vs. past days
- [ ] Test `/recap` with no gameplay (verify suggestions work)
- [ ] Verify file locking prevents corruption during concurrent access
- [ ] Check disk usage over several days of gameplay
- [ ] Test `/gif` command still works (renamed from old `/recap`)

### Test Environment

- Use `PYTEST_CURRENT_TEST=1` to skip ROM validation (existing pattern)
- Mock FFmpeg calls in unit tests, real FFmpeg in integration tests
- Use temporary database (`:memory:` or `tmp_path`) for all tests

## File Structure Changes

```
data/
├── bot.db                          # SQLite database (added recap_files table)
├── recaps/                         # NEW: Daily timelapse videos
│   └── {chat_id}/
│       ├── 20260221.mp4           # Daily timelapse (appended throughout day)
│       ├── 20260220.mp4
│       ├── 20260219.mp4
│       └── failed/                # Failed encoding recovery
│           └── {timestamp}/
│               ├── frame_0000.png
│               ├── frame_0001.png
│               └── error.txt
└── ... (existing directories)

src/
├── tasks/
│   ├── backup_task.py             # Existing backup scheduler
│   └── timelapse_encoder.py       # NEW: Encoding queue and worker
├── handlers/
│   ├── commands.py                # Modified: rename recap_command → gif_command, add recap_timelapse_command
│   └── input_handler.py           # Modified: hook timelapse encoding after animation sent
├── db/
│   └── manager.py                 # Modified: add recap_files table and queries
└── utils/
    └── frame_utils.py             # Modified: add save_frames_as_mp4_optimized() with better compression

tests/
├── test_timelapse_encoder.py     # NEW
├── test_timelapse_queue.py        # NEW
├── test_recap_command.py          # NEW
├── test_timelapse_integration.py  # NEW
└── test_recap_database.py         # NEW
```

## Implementation Checklist

- [ ] Create `src/tasks/timelapse_encoder.py` with `TimelapseEncodingQueue` and `TimelapseEncoder`
- [ ] Add `recap_files` table to `src/db/manager.py` with indexes
- [ ] Implement frame skipping and TBC removal logic
- [ ] Implement atomic file append with concat demuxer and file locking
- [ ] Hook encoding queue into `InputHandler._animate_frames()`
- [ ] Rename `recap_command` → `gif_command` in `src/handlers/commands.py`
- [ ] Implement `/recap YYYYMMDD` command handler with i18n strings
- [ ] Add retry logic with exponential backoff
- [ ] Add failed frame recovery
- [ ] Add `TIMELAPSE_FRAME_SKIP` env var support
- [ ] Initialize timelapse workers during webhook lifespan startup
- [ ] Graceful shutdown: wait for in-flight encoding jobs
- [ ] Write comprehensive tests (unit, integration, database)
- [ ] Update i18n translation files with new strings
- [ ] Manual testing with real gameplay

## Verification

**End-to-End Testing:**

1. Run the bot: `poetry run python -m src.main`
2. Play the game for 10+ minutes with multiple inputs
3. Request `/recap` (today's date) - verify timelapse video sent
4. Request `/recap YYYYMMDD` for yesterday - verify "no gameplay" message with suggestions
5. Request `/gif` - verify old recap behavior (resend last animation)
6. Check `data/recaps/{chat_id}/YYYYMMDD.mp4` file exists and is valid
7. Check database: `SELECT * FROM recap_files` - verify metadata is correct
8. Run tests: `poetry run pytest tests/test_timelapse_*` - all pass

**Performance Verification:**

- Bot latency unaffected (encoding happens in background)
- Timelapse file size reasonable (~1-2 MB per hour of gameplay)
- No memory leaks from queue accumulation
- File locks don't cause deadlocks

## Future Enhancements (Out of Scope)

- Configurable timelapse speed per chat
- Video quality settings (low/medium/high)
- Automatic retention/cleanup policy
- Admin recovery command for failed encodings
- Analytics dashboard (total gameplay hours, timelapse storage usage)
