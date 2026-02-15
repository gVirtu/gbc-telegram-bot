# Docker Deployment Guide

## Quick Start

1. **Copy environment file:**
   ```bash
   cp .env.docker.example .env
   ```

2. **Edit `.env` and fill in required values:**
   - `TELEGRAM_BOT_TOKEN`
   - `WEBHOOK_URL`
   - `WEBHOOK_SECRET`

3. **Place your ROM file:**
   ```bash
   mkdir -p roms
   cp /path/to/your/game.gbc roms/
   # Optional: copy initial save state
   cp /path/to/initial.state roms/
   ```

4. **Start the bot:**
   ```bash
   docker-compose up -d
   ```

5. **Check logs:**
   ```bash
   docker-compose logs -f
   ```

## Security Features

- **Rootless**: Container runs as non-root user (uid 1000)
- **No .env in image**: Build context excludes all .env files
- **No new privileges**: Container cannot escalate privileges
- **Resource limits**: CPU and memory limits configured
- **Restart policy**: Container restarts on failure (max 5 attempts)

## Volume Mounts

- `./data:/app/data` - Persistent storage for saves, config, and polls (read-write)
- `./roms:/app/roms` - ROM files and save data (.sav, .ram, .rtc files)

Both directories are mounted read-write because the emulator writes save files alongside ROM files.

## Environment Variables

### Required
- `TELEGRAM_BOT_TOKEN` - Bot token from @BotFather
- `WEBHOOK_URL` - Public URL for webhook endpoint
- `WEBHOOK_SECRET` - Secret token for webhook validation

### Optional
- `PORT` - Server port (default: 8000)
- `LOG_LEVEL` - Logging level (default: INFO)
- `ROM_PATH` - Path to ROM file inside container (default: /app/roms/game.gbc)
- `DATA_DIR` - Data directory inside container (default: /app/data)
- `INITIAL_SAVE_PATH` - Initial save state path (default: /app/roms/initial.state)
- `ALLOWED_CHAT_IDS` - Comma-separated list of allowed chat IDs

## Updating

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose up -d --build
```

## Troubleshooting

### Container won't start
Check logs: `docker-compose logs`

### Permission issues
Ensure the `data` and `roms` directories are writable by user 1000:
```bash
sudo chown -R 1000:1000 ./data ./roms
```

### Health check failing
The health check pings port 8000. Ensure the bot is fully started (may take a few seconds).

### ROM not found
Make sure your ROM file is in the `roms/` directory and the `ROM_PATH` environment variable matches the filename.

## Development

For development, you can create a `docker-compose.override.yml` file:

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
```

This will:
- Disable automatic restart
- Set log level to DEBUG
- Allow you to mount source code for live reload (uncomment in override file)

## Commands Reference

```bash
# Build and start
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop
docker-compose down

# Rebuild after code changes
docker-compose up -d --build

# Run one-off command
docker-compose run --rm bot python -m pytest

# Shell into container (for debugging)
docker-compose exec bot /bin/bash
```
