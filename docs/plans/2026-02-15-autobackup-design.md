# Autobackup Feature — Design Document

**Date:** 2026-02-15
**Status:** Implemented

---

## Problem

Group chats playing Gameboy games have no protection against accidental save-slot
overwrites or corrupted states. The 5 rotating save slots can all be clobbered by
a bad `/save`, leaving no way to recover yesterday's progress.

---

## Goals

1. Automatically snapshot each active chat's game state once per day.
2. Allow group admins to restore to any day's snapshot via `/load backup YYYYMMDD`.
3. Purge snapshots older than a configurable retention window (default 30 days).
4. Zero new DB tables — backups live entirely on the filesystem.

---

## Design Decisions

### Storage format

Binary `.state` files at `data/backups/{chat_id}/backup_{YYYYMMDD}.state`.

**Why filesystem, not SQLite?**
Save-state blobs are already stored as files (the slot system uses `.state` files too).
Putting large blobs in SQLite would bloat the DB and complicate backup/restore logic.
Keeping them as files makes it easy to inspect, copy, or delete individual backups.

### Active-chat detection

Query the existing `recent_inputs` table:

```sql
SELECT DISTINCT chat_id FROM recent_inputs
WHERE timestamp >= datetime('now', '-24 hours');
```

No new schema changes. Chats that have had at least one button press in the last 24 hours
get backed up. Idle chats are skipped, keeping backup overhead minimal.

### Scheduler design

An `asyncio` background task (`run_backup_loop`) is started in FastAPI's lifespan.
It runs one cycle immediately on startup (so any missed backup is caught), then sleeps
until the next configured UTC time before repeating daily.

**Why asyncio, not cron/APScheduler?**
The app is already an `asyncio` process. A simple loop with `asyncio.sleep` avoids
adding dependencies (APScheduler, celery, etc.) and integrates naturally with FastAPI
lifespan startup/shutdown.

### Startup catch-up

On startup the loop runs `_run_backup_cycle` before entering the sleep phase. This
means if the bot restarts mid-day the backup for today still gets created (it skips
if the file already exists).

### `/load backup YYYYMMDD` command

Extends the existing `/load` command with a `backup` sub-command. The same admin
permission check that guards `/load <slot>` also applies here. If the requested date
is absent, the response lists all available backup dates.

### Purge

After each successful backup, files older than `backup_retention_days` days are
deleted. Purge runs per-chat immediately after backup, not as a separate step, to
keep the code simple and avoid a separate scheduled job.

---

## Configuration

| Setting | Env var | Default | Description |
|---|---|---|---|
| `backup_hour` | `BACKUP_HOUR` | `0` | Hour (UTC) to run daily backup |
| `backup_minute` | `BACKUP_MINUTE` | `0` | Minute (UTC) to run daily backup |
| `backup_retention_days` | `BACKUP_RETENTION_DAYS` | `30` | Days to keep backups |

---

## File Layout

```
src/
  config.py                  — added backup_hour, backup_minute, backup_retention_days,
                               get_chat_backup_dir()
  tasks/
    __init__.py
    backup_task.py            — run_backup_loop(), _run_backup_cycle()
  utils/
    backup_manager.py         — BackupManager class
  handlers/
    webhook.py                — BackupManager + task wired into lifespan
    commands.py               — /load backup YYYYMMDD branch added

data/backups/{chat_id}/backup_{YYYYMMDD}.state   (runtime)

tests/
  test_backup_manager.py
  test_backup_task.py
  test_commands.py            — TestLoadBackupCommand added
```

---

## Alternatives Considered

| Option | Rejected because |
|---|---|
| Store backups in SQLite | Large blobs bloat DB; filesystem is simpler |
| New DB table for backup metadata | No metadata needed beyond the date in the filename |
| APScheduler / celery | Extra dependencies; asyncio sleep is sufficient |
| Separate cron job | Requires OS-level setup outside the app |
| Daily backup of all chats | Wastes resources on idle chats |
