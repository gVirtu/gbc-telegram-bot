"""Migration 024 - Add modifier to recent_inputs."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "ALTER TABLE recent_inputs ADD COLUMN modifier TEXT DEFAULT NULL;"
    )


def downgrade(conn: sqlite3.Connection) -> None:
    # SQLite does not support DROP COLUMN on older versions; no-op.
    pass
