# Database Migration System

This document describes the SQLite database migration system for the Telegram GBC Bot.

## Overview

The migration system automatically manages database schema changes:

- **Auto-discovery**: Migrations are discovered from `src/db/migrations/*.py`
- **Version tracking**: Each migration has a version number and timestamp
- **Transaction safety**: Each migration runs in a transaction; failures roll back
- **Rollback support**: Migrations can optionally provide a downgrade function
- **Baseline handling**: Existing databases are detected and baseline is marked as applied

## Migration Files

Migration files follow the naming convention: `XXX_description.py`

Example: `001_baseline.py`, `002_add_user_table.py`

### Structure

Each migration file must define:

```python
"""Description of what this migration does."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply the migration."""
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY);")


def downgrade(conn: sqlite3.Connection) -> None:
    """Rollback the migration (optional)."""
    conn.execute("DROP TABLE users;")
```

## Running Migrations

Migrations run automatically when the app starts:

```python
from src.db.connection import DatabaseConnection

conn = DatabaseConnection(db_path)
conn.initialize()  # Runs all pending migrations
```

If any migration fails, the app startup is aborted with a `MigrationError`.

## Checking Migration Status

Use the CLI script to check status:

```bash
python scripts/migration_status.py
```

Output:
```
Database: data/bot.db
Current Version: 2
Applied: 2 / 2
Pending: 0

Migrations:
------------------------------------------------------------
    1  ✓ Applied  001_baseline [↓]
    2  ✓ Applied  002_add_updated_at_to_migration_history [↓]
```

## Creating New Migrations

1. Create a new file in `src/db/migrations/`
2. Use the next sequential version number
3. Implement `upgrade()` function (required)
4. Optionally implement `downgrade()` function
5. Test the migration

Example:

```python
# src/db/migrations/003_add_game_sessions.py

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE game_sessions (
            id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE game_sessions;")
```

## Rolling Back Migrations

**Warning**: Rollback is destructive and should be used with caution.

```python
from src.db.connection import DatabaseConnection
from src.db.migrations.runner import MigrationRunner

conn = DatabaseConnection(db_path)
runner = MigrationRunner(conn)
runner.run_migrations()

# Rollback version 2
runner.rollback_migration(2)
```

## Error Handling

If a migration fails:

1. The transaction is rolled back
2. The migration is NOT recorded as applied
3. A `MigrationError` is raised
4. App initialization aborts

Example error:
```
MigrationError: Migration 002_add_table (v2) failed: table already exists
```

## Existing Databases

When the migration system is first introduced to an existing database:

1. The system detects the database has existing tables
2. The baseline migration (v1) is marked as applied without running
3. Subsequent migrations are applied normally

This ensures existing deployments can adopt migrations without data loss.

## Best Practices

1. **Always provide downgrade functions** for rollback capability
2. **Test migrations** on a copy of production data
3. **Keep migrations small** and focused on one change
4. **Never modify existing migrations** that have been applied
5. **Add new migrations** to fix issues instead
6. **Use transactions** within your migration functions when needed

## Troubleshooting

### Migration fails on startup

Check the error message for the specific migration and failure reason. Common issues:
- Syntax errors in SQL
- Trying to create tables/columns that already exist
- Foreign key constraint violations

### Need to skip a migration

Mark it as applied manually (not recommended):

```sql
INSERT INTO migration_history (version, name, applied_at) 
VALUES (2, '002_problematic', datetime('now'));
```

### Database is in weird state

Check status with the CLI script, then manually fix or restore from backup.
