"""Database schema definitions for SQLite migration."""

# Schema version for migrations
SCHEMA_VERSION = 1

CREATE_TABLES_SQL = """
-- Chat configurations
CREATE TABLE IF NOT EXISTS chat_configs (
    chat_id INTEGER PRIMARY KEY,
    input_hold_frames INTEGER,
    animation_duration INTEGER,
    auto_save_enabled BOOLEAN DEFAULT 1,
    running_mode BOOLEAN DEFAULT 0,
    message_base_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Game states
CREATE TABLE IF NOT EXISTS game_states (
    chat_id INTEGER PRIMARY KEY,
    message_id INTEGER,
    input_in_progress BOOLEAN DEFAULT 0,
    last_input TEXT,
    last_input_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User input counts per chat
CREATE TABLE IF NOT EXISTS user_input_counts (
    chat_id INTEGER,
    user_id INTEGER,
    input_count INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id),
    FOREIGN KEY (chat_id) REFERENCES game_states(chat_id) ON DELETE CASCADE
);

-- Recent inputs (FIFO, max 3 per chat managed by application)
CREATE TABLE IF NOT EXISTS recent_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    user_id INTEGER,
    user_name TEXT,
    button TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES game_states(chat_id) ON DELETE CASCADE
);

-- Input queue items
CREATE TABLE IF NOT EXISTS input_queue_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    position INTEGER NOT NULL,
    user_id INTEGER,
    user_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES game_states(chat_id) ON DELETE CASCADE
);

-- Buttons within queue items
CREATE TABLE IF NOT EXISTS input_queue_buttons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_item_id INTEGER,
    button TEXT NOT NULL,
    position INTEGER NOT NULL,
    FOREIGN KEY (queue_item_id) REFERENCES input_queue_items(id) ON DELETE CASCADE
);

-- Save slots metadata
CREATE TABLE IF NOT EXISTS save_slots (
    chat_id INTEGER,
    slot_number INTEGER,
    is_auto_save BOOLEAN DEFAULT 0,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    state_file_path TEXT NOT NULL,
    PRIMARY KEY (chat_id, slot_number),
    FOREIGN KEY (chat_id) REFERENCES game_states(chat_id) ON DELETE CASCADE
);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_user_counts_chat ON user_input_counts(chat_id);
CREATE INDEX IF NOT EXISTS idx_recent_inputs_chat ON recent_inputs(chat_id);
CREATE INDEX IF NOT EXISTS idx_queue_items_chat ON input_queue_items(chat_id);
CREATE INDEX IF NOT EXISTS idx_queue_buttons_item ON input_queue_buttons(queue_item_id);
CREATE INDEX IF NOT EXISTS idx_save_slots_chat ON save_slots(chat_id);
"""


def get_schema_sql() -> str:
    """Get complete schema SQL for fresh database creation."""
    return CREATE_TABLES_SQL + INDEXES_SQL


def get_schema_version_sql() -> str:
    """Get SQL to record schema version."""
    return f"INSERT OR REPLACE INTO schema_version (version) VALUES ({SCHEMA_VERSION});"
