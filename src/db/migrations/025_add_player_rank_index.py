"""Migration 025 - Add composite index for player rank queries."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_counts_chat_count "
        "ON user_input_counts(chat_id, input_count DESC);"
    )


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_user_counts_chat_count;")
