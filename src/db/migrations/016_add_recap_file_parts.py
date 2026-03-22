import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add part_number and is_rt columns to recap_files, changing PK to (chat_id, date, part_number, is_rt)."""
    conn.execute("""
        CREATE TABLE recap_files_new (
            chat_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            part_number INTEGER NOT NULL DEFAULT 1,
            is_rt BOOLEAN NOT NULL DEFAULT FALSE,
            file_id TEXT,
            frame_count INTEGER NOT NULL DEFAULT 0,
            duration_sec REAL NOT NULL DEFAULT 0.0,
            file_size_bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (chat_id, date, part_number, is_rt)
        );
    """)
    conn.execute("""
        INSERT INTO recap_files_new
            (chat_id, date, part_number, is_rt, file_id, frame_count,
             duration_sec, file_size_bytes, created_at, updated_at)
        SELECT chat_id, date, 1, FALSE, file_id, frame_count,
               duration_sec, file_size_bytes, created_at, updated_at
        FROM recap_files;
    """)
    conn.execute("DROP TABLE recap_files;")
    conn.execute("ALTER TABLE recap_files_new RENAME TO recap_files;")
    conn.execute("CREATE INDEX idx_recap_files_chat_id_date_is_rt ON recap_files(chat_id, date, is_rt);")
    conn.execute("CREATE INDEX idx_recap_files_chat_id ON recap_files(chat_id);")
    conn.execute("CREATE INDEX idx_recap_files_date ON recap_files(date);")


def downgrade(conn: sqlite3.Connection) -> None:
    """Revert recap_files to single-part schema."""
    conn.execute("""
        CREATE TABLE recap_files_old (
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
        INSERT INTO recap_files_old
            (chat_id, date, file_id, frame_count, duration_sec, file_size_bytes, created_at, updated_at)
        SELECT chat_id, date, file_id, frame_count, duration_sec, file_size_bytes, created_at, updated_at
        FROM recap_files
        WHERE part_number = 1 AND is_rt = FALSE;
    """)
    conn.execute("DROP TABLE recap_files;")
    conn.execute("ALTER TABLE recap_files_old RENAME TO recap_files;")
    conn.execute("CREATE UNIQUE INDEX idx_recap_files_chat_id_date ON recap_files(chat_id, date);")
    conn.execute("CREATE INDEX idx_recap_files_chat_id ON recap_files(chat_id);")
    conn.execute("CREATE INDEX idx_recap_files_date ON recap_files(date);")
