"""Migration 015 - Add scoring columns to recent_inputs and create user_player_profiles."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE recent_inputs ADD COLUMN base_score INTEGER NOT NULL DEFAULT 0;")
    conn.execute("ALTER TABLE recent_inputs ADD COLUMN streak_bonus INTEGER NOT NULL DEFAULT 0;")
    conn.execute("ALTER TABLE recent_inputs ADD COLUMN total_score INTEGER NOT NULL DEFAULT 0;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_player_profiles (
            platform TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            total_score_earned INTEGER NOT NULL DEFAULT 0,
            total_score_spent INTEGER NOT NULL DEFAULT 0,
            current_streak INTEGER NOT NULL DEFAULT 0,
            best_streak INTEGER NOT NULL DEFAULT 0,
            best_streak_date TEXT,
            last_input_at TEXT,
            PRIMARY KEY (platform, user_id)
        );
    """)
    conn.execute("""
        CREATE UNIQUE INDEX idx_user_player_profiles_platform_user_id ON user_player_profiles(platform, user_id);
    """)


def downgrade(conn: sqlite3.Connection) -> None:

    conn.execute("DROP TABLE IF EXISTS user_player_profiles;")

    conn.execute("""
        ALTER TABLE recent_inputs
        DROP COLUMN base_score;
    """)
    conn.execute("""
        ALTER TABLE recent_inputs
        DROP COLUMN streak_bonus;
    """)
    conn.execute("""
        ALTER TABLE recent_inputs
        DROP COLUMN total_score;
    """)
