# GBC Telegram Bot

A Telegram bot that allows group chats to collaboratively play GBC games through voting on inputs.

## Features

- Group-based collaborative gameplay via voting
- Real-time GameBoy emulation using PyBoy
- Webhook-based Telegram bot architecture
- File-based state persistence

## Setup

### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
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
python -m src.main
```

## Environment Variables

| Variable             | Required | Default              | Description                         |
| -------------------- | -------- | -------------------- | ----------------------------------- |
| `TELEGRAM_BOT_TOKEN` | Yes      | -                    | Telegram bot token from @BotFather  |
| `WEBHOOK_URL`        | Yes      | -                    | Public URL for webhook endpoint     |
| `WEBHOOK_SECRET`     | Yes      | -                    | Secret token for webhook validation |
| `PORT`               | No       | 8000                 | Server port                         |
| `ROM_PATH`           | No       | ./roms/game.gbc      | Path to ROM file                    |
| `DATA_DIR`           | No       | ./data               | Directory for runtime data          |
| `INITIAL_SAVE_PATH`  | No       | ./roms/initial.state | Path to initial save state          |
| `LOG_LEVEL`          | No       | INFO                 | Logging level                       |

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
├── requirements.txt
└── .env.example
```

## License

MIT
