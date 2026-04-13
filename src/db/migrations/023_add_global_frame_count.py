"""Migration 023 - Add global_frame_count to game_states."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "ALTER TABLE game_states ADD COLUMN global_frame_count INTEGER NOT NULL DEFAULT 0;"
    )


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE game_states DROP COLUMN global_frame_count;")
