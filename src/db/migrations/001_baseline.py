"""Baseline migration - creates the initial schema.

This migration creates the schema as it exists at version 1.
For new databases, this runs first. For existing databases with
schema version 1, this will be marked as applied without running.
"""

import sqlite3
from src.db.schema import get_schema_sql


def upgrade(conn: sqlite3.Connection) -> None:
    """Create initial database schema."""
    conn.executescript(get_schema_sql())


def downgrade(conn: sqlite3.Connection) -> None:
    """Drop all tables (destructive - use with caution)."""
    conn.executescript("""
        DROP TABLE IF EXISTS input_queue_buttons;
        DROP TABLE IF EXISTS input_queue_items;
        DROP TABLE IF EXISTS recent_inputs;
        DROP TABLE IF EXISTS user_input_counts;
        DROP TABLE IF EXISTS save_slots;
        DROP TABLE IF EXISTS chat_configs;
        DROP TABLE IF EXISTS game_states;
        DROP TABLE IF EXISTS schema_version;
        DROP TABLE IF EXISTS migration_history;
    """)
