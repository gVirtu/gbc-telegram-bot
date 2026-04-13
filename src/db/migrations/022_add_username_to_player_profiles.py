"""Migration 022 - Add user_name column to user_player_profiles."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "ALTER TABLE user_player_profiles ADD COLUMN user_name TEXT;"
    )


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE user_player_profiles DROP COLUMN user_name;")
