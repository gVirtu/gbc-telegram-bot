"""Migration 007: Replace running_mode with modifier_states in chat_configs.

Adds a modifier_states JSON column, migrates existing running_mode=1 rows
to {"run": true}, then drops the running_mode column.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add modifier_states column, migrate data, drop running_mode."""
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN modifier_states TEXT NOT NULL DEFAULT '{}';
    """)
    conn.execute("""
        UPDATE chat_configs
        SET modifier_states = '{"run": true}'
        WHERE running_mode = 1;
    """)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(chat_configs);").fetchall()]
    if "running_mode" in columns:
        conn.execute("ALTER TABLE chat_configs DROP COLUMN running_mode;")


def downgrade(conn: sqlite3.Connection) -> None:
    """Restore running_mode column from modifier_states."""
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN running_mode BOOLEAN NOT NULL DEFAULT 0;
    """)
    conn.execute("""
        UPDATE chat_configs
        SET running_mode = 1
        WHERE json_extract(modifier_states, '$.run') = 1;
    """)
    conn.execute("ALTER TABLE chat_configs DROP COLUMN modifier_states;")
