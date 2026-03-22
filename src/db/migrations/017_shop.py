"""Migration 017 - Add name_tag_color to user_player_profiles."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "ALTER TABLE user_player_profiles "
        "ADD COLUMN name_tag_color TEXT NOT NULL DEFAULT '#FFFFFF';"
    )


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE user_player_profiles_bak AS "
        "SELECT platform, user_id, total_score_earned, total_score_spent, "
        "current_streak, best_streak, best_streak_date, last_input_at "
        "FROM user_player_profiles;"
    )
    conn.execute("DROP TABLE user_player_profiles;")
    conn.execute(
        "ALTER TABLE user_player_profiles_bak RENAME TO user_player_profiles;"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_user_player_profiles_platform_user_id "
        "ON user_player_profiles(platform, user_id);"
    )
