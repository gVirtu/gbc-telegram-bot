"""Migration 012 - Add last_animation_file_id column to game_states."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE game_states
        ADD COLUMN last_animation_file_id TEXT;
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE game_states
        DROP COLUMN last_animation_file_id;
    """)
