"""Migration 010 - Add platform column to chat_configs."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN platform TEXT NOT NULL DEFAULT 'telegram';
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        DROP COLUMN platform;
    """)
