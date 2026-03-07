"""Migration 008 - Drop input queue tables.

The input queue is now in-memory only (PendingBuffer). These tables are no
longer written to and can be safely dropped.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Drop input queue tables."""
    conn.executescript("""
        DROP TABLE IF EXISTS input_queue_buttons;
        DROP TABLE IF EXISTS input_queue_items;
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    """Recreate input queue tables (data will be empty)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS input_queue_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            position INTEGER NOT NULL,
            user_id INTEGER,
            user_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS input_queue_buttons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_item_id INTEGER,
            button TEXT NOT NULL,
            position INTEGER NOT NULL,
            FOREIGN KEY (queue_item_id) REFERENCES input_queue_items(id) ON DELETE CASCADE
        );
    """)
