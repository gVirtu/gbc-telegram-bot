"""Migration 021 - Add auto_sent_at column to recap_files."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE recap_files ADD COLUMN auto_sent_at TEXT;")


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE recap_files DROP COLUMN auto_sent_at;")
