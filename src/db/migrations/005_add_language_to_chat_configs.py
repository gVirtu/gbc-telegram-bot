import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN language TEXT;
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        DROP COLUMN language;
    """)
