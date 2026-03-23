"""Migration 019 - Add shop_transactions table."""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shop_transactions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            platform     TEXT    NOT NULL,
            user_id      INTEGER NOT NULL,
            item_id      TEXT    NOT NULL,
            pts_spent    INTEGER NOT NULL,
            purchased_at TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_shop_transactions_lookup
            ON shop_transactions(platform, user_id, item_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_shop_transactions_purchased_at
            ON shop_transactions(purchased_at, platform, user_id)
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_shop_transactions_lookup;")
    conn.execute("DROP INDEX IF EXISTS idx_shop_transactions_purchased_at;")
    conn.execute("DROP TABLE IF EXISTS shop_transactions;")
