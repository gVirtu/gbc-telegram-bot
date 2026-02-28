# GBC Telegram Bot

![demo](https://github.com/user-attachments/assets/f5bcc560-0973-4f12-94f6-13954a99516d)

Play GBC games collaboratively in Telegram chats, completely inline, without polluting chat history.

## Features

- Gameplay footage sent as GIFs after input, in a single message
- Save/Load State
- Autosave after each input, autoloading last save on bot restart
- Input queueing for concurrent requests
- Daily backups of save states
- On-demand timelapse generation (per day)
- Admin-only commands for group chats
- Game-specific modifier buttons (held buttons during input)
- Game-specific hooks for custom behavior (early animation termination / prevent dangerous actions)
- Chat allowlist
- Multi-language (currently supported: `pt-BR`, `en-US`)
- Configurable rate limiting

## Architecture

- Webhook-based Telegram bot
- GameBoy emulation powered by [PyBoy](https://github.com/Baekalfen/PyBoy)
- SQLite-based state persistence
- Gameplay footage encoded with [FFmpeg](https://ffmpeg.org/)

## Quick start

1. Set environment variables:

```bash
# Obtain a bot token with @BotFather
export TELEGRAM_BOT_TOKEN={YOUR TELEGRAM BOT TOKEN HERE}

# Define a webhook URL
#   - If hosting locally, consider using a tool like ngrok
#   - If hosting on a server, this is your server's domain
export WEBHOOK_URL={YOUR WEBHOOK URL HERE}

# Define a webhook secret
#   Example: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
export WEBHOOK_SECRET={YOUR SECRET HERE}

# Volumes
#   Should point to directories on the host machine
export ROM_VOLUME_DIR={DIRECTORY WHERE ROM IS LOCATED}
export DATA_VOLUME_DIR={DIRECTORY WHERE SAVE DATA WILL BE STORED}

# Define the ROM file that will be played. (keep the /app/roms/ prefix)
export ROM_PATH=/app/roms/{YOUR ROM FILENAME HERE}

# Optionally, define a list of Telegram chat IDs that are allowed to use the bot.
export ALLOWED_CHAT_IDS={OPTIONAL: YOUR TELEGRAM CHAT ID HERE}
```

2. Run with docker:

```bash
docker run -d \
  --name gbc-telegram-bot \
  -e TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN} \
  -e WEBHOOK_URL=${WEBHOOK_URL} \
  -e WEBHOOK_SECRET=${WEBHOOK_SECRET}\
  -e ROM_PATH=${ROM_PATH} \
  -e ALLOWED_CHAT_IDS=${ALLOWED_CHAT_IDS} \
  -v ${ROM_VOLUME_DIR}:/app/roms \
  -v ${DATA_VOLUME_DIR}:/app/data \
  -p 8000:8000 \
  gvirtu/pyboy-telegram-bot:latest
```

3. Set webhook for the bot:

```bash
docker exec gbc-telegram-bot python -c 'from src.main import setup_webhook; setup_webhook()'
```

4. Send `/start_game` to the bot in a Telegram chat.

## Commands

| Command                 | Description                                                                               | Admin only? |
| ----------------------- | ----------------------------------------------------------------------------------------- | ----------- |
| `/start_game`           | Starts the game in the current chat                                                       | Yes         |
| `/resume`               | Sends a new message with the current game state                                           | No          |
| `/reboot`               | Restarts the current game.                                                                | Yes         |
| `/print`                | Sends a screen capture of the current game frame                                          | No          |
| `/gif`                  | Sends the last gameplay animation in the current chat (does not persist between restarts) | No          |
| `/save N`               | Saves in slot N                                                                           | Yes         |
| `/load N`               | Loads from slot N                                                                         | Yes         |
| `/load backup YYYYMMDD` | Loads a backup from the given date                                                        | Yes         |
| `/status`               | Shows the current game status                                                             | No          |
| `/help`                 | Shows a help message                                                                      | No          |
| `/m`                    | Sets the message text that will be displayed below the game state in the chat             | Yes         |
| `/recap YYYYMMDD`       | Sends a timelapse of the specified day                                                    | No          |
| `/language LANGUAGE`    | Changes the language of the bot (LANGUAGE can be `pt-BR` or `en-US`)                      | Yes         |
| `/maintenance on/off`   | Toggles maintenance mode (only admins can send input)                                     | Yes         |

## Development Setup

### 1. Install Dependencies

First, install [ffmpeg](https://ffmpeg.org/download.html) and make sure it is in your PATH:

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y ffmpeg

# Fedora
sudo dnf install ffmpeg

# Arch Linux
sudo pacman -S ffmpeg
```

Then, install Python dependencies.

```bash
# Using Poetry
poetry install

# OR via traditional venv
python -m venv venv
source venv/bin/activate
pip install .
```

### 2. Configure Environment

```bash
cp .env.example .env
```

**⚠️ Remember to edit `.env` with your Telegram bot token and webhook URL and secret.**

### 3. Add ROM File

Place your GBC ROM file at `./roms/game.gbc`

### 4. Set up webhook

```bash
# Using Poetry
poetry run python -c 'from src.main import setup_webhook; setup_webhook()'

# OR via traditional venv
python -c 'from src.main import setup_webhook; setup_webhook()'
```

### 5. Run tests

```bash
# Using Poetry
poetry run pytest tests

# OR via traditional venv
python -m pytest tests
```

### 6. Run the Bot

```bash
# Using Poetry
poetry run python -m src.main

# OR via traditional venv
python -m src.main
```

## Environment Variables

| Variable                     | Required | Default                      | Description                                                         |
| ---------------------------- | -------- | ---------------------------- | ------------------------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN`         | Yes      | -                            | Telegram bot token from @BotFather                                  |
| `WEBHOOK_URL`                | Yes      | -                            | Public URL for webhook endpoint                                     |
| `WEBHOOK_SECRET`             | Yes      | -                            | Secret token for webhook validation                                 |
| `PORT`                       | No       | 8000                         | Server port                                                         |
| `ROM_PATH`                   | No       | ./roms/game.gbc              | Path to ROM file                                                    |
| `SYM_PATH`                   | No       | -                            | Path to Symbols file                                                |
| `DATA_DIR`                   | No       | ./data                       | Directory for runtime data                                          |
| `LOG_LEVEL`                  | No       | INFO                         | Logging level                                                       |
| `INPUT_HOLD_FRAMES`          | No       | 10                           | Number of frames to hold each input                                 |
| `ANIMATION_DURATION`         | No       | 5                            | Maximum duration of animation phase after input presses, in seconds |
| `TBC_OVERLAY_PATH`           | No       | ./assets/to_be_continued.png | Path to "To Be Continued" overlay image                             |
| `TBC_DURATION_FRAMES`        | No       | 10                           | Number of frames for the "To Be Continued" end sequence             |
| `TIMELAPSE_FRAME_SKIP`       | No       | 20                           | Number of frames to skip between each frame in the timelapse        |
| `TIMELAPSE_BACKOFF_DELAYS`   | No       | 1,2,4                        | Backoff delays for timelapse generation retries in seconds          |
| `SAVE_SLOTS`                 | No       | 5                            | Number of save slots available                                      |
| `BACKUP_HOUR`                | No       | 0                            | Hour of the day (0-23) to perform save backups                      |
| `BACKUP_MINUTE`              | No       | 0                            | Minute of the hour (0-59) to perform save backups                   |
| `BACKUP_RETENTION_DAYS`      | No       | 30                           | Number of days to keep backups                                      |
| `MAX_SEQUENCE_LENGTH`        | No       | 6                            | Maximum number of buttons in an input sequence                      |
| `SEQUENCE_DELAY_SECONDS`     | No       | 1.0                          | Delay in seconds between button presses in a sequence               |
| `MAX_QUEUE_SIZE`             | No       | 10                           | Maximum number of items in the input queue                          |
| `RATE_LIMIT_PER_CHAT`        | No       | 1                            | Maximum messages per chat within the window                         |
| `RATE_LIMIT_PER_CHAT_WINDOW` | No       | 1.0                          | Time window in seconds for per-chat rate limit                      |
| `RATE_LIMIT_GLOBAL`          | No       | 30                           | Maximum messages globally across all chats within the window        |
| `RATE_LIMIT_GLOBAL_WINDOW`   | No       | 1.0                          | Time window in seconds for global rate limit                        |
| `ALLOWED_CHAT_IDS`           | No       | -                            | List of allowed chat IDs, comma separated. Empty = allow all        |

## Project Structure

```
.
├── src/
│   ├── assets/      # Static assets (images and such)
│   ├── db/          # Database migrations and utilities
│   ├── game_hooks/  # Game-specific PyBoy hooks
│   ├── handlers/    # Telegram handlers
│   ├── models/      # Data models
│   ├── tasks/       # Async tasks
│   └── utils/       # Utility functions
├── tests/           # Test files
├── data/            # Persistent data (db, saved states)
├── roms/            # Place ROM files here
├── pyproject.toml
└── .env.example
```

## Docker Image Building

This project supports multi-architecture Docker images (x86_64 and ARM64) with semantic versioning based on `pyproject.toml`.

### Quick Build

```bash
# Dry-run build (local only, no push)
./scripts/build-image.sh

# Build and push to registry
./scripts/build-image.sh docker.io/gvirtu push
```

### Using Versioned Images

Update your `.env` file:

```bash
# Use a specific version
IMAGE_TAG=1.0.0

# Or use latest (default)
IMAGE_TAG=latest

# Use a different registry
DOCKER_REGISTRY=ghcr.io/myorg
```

## License

MIT
