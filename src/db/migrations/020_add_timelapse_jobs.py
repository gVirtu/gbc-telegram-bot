"""Migration 020 - Add timelapse_jobs table for disk-backed timelapse queue."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS timelapse_jobs (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id             TEXT NOT NULL,
            folder_path         TEXT NOT NULL,
            timestamp           TEXT NOT NULL,
            fps                 INTEGER NOT NULL,
            compositing_context TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'pending',
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_timelapse_jobs_chat_status_created
            ON timelapse_jobs(chat_id, status, created_at ASC)
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_timelapse_jobs_chat_status_created")
    conn.execute("DROP TABLE IF EXISTS timelapse_jobs")
