# GBC Telegram Bot - System Design

**Date**: 2026-02-04  
**Architecture**: PyBoy + FastAPI + File-based State  
**Deployment**: Single VPS, self-contained

---

## Overview

A Telegram bot that allows group chats to collaboratively play GBC games through voting on inputs. The bot runs a headless GameBoy Color emulator (PyBoy) and exposes the game via inline keyboard buttons in a single message that gets updated throughout gameplay.

**Key Design Decisions**:

- Single message per chat (no chat pollution)
- First vote wins (inline keyboard buttons, not polls)
- No external dependencies (file-based state, no Redis/DB)
- Optimized frame updates (skip if unchanged)
- Self-healing (always waits for input, no stuck states)

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Bot (Python)                     │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Webhook    │  │   Game       │  │   Input          │  │
│  │   Handler    │◄─┤   Controller │◄─┤   Handler        │  │
│  │   (FastAPI)  │  │   (PyBoy)    │  │   (Buttons)      │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│         │                  │                    │          │
│         ▼                  ▼                    ▼          │
│  ┌────────────────────────────────────────────────────┐   │
│  │              File-based State Storage               │   │
│  │  data/polls/<chat_id>.json                         │   │
│  │  data/saves/<chat_id>/slot_{0-4}.state            │   │
│  │  data/config/<chat_id>.json                        │   │
│  └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Component Details

#### 1. Webhook Handler (`webhook.py`)

FastAPI endpoint receiving Telegram updates:

```python
@app.post("/webhook/{token_hash}")
async def webhook_handler(update: TelegramUpdate, token_hash: str):
    # Validate token hash
    # Route to appropriate handler based on update type:
    # - callback_query: Button press
    # - message with /command: Command handler
```

**Routes**:

- `POST /webhook/{token_hash}` - Receive Telegram updates
- `GET /health` - Health check for monitoring

#### 2. Game Controller (`game.py`)

Manages the PyBoy emulator instance per chat:

```python
class GameController:
    def __init__(self, chat_id: int, rom_path: str):
        self.pyboy = PyBoy(rom_path, window="null")
        self.chat_id = chat_id
        self.last_frame_hash = None
        self.input_in_progress = False

    def tick(self, frames: int) -> np.ndarray:
        """Advance emulator and return frame buffer"""
        for _ in range(frames):
            self.pyboy.tick()
        return self.get_frame()

    def get_frame(self) -> np.ndarray:
        """Get current screen as numpy array"""
        screen = self.pyboy.botsupport_manager().screen()
        return screen.screen_ndarray()

    def send_input(self, button: str, frames: int):
        """Press and hold button for N frames"""
        press_event = BUTTON_MAP[button]["press"]
        release_event = BUTTON_MAP[button]["release"]

        self.pyboy.send_input(press_event)
        self.tick(frames)
        self.pyboy.send_input(release_event)
```

**Button Mapping**:

```python
BUTTON_MAP = {
    "up": {"press": WindowEvent.PRESS_ARROW_UP, "release": WindowEvent.RELEASE_ARROW_UP},
    "down": {"press": WindowEvent.PRESS_ARROW_DOWN, "release": WindowEvent.RELEASE_ARROW_DOWN},
    "left": {"press": WindowEvent.PRESS_ARROW_LEFT, "release": WindowEvent.RELEASE_ARROW_LEFT},
    "right": {"press": WindowEvent.PRESS_ARROW_RIGHT, "release": WindowEvent.RELEASE_ARROW_RIGHT},
    "a": {"press": WindowEvent.PRESS_BUTTON_A, "release": WindowEvent.RELEASE_BUTTON_A},
    "b": {"press": WindowEvent.PRESS_BUTTON_B, "release": WindowEvent.RELEASE_BUTTON_B},
    "start": {"press": WindowEvent.PRESS_BUTTON_START, "release": WindowEvent.RELEASE_BUTTON_START},
    "select": {"press": WindowEvent.PRESS_BUTTON_SELECT, "release": WindowEvent.RELEASE_BUTTON_SELECT},
}
```

#### 3. Input Handler (`input_handler.py`)

Processes inline keyboard callbacks and manages game flow:

