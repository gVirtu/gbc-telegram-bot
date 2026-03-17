"""Migration 014 - Add user_preferences table for per-user settings."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE user_preferences (
            platform TEXT NOT NULL,
            user_id  INTEGER NOT NULL,
            key      TEXT NOT NULL,
            value    TEXT NOT NULL,
            PRIMARY KEY (platform, user_id, key)
        );
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS user_preferences;")
