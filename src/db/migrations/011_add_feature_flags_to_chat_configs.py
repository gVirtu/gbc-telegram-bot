"""Migration 011 - Add feature_flags and last_avatar_update_at columns to chat_configs."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN feature_flags TEXT NOT NULL DEFAULT '{}';
    """)
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN last_avatar_update_at TIMESTAMP;
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        DROP COLUMN feature_flags;
    """)
    conn.execute("""
        ALTER TABLE chat_configs
        DROP COLUMN last_avatar_update_at;
    """)