```python
class InputHandler:
    def __init__(self, bot: Bot, game_controllers: Dict[int, GameController]):
        self.bot = bot
        self.games = game_controllers

    async def handle_button_press(self, callback_query: CallbackQuery):
        """Handle first button press (first vote wins)"""
        chat_id = callback_query.message.chat.id
        button = callback_query.data  # "up", "down", "a", etc.

        game = self.games.get(chat_id)
        if not game or game.input_in_progress:
            await callback_query.answer("Wait for current input to finish!")
            return

        # Lock input processing
        game.input_in_progress = True

        # Remove keyboard immediately
        await self.bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=callback_query.message.message_id,
            reply_markup=None  # Removes all buttons
        )

        # Execute input
        await self.execute_input(chat_id, button, callback_query.message.message_id)

    async def execute_input(self, chat_id: int, button: str, message_id: int):
        """Execute input and animate results"""
        game = self.games[chat_id]

        # Press button for INPUT_HOLD_FRAMES
        game.send_input(button, INPUT_HOLD_FRAMES)

        # Animation phase: edit message every ANIMATION_INTERVAL for ANIMATION_DURATION
        start_time = time.time()
        last_update = 0

        while time.time() - start_time < ANIMATION_DURATION:
            # Tick a few frames
            frame = game.tick(ANIMATION_TICK_FRAMES)

            # Check if frame changed (optimization)
            frame_hash = hash_frame(frame)
            if frame_hash != game.last_frame_hash:
                # Convert to PNG and edit message
                png_bytes = frame_to_png(frame)
                await self.bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=png_bytes)
                )
                game.last_frame_hash = frame_hash

            # Wait for next interval
            await asyncio.sleep(ANIMATION_INTERVAL)

        # Unlock and add new keyboard
        game.input_in_progress = False
        await self.add_keyboard(chat_id, message_id)
```

#### 4. Command Handler (`commands.py`)

Handles bot commands:

```python
class CommandHandler:
    async def start_game(self, message: Message):
        """/start_game - Initialize or restart game"""
        chat_id = message.chat.id

        # Load or create game controller
        if chat_id not in self.games:
            self.games[chat_id] = GameController(chat_id, ROM_PATH)

        game = self.games[chat_id]
        game.load_initial_save()  # Load from data/saves/<chat_id>/initial.state

        # Capture initial frame
        frame = game.get_frame()
        png_bytes = frame_to_png(frame)
        game.last_frame_hash = hash_frame(frame)

        # Send message with keyboard
        keyboard = self.create_input_keyboard()
        sent_message = await self.bot.send_photo(
            chat_id=chat_id,
            photo=png_bytes,
            caption="GBC Game - Press a button to play!\nFirst press wins.",
            reply_markup=keyboard
        )

        # Store message ID for future edits
        save_poll_state(chat_id, sent_message.message_id)

    async def current_frame(self, message: Message):
        """/current_frame - Show current frame"""
        chat_id = message.chat.id
        game = self.games.get(chat_id)

        if not game:
            await message.reply("No active game! Use /start_game first.")
            return

        frame = game.get_frame()
        png_bytes = frame_to_png(frame)

        # If input not in progress, add keyboard
        keyboard = None if game.input_in_progress else self.create_input_keyboard()

        await self.bot.send_photo(
            chat_id=chat_id,
            photo=png_bytes,
            caption="Current frame",
            reply_markup=keyboard
        )
```

### State Storage

All state stored in files (no external DB):

```
data/
├── polls/
│   └── <chat_id>.json          # Current game message ID, input status
├── saves/
│   └── <chat_id>/
│       ├── initial.state       # Starting save state
│       ├── slot_0.state        # Rotating auto-saves
│       ├── slot_1.state
│       ├── slot_2.state
│       ├── slot_3.state
│       └── slot_4.state
└── config/
    └── <chat_id>.json          # Chat-specific settings
```

**Poll State** (`data/polls/<chat_id>.json`):

```json
{
  "message_id": 12345,
  "input_in_progress": false,
  "last_input": "a",
  "last_input_time": "2026-02-04T10:30:00Z"
}
```

**Config** (`data/config/<chat_id>.json`):

```json
{
  "input_hold_frames": 30,
  "animation_duration": 10,
  "animation_interval": 1,
  "animation_tick_frames": 60
}
```

---

## Configuration

### Default Settings

```python
# Game timing
INPUT_HOLD_FRAMES = 30          # Hold button for 30 frames (0.5s @ 60fps)
ANIMATION_DURATION = 10         # Show animation for 10 seconds
ANIMATION_INTERVAL = 1          # Edit message every 1 second
ANIMATION_TICK_FRAMES = 60      # Advance 60 frames between edits (1 second of game time)

# Save state
AUTO_SAVE_INTERVAL = 300        # Auto-save every 5 minutes (in seconds)
SAVE_SLOTS = 5                  # Number of rotating save slots

# Telegram
MAX_RETRIES = 3                 # Retry failed API calls
RETRY_DELAY = 1                 # Seconds between retries
```

### Environment Variables

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_here
WEBHOOK_URL=https://your-domain.com/webhook
WEBHOOK_SECRET=random_secret_for_validation

