## Summary

A Telegram/Discord bot to play GBC games collaboratively in group chats. Users press inline keyboard buttons, bot runs received input in a queue through a headless PyBoy emulator, animates the result and edits the message's media.

## Dependencies

Python 3.11 required (`mise.toml`). Dependencies in `pyproject.toml`, managed by `poetry`.

## Architecture

FastAPI webhook server: Discord using discord.py, endpoints to receive Telegram updates, routes them to handlers, and controls a stateful emulator instance per chat.

### Key Modules

- **`src/config.py`** - Pydantic Settings - global `settings` object imported everywhere.
- **`src/db/migrations/*.py`** - Migrations for the DB schema.
- **`src/db/manager.py`** - DB queries and commands.
- **`src/game.py`** - `GameController` wraps a single PyBoy instance. One controller per chat_id.
- **`src/handlers/input_handler.py`** - `InputHandler` manages the game loop: receive button press -> buffer input -> loop process queue -> execute input -> async animate frames.
- **`src/handlers/commands.py`** - Functions registered in `COMMAND_HANDLERS` dict.
- **`src/handlers/webhook.py`** - Has the FastAPI app lifecycle, routes callbacks and messages.
- **`src/utils/frame_utils.py`** - Animation MP4 encoding using FFMPEG, overlay utils, and more.
- **`src/models/*.py`** - Dataclasses for game state, input, etc.

### Testing

All features MUST be tested with `unittest`. pytest-asyncio is available. Run tests with `poetry run pytest`.

### Response style

When reporting info, be extremely concise and sacrifice grammar for the sake of conciseness.
