"""Migration 013 - Add latest_telegram_message_id column to chat_configs."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN latest_telegram_message_id INTEGER;
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        DROP COLUMN latest_telegram_message_id;
    """)
