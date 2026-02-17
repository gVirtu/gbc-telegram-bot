"""Add updated_at column to migration_history table.

This is a sample migration demonstrating the migration pattern.
It adds an updated_at column to track when migration records are modified.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add updated_at column to migration_history table."""
    conn.execute("""
        ALTER TABLE migration_history 
        ADD COLUMN updated_at TIMESTAMP;
    """)
    
    # Create trigger to automatically update the timestamp
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS migration_history_update
        AFTER UPDATE ON migration_history
        BEGIN
            UPDATE migration_history 
            SET updated_at = CURRENT_TIMESTAMP 
            WHERE id = NEW.id;
        END;
    """)


def downgrade(conn: sqlite3.Connection) -> None:
    """Remove updated_at column from migration_history table.
    
    Note: SQLite doesn't support DROP COLUMN directly in older versions.
    We need to recreate the table.
    """
    # Drop the trigger first
    conn.execute("DROP TRIGGER IF EXISTS migration_history_update;")
    
    # Create new table without updated_at
    conn.execute("""
        CREATE TABLE migration_history_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reverted_at TIMESTAMP,
            CHECK (version > 0)
        );
    """)
    
    # Copy data
    conn.execute("""
        INSERT INTO migration_history_new (id, version, name, applied_at, reverted_at)
        SELECT id, version, name, applied_at, reverted_at FROM migration_history;
    """)
    
    # Drop old table
    conn.execute("DROP TABLE migration_history;")
    
    # Rename new table
    conn.execute("ALTER TABLE migration_history_new RENAME TO migration_history;")
    
    # Recreate index
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_migration_history_version 
        ON migration_history(version);
    """)