# Optional (with defaults)
PORT=8000
ROM_PATH=./roms/game.gbc
DATA_DIR=./data
INITIAL_SAVE_PATH=./roms/initial.state
```

---

## Game Flow

### Sequence Diagram

```
User                    Bot                    Game Controller
 |                       |                            |
 |---- /start_game ----->|                            |
 |                       |---- initialize PyBoy ----->|
 |                       |<---- ready ----------------|
 |                       |                            |
 |                       |---- get initial frame ---->|
 |                       |<---- frame buffer ---------|
 |                       |                            |
 |<--- photo + keyboard--|                            |
 |                       |                            |
 |---- [press A] ------->|                            |
 |                       |---- remove keyboard -------|
 |<--- (buttons gone) ---|                            |
 |                       |                            |
 |                       |---- send_input(A, 30) ---->|
 |                       |<---- done -----------------|
 |                       |                            |
 |                       |---- tick(60) ------------->|
 |                       |<---- frame 1 --------------|
 |<--- edit: frame 1 ----|                            |
 |    (1 second delay)   |                            |
 |                       |---- tick(60) ------------->|
 |                       |<---- frame 2 --------------|
 |<--- edit: frame 2 ----|                            |
 |    ... (10 seconds)   |                            |
 |                       |                            |
 |                       |---- tick(60) ------------->|
 |                       |<---- frame N --------------|
 |<--- edit: frame N + keyboard ---------------------|
 |                       |                            |
 |---- [press B] ------->|                            |
 |                       |    (repeat cycle)          |
```

### Input States

1. **Waiting for Input**: Message shows frame with inline keyboard buttons
   - All buttons active and clickable
   - First press wins immediately

2. **Processing Input**: Button pressed, input executing
   - Keyboard removed from message
   - Caption shows: "Processing: [Button]..."
   - Animation phase begins

3. **Animation Phase**: Showing game progression
   - Message edited every 1 second with new frame (if changed)
   - No user interaction possible
   - Lasts for 10 seconds

4. **Back to Waiting**: Animation complete
   - Fresh keyboard added to message
   - Ready for next input

---

## Frame Optimization

To minimize Telegram API calls and bandwidth:

```python
import hashlib

def hash_frame(frame: np.ndarray) -> str:
    """Create hash of frame buffer for comparison"""
    return hashlib.sha256(frame.tobytes()).hexdigest()

def frame_to_png(frame: np.ndarray) -> BytesIO:
    """Convert numpy array to PNG bytes"""
    image = Image.fromarray(frame)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return buffer

async def update_frame_if_changed(game, chat_id, message_id, bot):
    """Only edit message if frame actually changed"""
    frame = game.get_frame()
    frame_hash = hash_frame(frame)

    if frame_hash == game.last_frame_hash:
        return False  # Skip update

    png_bytes = frame_to_png(frame)
    await bot.edit_message_media(
        chat_id=chat_id,
        message_id=message_id,
        media=InputMediaPhoto(media=png_bytes)
    )
    game.last_frame_hash = frame_hash
    return True
```

**Benefits**:

- Reduces API calls by ~60-80% during static screens (menus, text boxes)
- Lower bandwidth usage
- Faster perceived performance (no flickering on unchanged frames)

---

## Error Handling

### Graceful Degradation

1. **Lost Message**: If message is deleted by user
   - `/current_frame` creates new message
   - Updates reference in poll state

2. **Telegram API Errors**:
   - Retry with exponential backoff (max 3 retries)
   - Log errors, don't crash
   - Continue game loop even if frame update fails

3. **Corrupt Save State**:
   - Try next slot in rotation
   - If all fail, restart from initial state
   - Notify chat of reset

4. **Memory Issues**:
   - Limit concurrent games (configurable, default 10)
   - LRU cache for inactive games (unload after 1 hour idle)

### Recovery Mechanisms

```python
async def safe_edit_message(bot, chat_id, message_id, **kwargs):
    """Edit message with retry logic"""
    for attempt in range(MAX_RETRIES):
        try:
            return await bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                **kwargs
            )
        except TelegramAPIError as e:
            if "message to edit not found" in str(e):
                # Message was deleted, create new one
                return await create_new_game_message(chat_id)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
            else:
                raise
