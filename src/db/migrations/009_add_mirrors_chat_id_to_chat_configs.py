"""Migration 009 - Add mirrors_chat_id column to chat_configs.

A mirror chat shares a game with a leader chat: all game updates broadcast
to the leader and all mirrors, while inputs from any mirror are proxied to
the leader's game controller.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        ALTER TABLE chat_configs
        ADD COLUMN mirrors_chat_id INTEGER NULL REFERENCES chat_configs(chat_id);
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_configs_mirrors_chat_id
        ON chat_configs(mirrors_chat_id);
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        DROP INDEX IF EXISTS idx_chat_configs_mirrors_chat_id;
    """)
    conn.execute("""
        ALTER TABLE chat_configs
        DROP COLUMN mirrors_chat_id;
    """)
