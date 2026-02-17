# GBC Telegram Bot

A Telegram bot that allows group chats to collaboratively play GBC games through voting on inputs.

## Features

- Group-based collaborative gameplay
- Real-time GameBoy emulation using PyBoy
- Webhook-based Telegram bot architecture
- SQLite-based state persistence

## Setup

### 1. Install Dependencies

Using Poetry:

```bash
poetry install
```

Or via traditional venv:

```bash
python -m venv venv
source venv/bin/activate
pip install .
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your Telegram bot token and webhook settings
```

### 3. Add ROM File

Place your GBC ROM file at `./roms/game.gbc`

### 4. Run the Bot

```bash
poetry run python -m src.main
```

Or with active venv:

```bash
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
| `ANIMATION_TICK_FRAMES`      | No       | 60                           | Number of frames between animation ticks, in seconds                |
| `TBC_OVERLAY_PATH`           | No       | ./assets/to_be_continued.png | Path to "To Be Continued" overlay image                             |
| `TBC_DURATION_FRAMES`        | No       | 10                           | Number of frames for the "To Be Continued" end sequence             |
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
│   ├── models/      # Data models
│   ├── utils/       # Utility functions
│   └── handlers/    # Telegram handlers
├── tests/           # Test files
├── data/            # Runtime data (polls, saves)
├── roms/            # ROM files
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
