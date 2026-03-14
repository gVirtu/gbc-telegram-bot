"""Migration 013 - Add composite index on recent_inputs(chat_id, timestamp) for efficient purge queries."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_recent_inputs_chat_timestamp
        ON recent_inputs(chat_id, timestamp);
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_recent_inputs_chat_timestamp;")
