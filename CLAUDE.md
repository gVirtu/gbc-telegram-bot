# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Telegram bot that lets group chats collaboratively play Gameboy games. Users press inline keyboard buttons (first vote wins), the bot runs the input through a headless PyBoy emulator, animates the result by editing the Telegram message, then re-enables the keyboard for the next input.

## Commands

```bash
# Run the bot
python -m src.main

# Run all tests
pytest

# Run a single test file
pytest tests/test_config.py

# Run a specific test
pytest tests/test_config.py::TestRequiredSettings::test_telegram_bot_token_required

# Activate virtualenv
source venv/bin/activate
```

Python 3.11 is required (managed via `mise.toml`). Dependencies are in `requirements.txt` (runtime) and `pyproject.toml` (dev extras).

## Architecture

The app is a FastAPI webhook server that receives Telegram updates, routes them to handlers, and controls a PyBoy GameBoy emulator per chat.

### Request Flow

1. **Telegram sends update** -> `WebhookHandler` (FastAPI endpoint at `/webhook/{hash}`)
2. **WebhookHandler** routes to either:
   - `InputHandler.handle_button_press()` for callback queries (game button presses)
   - `COMMAND_HANDLERS[command]` for `/start_game`, `/resume`, `/save`, `/load`, `/status`, `/print`, `/help`
3. **InputHandler** uses `GameController` (PyBoy wrapper) to execute inputs and animate frames
4. **StateManager** persists everything to disk as JSON/binary files

### Key Modules

- **`src/config.py`** - Pydantic Settings with env var support. Uses a `_SettingsProxy` for lazy instantiation. The global `settings` object is imported everywhere. In tests, `PYTEST_CURRENT_TEST` env var skips `.env` loading and ROM validation.
- **`src/game.py`** - `GameController` wraps a single PyBoy instance. `GameControllerManager` (singleton `game_controller_manager`) manages one controller per chat_id.
- **`src/handlers/input_handler.py`** - `InputHandler` manages the game loop: receive button press -> lock input -> remove keyboard -> execute input -> animate frames (edit message every N seconds) -> re-add keyboard. Uses a `_processing` set to enforce first-vote-wins.
- **`src/handlers/commands.py`** - Command functions registered in `COMMAND_HANDLERS` dict. Commands auto-start the game via `_ensure_game_active()` which tries to load save slot 1 first.
- **`src/handlers/webhook.py`** - `WebhookHandler` creates the FastAPI app in `create_app()` with lifespan for startup/shutdown. Routes callbacks and messages.
- **`src/keyboard.py`** - Telegram inline keyboard builders. `BUTTON_LAYOUT` from `models/game_state.py` defines the grid.
- **`src/utils/state_manager.py`** - File-based persistence. Game state goes in `data/polls/<chat_id>.json`, save states in `data/saves/<chat_id>/slot_N.state`, config in `data/config/<chat_id>.json`.
- **`src/utils/frame_utils.py`** - Frame hashing (SHA256) for deduplication and numpy-to-PNG conversion via Pillow.
- **`src/models/game_state.py`** - Dataclasses: `GameButton` enum, `ChatGameState`, `ChatConfig`, `SaveSlotInfo`, `GameSession`.

### Singleton Pattern

Several modules use module-level singletons: `settings` (config proxy), `game_controller_manager`, `state_manager`, `_webhook_handler`, `_input_handler`. These are lazily initialized.

### Testing

All features MUST be tested. Tests use `PYTEST_CURRENT_TEST=1` to bypass `.env` file loading and ROM existence checks. Config tests create temporary ROM files via `tmp_path`. pytest-asyncio is available for async tests.

## Environment Variables

Required: `TELEGRAM_BOT_TOKEN`, `WEBHOOK_URL`, `WEBHOOK_SECRET` (min 16 chars). See `.env.example` for the full list.
