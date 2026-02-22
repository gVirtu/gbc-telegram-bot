import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create recap_files table for storing daily timelapse metadata."""
    conn.execute("""
        CREATE TABLE recap_files (
            chat_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            file_id TEXT,
            frame_count INTEGER NOT NULL DEFAULT 0,
            duration_sec REAL NOT NULL DEFAULT 0.0,
            file_size_bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (chat_id, date)
        );
    """)

    conn.execute("""
        CREATE UNIQUE INDEX idx_recap_files_chat_id_date ON recap_files(chat_id, date);
    """)

    conn.execute("""
        CREATE INDEX idx_recap_files_chat_id ON recap_files(chat_id);
    """)

    conn.execute("""
        CREATE INDEX idx_recap_files_date ON recap_files(date);
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    """Drop recap_files table and indexes."""
    conn.execute("DROP INDEX IF EXISTS idx_recap_files_date;")
    conn.execute("DROP INDEX IF EXISTS idx_recap_files_chat_id;")
    conn.execute("DROP INDEX IF EXISTS idx_recap_files_chat_id_date;")
    conn.execute("DROP TABLE IF EXISTS recap_files;")
