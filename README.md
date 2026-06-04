# GBC Together Bot

### 🌐 [Live demos - Click here](https://linktr.ee/polishedcrystaltogether)

![demo](https://raw.githubusercontent.com/gVirtu/gbc-together-bot/refs/heads/main/assets/demo.gif)

Play GBC games collaboratively in Telegram chats or Discord servers, completely inline, without cluttering chat history.

Includes a highly customized preset for [Pokémon Polished Crystal](https://github.com/Rangi42/polishedcrystal).

Inspired by the [Twitch Plays Pokémon](https://en.wikipedia.org/wiki/Twitch_Plays_Pok%C3%A9mon) project.

## Features

- Gameplay footage sent as GIFs after input, in a single message
- Autosave after each input, autoloading last save on bot restart
- Input queueing and batch processing
- Hourly backups of save states
- Autogenerate timelapse or realtime capture (with audio) of gameplay
- Admin-only commands for group chats
- Dynamic overlay with input history, current player, player rankings and more
- Input-based gamification with points shop: custom name tag colors, reactions
- Game-specific modifier buttons (held buttons during input)
- Game-specific hooks for custom behavior (early animation termination / prevent dangerous actions)
- Game-specific status bar render logic
- Game-specific shop items with access to in-game memory
- Game-specific event tracking with toast rendering for achievements
- Chat ID allowlist
- Multi-language (currently supported: `pt-BR`, `en-US`)

## Architecture

- GB / GBC emulation powered by [PyBoy](https://github.com/Baekalfen/PyBoy)
- Platform adapters: Telegram and Discord
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
  --name gbc-together-bot \
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

3. Set webhook for the bot (for Telegram):

```bash
docker exec gbc-together-bot python -c 'from src.main import setup_webhook; setup_webhook()'
```

4. Send `/start_game` to the bot in one of the allowed chats.

## Commands

| Command                            | Description                                                                                                                                                       | Admin only? |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| `/start_game`                      | Starts the game in the current chat                                                                                                                               | Yes         |
| `/resume`                          | Sends a new message with the current game state                                                                                                                   | No          |
| `/i BUTTON_SEQUENCE`               | Sends the given button sequence as input to the game according to the current mapping. The mapping can be changed via the "INPUT SEQUENCE" button. (Discord only) | No          |
| `/reboot`                          | Restarts the current game.                                                                                                                                        | Yes         |
| `/print`                           | Sends a screen capture of the current game frame                                                                                                                  | No          |
| `/gif`                             | Sends the last gameplay animation in the current chat (does not persist between restarts)                                                                         | No          |
| `/save N`                          | Saves in slot N                                                                                                                                                   | Yes         |
| `/load N`                          | Loads from slot N                                                                                                                                                 | Yes         |
| `/load backup YYYYMMDD`            | Loads a backup from the given date                                                                                                                                | Yes         |
| `/status`                          | Shows the current game status                                                                                                                                     | No          |
| `/help`                            | Shows a help message                                                                                                                                              | No          |
| `/m`                               | Sets the message text that will be displayed below the game state in the chat                                                                                     | Yes         |
| `/recap YYYYMMDD`                  | Sends a timelapse of the specified day                                                                                                                            | No          |
| `/mirror CHAT_ID`                  | Makes the current chat receive game updates from the specified chat (leader). Pass `unset` as `CHAT_ID` to remove the mirror.                                     | Yes         |
| `/feature FEATURE_NAME true/false` | Toggles a feature for the current chat                                                                                                                            | Yes         |
| `/language LANGUAGE`               | Changes the language of the bot (LANGUAGE can be `pt-BR` or `en-US`)                                                                                              | Yes         |
| `/maintenance on/off`              | Toggles maintenance mode (only admins can send input)                                                                                                             | Yes         |
| `/peek_symbol SYMBOL [LENGTH]`     | Shows the current value of the given symbol in hex format. (LENGTH is optional, defaults to 1 byte)                                                               | Yes         |

## Supported feature flags

#### update_group_avatar

When true, the bot will attempt to update the chat/server icon with a screenshot of the game once every 10 minutes. Requires admin permissions in the chat.

#### media_only_mirror

When true, the current chat will not receive game updates from its leader, but will have access to media commands such as `/print`, `/gif` and `/recap`.

#### realtime_recaps

When true, recaps will record gameplay and audio in the source frame rate. (File sizes will be larger!). By default, recaps record an audioless timelapse.

#### auto_send_recaps

When true, recap parts will be sent as they reach the size threshold, or at the end of the day, whichever comes first.

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

⚠️ For Discord, your ffmpeg installation must support `libsvtav1`.

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

**⚠️ Remember to edit `.env` with your bot token and, in case of Telegram, webhook URL and secret.**

### 3. Add ROM File

Place your GBC ROM file at `./roms/game.gbc`

### 4. Set up webhook (Telegram only)

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

### Required for Telegram

| Variable             | Default | Description                                         |
| -------------------- | ------- | --------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN` | -       | Telegram bot token from @BotFather                  |
| `WEBHOOK_URL`        | -       | Public URL for webhook endpoint (Telegram only)     |
| `WEBHOOK_SECRET`     | -       | Secret token for webhook validation (Telegram only) |

### Required for Discord

| Variable            | Default | Description       |
| ------------------- | ------- | ----------------- |
| `DISCORD_BOT_TOKEN` | -       | Discord bot token |

### Optional

<details>
  <summary>Show optional environment variables</summary>

| Variable                            | Default                      | Description                                                                             |
| ----------------------------------- | ---------------------------- | --------------------------------------------------------------------------------------- |
| `PORT`                              | 8000                         | Server port                                                                             |
| `ROM_PATH`                          | ./roms/game.gbc              | Path to ROM file                                                                        |
| `SYM_PATH`                          | -                            | Path to Symbols file                                                                    |
| `DATA_DIR`                          | ./data                       | Directory for runtime data                                                              |
| `LOG_LEVEL`                         | INFO                         | Logging level                                                                           |
| `INPUT_HOLD_FRAMES`                 | 10                           | Number of frames to hold each input                                                     |
| `ANIMATION_DURATION`                | 5                            | Maximum duration of animation phase after input presses, in seconds                     |
| `TBC_OVERLAY_PATH`                  | ./assets/to_be_continued.png | Path to "To Be Continued" overlay image                                                 |
| `TBC_DURATION_FRAMES`               | 10                           | Number of frames for the "To Be Continued" end sequence                                 |
| `TIMELAPSE_FRAME_SKIP`              | 20                           | Number of frames to skip between each frame in the timelapse                            |
| `TIMELAPSE_BACKOFF_DELAYS`          | 1,2,4                        | Backoff delays for timelapse generation retries in seconds                              |
| `TIMELAPSE_IDLE_WAIT_SECONDS`       | 30                           | Maximum number of seconds to wait until idle before generating the timelapse            |
| `TIMELAPSE_DONE_JOB_RETENTION_DAYS` | 1                            | Number of days to keep history of timelapse generation                                  |
| `RECAP_PART_FILE_SIZE_THRESHOLD`    | 7864320                      | Maximum number of bytes before a recap file is split into a new part                    |
| `RECAP_PART_SEND_DELAY_SECONDS`     | 10                           | Delay in seconds between sending recap parts to avoid rate limits                       |
| `SAVE_SLOTS`                        | 5                            | Number of save slots available                                                          |
| `BACKUP_RETENTION_DAYS`             | 30                           | Number of days to keep backups                                                          |
| `RECENT_INPUTS_MAX_RETENTION_DAYS`  | 7                            | Number of days to keep history of recent inputs                                         |
| `PLAYER_INPUT_MAX_SCORE`            | 10                           | Maximum base score per input. Score decreases as same user dominates the scoring window |
| `DAILY_STREAK_SCORE_BONUS`          | 50                           | Bonus points awarded per streak day for playing on consecutive days                     |
| `MAX_SEQUENCE_LENGTH`               | 12                           | Maximum number of buttons in a player's input sequence                                  |
| `MAXIMUM_INPUTS_PER_ANIMATION`      | 18                           | Maximum number of buttons to include in a single animation batch                        |
| `MAX_QUEUE_SIZE`                    | 18                           | Maximum number of items in the input queue                                              |
| `SEQUENCE_DELAY_SECONDS`            | 0.1                          | Delay in seconds between button presses in a sequence                                   |
| `INPUT_BUFFER_SECONDS`              | 1.5                          | How long to wait before starting to process inputs in a sequence                        |
| `MIN_UPDATE_INTERVAL_SECONDS`       | 2.0                          | Minimum wait between processing input batches to avoid rate limits                      |
| `ALLOWED_CHAT_IDS`                  | -                            | List of allowed chat IDs, comma separated. Empty = allow all                            |

</details>

## Project Structure

```
.
├── assets/          # Static assets (images and such)
├── src/
│   ├── adapters/      # Platform adapters
│   ├── db/            # Database migrations and utilities
│   ├── game_avatar_providers/    # Game-specific avatar rendering logic
│   ├── game_events/              # Game-specific tracked events
│   ├── game_hooks/               # Game-specific PyBoy hooks
│   ├── game_modifier_buttons/    # Game-specific modifier button definitions
│   ├── game_shops/               # Game-specific shop flows
│   ├── game_status_bars/         # Game-specific status bar rendering logic
│   ├── game_utils/               # Game-specific reusable utils
│   ├── handlers/      # Command and input handlers
│   ├── i18n/          # Internationalization helpers
│   ├── models/        # Data models
│   ├── shop/        # Shop system
│   ├── tasks/       # Async tasks
│   └── utils/       # Utility functions
├── tests/           # Test files
├── data/            # Persistent data (db, recaps, backups, saved states)
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
