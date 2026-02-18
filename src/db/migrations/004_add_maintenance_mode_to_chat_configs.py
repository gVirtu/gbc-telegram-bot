import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN maintenance_mode INTEGER DEFAULT 0;
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        DROP COLUMN maintenance_mode;
    """)