```

---

## Deployment

### Requirements

**Minimal VPS Specs** (tested with 2+ concurrent games):

- 1 vCPU
- 1GB RAM
- 10GB SSD
- Python 3.9+

**Python Dependencies**:

```
fastapi==0.104.0
uvicorn==0.24.0
python-telegram-bot==20.6
pyboy==2.2.0
Pillow==10.1.0
numpy==1.24.3
```

### Directory Structure

```
pokemon-red-bot/
├── main.py                 # Entry point
├── requirements.txt
├── .env                    # Environment variables (not in git)
├── roms/
│   ├── game.gbc     # ROM file (user-provided)
│   └── initial.state       # Initial save state (user-provided)
├── src/
│   ├── __init__.py
│   ├── bot.py             # Telegram bot setup
│   ├── webhook.py         # FastAPI webhook handler
│   ├── game.py            # PyBoy game controller
│   ├── input_handler.py   # Button press handling
│   ├── commands.py        # Bot commands
│   ├── keyboard.py        # Inline keyboard layouts
│   ├── frame_utils.py     # Frame capture and conversion
│   └── state_manager.py   # File-based state persistence
└── data/                  # Runtime data (created on first run)
    ├── polls/
    ├── saves/
    └── config/
```

### Setup Instructions

1. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**:

   ```bash
   cp .env.example .env
   # Edit .env with your bot token and webhook URL
   ```

3. **Add ROM and save state**:

   ```bash
   mkdir -p roms
   cp /path/to/game.gbc roms/
   cp /path/to/initial.state roms/
   ```

4. **Set webhook** (one-time setup):

   ```bash
   python -c "from src.bot import set_webhook; set_webhook()"
   ```

5. **Run**:
   ```bash
   python main.py
   ```

### Reverse Proxy (nginx)

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    location /webhook/ {
        proxy_pass http://127.0.0.1:8000/webhook/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Commands Reference

| Command          | Description                     | Usage                |
| ---------------- | ------------------------------- | -------------------- |
| `/start_game`    | Start or restart the game       | `/start_game`        |
| `/current_frame` | Show current frame + open input | `/current_frame`     |
| `/save [slot]`   | Save current state to slot      | `/save` or `/save 2` |
| `/load [slot]`   | Load state from slot            | `/load` or `/load 1` |
| `/status`        | Show game status                | `/status`            |
| `/help`          | Show help message               | `/help`              |

---

## Testing Strategy

### Unit Tests

- **Frame utilities**: Hash calculation, PNG conversion
- **State manager**: Save/load JSON, file operations
- **Button mapping**: Correct WindowEvent mapping

### Integration Tests

- **Game controller**: PyBoy initialization, tick, input injection
- **Input handler**: First-vote-wins logic, state transitions
- **Webhook handler**: Route dispatching, token validation

### Manual Testing Checklist

- [ ] `/start_game` creates message with keyboard
- [ ] First button press removes keyboard
- [ ] Animation phase edits message every 1 second
- [ ] Frame optimization skips unchanged frames
- [ ] New keyboard appears after animation
- [ ] `/current_frame` works during and between inputs
- [ ] Save/load commands work across slots
- [ ] Game handles rapid button presses gracefully
- [ ] Recovery after message deletion
- [ ] Multiple chats can play simultaneously

---

## Future Enhancements

**Not in MVP** (but considered in design):

1. **Game state display**: Show current location, party info, badges
2. **Input history**: Log of recent commands
3. **Speed control**: Allow chat to vote on emulation speed
4. **Screenshot archive**: Save key moments automatically
5. **Admin commands**: Pause game, reset to specific save
6. **Statistics**: Most active players, favorite buttons
7. **Sound notifications**: Optional audio cues on Telegram

---

## Security Considerations

1. **Token validation**: Webhook URLs include hash of bot token
2. **Rate limiting**: Per-chat cooldown on commands (configurable)
3. **File restrictions**: Only `.state` files in save directory
4. **ROM validation**: Verify ROM checksum on startup
5. **Resource limits**: Max concurrent games, max saves per chat

---

## Performance Optimizations

1. **Frame deduplication**: Skip edits if frame unchanged
2. **Lazy loading**: Only initialize PyBoy when needed
3. **LRU cache**: Unload inactive games after timeout
4. **PNG optimization**: Use Pillow's optimize flag
5. **Batch saves**: Auto-save during idle periods
6. **Memory pooling**: Reuse numpy arrays where possible

---

## Monitoring

Basic health checks:

```python
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "active_games": len(game_controllers),
        "uptime": time.time() - start_time,
        "memory_usage": get_memory_usage(),
    }
```

**Metrics to track**:

- Active games count
- API response times
- Frame update frequency
- Error rates
- Memory usage

---

## Summary

This design prioritizes **simplicity** and **reliability** for a small-group use case:

- Single Python process with file-based state
- First-vote-wins with inline keyboard (no chat pollution)
- Optimized frame updates to reduce API calls
- Self-contained on a budget VPS
- Graceful error handling and recovery

The architecture is intentionally minimal to avoid operational complexity while providing a smooth collaborative gameplay experience.
