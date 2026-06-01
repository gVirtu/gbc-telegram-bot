"""Migration 026 - Game events tracking."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS game_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id         INTEGER NOT NULL,
            cartridge_title TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            awarded_score   INTEGER NOT NULL DEFAULT 0,
            frame_offset    INTEGER NOT NULL,
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS game_event_users (
            event_id  INTEGER NOT NULL REFERENCES game_events(id) ON DELETE CASCADE,
            platform  TEXT NOT NULL,
            user_id   INTEGER NOT NULL,
            PRIMARY KEY (event_id, platform, user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_game_events_chat_frame ON game_events(chat_id, frame_offset);
        """
    )


def downgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP INDEX IF EXISTS idx_game_events_chat_frame;
        DROP TABLE IF EXISTS game_event_users;
        DROP TABLE IF EXISTS game_events;
        """
    )
