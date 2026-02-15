# SQLite Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate bot state storage from JSON files to SQLite database with hybrid filesystem storage for binary save states.

**Architecture:** 
- SQLite database stores all structured data (chat configs, game states, user input counts, recent inputs, input queue, save slot metadata)
- Binary PyBoy save state files remain on filesystem, referenced by path in database
- Big-bang migration: one-time import script converts all existing JSON data

**Tech Stack:** Python 3.11, sqlite3 (stdlib), aiosqlite for async support, pytest for testing

---

## Directory Structure

```
src/
├── db/
│   ├── __init__.py           # Exports DatabaseManager
│   ├── schema.py             # SQL schema definitions
│   ├── connection.py         # Database connection management
│   └── manager.py            # DatabaseManager class
scripts/
└── migrate_to_sqlite.py      # One-time migration script
tests/
├── db/
│   ├── test_schema.py
│   ├── test_connection.py
│   └── test_manager.py
└── test_migration_script.py
```

---

## Task 1: Database Schema Module

**Files:**
- Create: `src/db/schema.py`

**Step 1: Write schema definitions**

```python
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
    frame_hash TEXT,
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
```

**Step 2: Create test file**

**Files:**
- Create: `tests/db/test_schema.py`

```python
"""Tests for database schema."""
import sqlite3
import pytest
from src.db.schema import get_schema_sql, SCHEMA_VERSION


def test_schema_creates_all_tables(tmp_path):
    """Verify schema creates all expected tables."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    conn.executescript(get_schema_sql())
    
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    
    expected = {
        'chat_configs', 'game_states', 'user_input_counts',
        'recent_inputs', 'input_queue_items', 'input_queue_buttons',
        'save_slots', 'schema_version'
    }
    assert expected.issubset(tables)
    conn.close()


def test_schema_creates_indexes(tmp_path):
    """Verify schema creates expected indexes."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    conn.executescript(get_schema_sql())
    
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index';")
    indexes = {row[0] for row in cursor.fetchall()}
    
    assert 'idx_user_counts_chat' in indexes
    assert 'idx_recent_inputs_chat' in indexes
    conn.close()


def test_foreign_keys_enabled(tmp_path):
    """Verify foreign key constraints are enforced."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(get_schema_sql())
    
    # Should fail due to foreign key constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO user_input_counts (chat_id, user_id, input_count) VALUES (999, 1, 5);"
        )
    conn.close()
```

**Step 3: Run tests to verify they fail**

Run: `pytest tests/db/test_schema.py -v`
Expected: FAIL - ModuleNotFoundError: No module named 'src.db.schema'

**Step 4: Create schema module**

Save the schema code from Step 1 to `src/db/schema.py`.

**Step 5: Run tests to verify they pass**

Run: `pytest tests/db/test_schema.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/db/schema.py tests/db/test_schema.py
git commit -m "feat(db): add SQLite database schema definitions"
```

---

## Task 2: Database Connection Module

**Files:**
- Create: `src/db/connection.py`
- Create: `tests/db/test_connection.py`

**Step 1: Write failing test**

```python
"""Tests for database connection management."""
import sqlite3
import pytest
from pathlib import Path
from src.db.connection import DatabaseConnection, get_db_path


def test_get_db_path_returns_path_in_data_dir(tmp_path):
    """Verify database path is in data directory."""
    from src.config import Settings
    
    settings = Settings(data_dir=tmp_path, rom_path=tmp_path / "test.gbc")
    db_path = get_db_path(settings)
    
    assert db_path.parent == tmp_path
    assert db_path.name == "bot.db"


def test_database_connection_initializes_schema(tmp_path):
    """Verify connection initializes database with schema."""
    db_path = tmp_path / "test.db"
    
    conn = DatabaseConnection(db_path)
    conn.initialize()
    
    # Verify tables exist
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert 'game_states' in tables
    assert 'chat_configs' in tables
    
    conn.close()


def test_database_connection_context_manager(tmp_path):
    """Verify context manager properly closes connection."""
    db_path = tmp_path / "test.db"
    
    with DatabaseConnection(db_path) as conn:
        conn.initialize()
        cursor = conn.execute("SELECT 1;")
        assert cursor.fetchone()[0] == 1
    
    # Connection should be closed after context manager exits
    assert conn._connection is None


def test_database_connection_foreign_keys_enabled(tmp_path):
    """Verify foreign keys are enabled by default."""
    db_path = tmp_path / "test.db"
    
    conn = DatabaseConnection(db_path)
    conn.initialize()
    
    cursor = conn.execute("PRAGMA foreign_keys;")
    assert cursor.fetchone()[0] == 1
    
    conn.close()


def test_get_connection_creates_if_none(tmp_path):
    """Verify get_connection creates connection if not exists."""
    db_path = tmp_path / "test.db"
    
    conn = DatabaseConnection(db_path)
    assert conn._connection is None
    
    connection = conn.get_connection()
    assert connection is not None
    assert conn._connection is connection
    
    conn.close()
```

**Step 2: Run tests**

Run: `pytest tests/db/test_connection.py -v`
Expected: FAIL - ModuleNotFoundError

**Step 3: Implement connection module**

```python
"""Database connection management for SQLite."""

import sqlite3
import logging
from pathlib import Path
from typing import Optional

from src.db.schema import get_schema_sql, get_schema_version_sql

logger = logging.getLogger(__name__)


def get_db_path(settings) -> Path:
    """Get database file path from settings.
    
    Args:
        settings: Application settings with data_dir
        
    Returns:
        Path to SQLite database file
    """
    return settings.data_dir / "bot.db"


class DatabaseConnection:
    """Manages SQLite database connections.
    
    Handles connection lifecycle, schema initialization,
    and provides context manager support.
    
    Example:
        >>> conn = DatabaseConnection(Path("data/bot.db"))
        >>> conn.initialize()
        >>> conn.execute("SELECT 1;")
        >>> conn.close()
    """
    
    def __init__(self, db_path: Path):
        """Initialize database connection manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None
    
    def get_connection(self) -> sqlite3.Connection:
        """Get or create database connection.
        
        Returns:
            SQLite connection with foreign keys enabled
        """
        if self._connection is None:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            
            self._connection = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            # Enable foreign keys
            self._connection.execute("PRAGMA foreign_keys = ON;")
            # Return rows as sqlite3.Row for dict-like access
            self._connection.row_factory = sqlite3.Row
            
            logger.debug(f"Opened database connection to {self.db_path}")
        
        return self._connection
    
    def initialize(self) -> None:
        """Initialize database with schema.
        
        Creates tables and indexes if they don't exist.
        Safe to call multiple times (idempotent).
        """
        conn = self.get_connection()
        
        # Execute schema creation
        conn.executescript(get_schema_sql())
        conn.executescript(get_schema_version_sql())
        conn.commit()
        
        logger.info(f"Initialized database at {self.db_path}")
    
    def execute(self, sql: str, parameters: tuple = ()) -> sqlite3.Cursor:
        """Execute SQL statement.
        
        Args:
            sql: SQL statement to execute
            parameters: Query parameters
            
        Returns:
            Cursor object
        """
        conn = self.get_connection()
        return conn.execute(sql, parameters)
    
    def executescript(self, sql: str) -> sqlite3.Cursor:
        """Execute multiple SQL statements.
        
        Args:
            sql: SQL script to execute
            
        Returns:
            Cursor object
        """
        conn = self.get_connection()
        return conn.executescript(sql)
    
    def commit(self) -> None:
        """Commit current transaction."""
        if self._connection:
            self._connection.commit()
    
    def close(self) -> None:
        """Close database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.debug("Closed database connection")
    
    def __enter__(self):
        """Context manager entry."""
        self.get_connection()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type:
            # Exception occurred, rollback
            if self._connection:
                self._connection.rollback()
        else:
            # No exception, commit
            self.commit()
        self.close()
        return False  # Don't suppress exceptions
```

**Step 4: Run tests**

Run: `pytest tests/db/test_connection.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/db/connection.py tests/db/test_connection.py
git commit -m "feat(db): add database connection management"
```

---

## Task 3: Database Manager Core

**Files:**
- Create: `src/db/manager.py`
- Create: `tests/db/test_manager.py`

**Step 1: Write tests for ChatConfig operations**

```python
"""Tests for DatabaseManager."""
import pytest
from datetime import datetime
from pathlib import Path

from src.db.manager import DatabaseManager
from src.models.game_state import ChatConfig


@pytest.fixture
def db_manager(tmp_path):
    """Create a DatabaseManager with temporary database."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    yield manager
    manager.close()


class TestChatConfigOperations:
    """Test chat configuration CRUD operations."""
    
    def test_save_chat_config_creates_new(self, db_manager):
        """Verify saving new config creates row."""
        config = ChatConfig(
            chat_id=123,
            input_hold_frames=10,
            animation_duration=5,
            auto_save_enabled=True,
            running_mode=False
        )
        
        db_manager.save_chat_config(config)
        
        loaded = db_manager.load_chat_config(123)
        assert loaded is not None
        assert loaded.chat_id == 123
        assert loaded.input_hold_frames == 10
        assert loaded.auto_save_enabled is True
    
    def test_load_chat_config_nonexistent_returns_none(self, db_manager):
        """Verify loading nonexistent config returns None."""
        result = db_manager.load_chat_config(999)
        assert result is None
    
    def test_save_chat_config_updates_existing(self, db_manager):
        """Verify saving existing config updates row."""
        config1 = ChatConfig(chat_id=123, input_hold_frames=10)
        db_manager.save_chat_config(config1)
        
        config2 = ChatConfig(chat_id=123, input_hold_frames=20)
        db_manager.save_chat_config(config2)
        
        loaded = db_manager.load_chat_config(123)
        assert loaded.input_hold_frames == 20
    
    def test_get_or_create_chat_config_creates_default(self, db_manager):
        """Verify get_or_create creates default config."""
        config = db_manager.get_or_create_chat_config(123)
        
        assert config.chat_id == 123
        assert config.input_hold_frames is None
        assert config.auto_save_enabled is True
        assert config.created_at is not None
    
    def test_get_or_create_chat_config_returns_existing(self, db_manager):
        """Verify get_or_create returns existing config."""
        original = ChatConfig(chat_id=123, input_hold_frames=15)
        db_manager.save_chat_config(original)
        
        loaded = db_manager.get_or_create_chat_config(123)
        assert loaded.input_hold_frames == 15
```

**Step 2: Run tests**

Run: `pytest tests/db/test_manager.py::TestChatConfigOperations -v`
Expected: FAIL - ModuleNotFoundError

**Step 3: Implement DatabaseManager with ChatConfig support**

```python
"""Database manager for SQLite persistence.

This module provides a DatabaseManager class that replaces file-based
JSON storage with SQLite, maintaining the same public API as StateManager.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.db.connection import DatabaseConnection
from src.models.game_state import ChatConfig, ChatGameState, SaveSlotInfo, GameButton
from src.models.input_queue import InputQueue, QueueItem

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite persistence for game state.
    
    This class provides the same interface as the original StateManager
    but uses SQLite instead of JSON files for structured data.
    Binary save state files remain on the filesystem.
    
    Example:
        >>> manager = DatabaseManager()
        >>> manager.initialize()
        >>> manager.save_chat_config(ChatConfig(chat_id=123))
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """Initialize the database manager.
        
        Args:
            db_path: Path to SQLite database. If None, uses settings.
        """
        if db_path is None:
            from src.config import settings
            db_path = Path(settings.data_dir) / "bot.db"
        
        self.connection = DatabaseConnection(db_path)
    
    def initialize(self) -> None:
        """Initialize database schema.
        
        Safe to call multiple times. Creates tables if they don't exist.
        """
        self.connection.initialize()
    
    def close(self) -> None:
        """Close database connection."""
        self.connection.close()
    
    # ==================== Chat Config ====================
    
    def save_chat_config(self, config: ChatConfig) -> None:
        """Save chat configuration to database.
        
        Args:
            config: The chat configuration to save
        """
        sql = """
        INSERT INTO chat_configs 
            (chat_id, input_hold_frames, animation_duration, auto_save_enabled, running_mode, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            input_hold_frames = excluded.input_hold_frames,
            animation_duration = excluded.animation_duration,
            auto_save_enabled = excluded.auto_save_enabled,
            running_mode = excluded.running_mode,
            updated_at = excluded.updated_at;
        """
        
        self.connection.execute(sql, (
            config.chat_id,
            config.input_hold_frames,
            config.animation_duration,
            1 if config.auto_save_enabled else 0,
            1 if config.running_mode else 0,
            config.created_at.isoformat() if config.created_at else datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat()
        ))
        self.connection.commit()
        logger.debug(f"Saved chat config for chat {config.chat_id}")
    
    def load_chat_config(self, chat_id: int) -> Optional[ChatConfig]:
        """Load chat configuration from database.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            The saved configuration, or None if not found
        """
        sql = "SELECT * FROM chat_configs WHERE chat_id = ?;"
        cursor = self.connection.execute(sql, (chat_id,))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        config = ChatConfig(
            chat_id=row['chat_id'],
            input_hold_frames=row['input_hold_frames'],
            animation_duration=row['animation_duration'],
            auto_save_enabled=bool(row['auto_save_enabled']),
            running_mode=bool(row['running_mode']),
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at'])
        )
        
        logger.debug(f"Loaded chat config for chat {chat_id}")
        return config
    
    def get_or_create_chat_config(self, chat_id: int) -> ChatConfig:
        """Get existing config or create default.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            Existing or new ChatConfig
        """
        config = self.load_chat_config(chat_id)
        if config is None:
            config = ChatConfig(chat_id=chat_id)
            self.save_chat_config(config)
        return config
```

**Step 4: Run tests**

Run: `pytest tests/db/test_manager.py::TestChatConfigOperations -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/db/manager.py tests/db/test_manager.py
git commit -m "feat(db): add DatabaseManager with ChatConfig CRUD operations"
```

---

## Task 4: Database Manager - Game State Operations

**Step 1: Write tests for GameState operations**

```python
class TestGameStateOperations:
    """Test game state CRUD operations."""
    
    def test_save_game_state_creates_new(self, db_manager):
        """Verify saving new game state creates row."""
        state = ChatGameState(
            chat_id=123,
            message_id=456,
            input_in_progress=True,
            last_input=GameButton.A,
            frame_hash="abc123"
        )
        
        db_manager.save_game_state(state)
        
        loaded = db_manager.load_game_state(123)
        assert loaded is not None
        assert loaded.chat_id == 123
        assert loaded.message_id == 456
        assert loaded.input_in_progress is True
        assert loaded.last_input == GameButton.A
        assert loaded.frame_hash == "abc123"
    
    def test_load_game_state_nonexistent_returns_none(self, db_manager):
        """Verify loading nonexistent state returns None."""
        result = db_manager.load_game_state(999)
        assert result is None
    
    def test_save_game_state_updates_existing(self, db_manager):
        """Verify saving existing state updates row."""
        state1 = ChatGameState(chat_id=123, message_id=100)
        db_manager.save_game_state(state1)
        
        state2 = ChatGameState(chat_id=123, message_id=200)
        db_manager.save_game_state(state2)
        
        loaded = db_manager.load_game_state(123)
        assert loaded.message_id == 200
    
    def test_delete_game_state(self, db_manager):
        """Verify delete removes game state."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        deleted = db_manager.delete_game_state(123)
        assert deleted is True
        
        loaded = db_manager.load_game_state(123)
        assert loaded is None
    
    def test_delete_game_state_nonexistent_returns_false(self, db_manager):
        """Verify deleting nonexistent state returns False."""
        result = db_manager.delete_game_state(999)
        assert result is False
```

**Step 2: Run tests**

Run: `pytest tests/db/test_manager.py::TestGameStateOperations -v`
Expected: FAIL - methods not implemented

**Step 3: Add GameState methods to DatabaseManager**

Add these methods to `src/db/manager.py`:

```python
    # ==================== Game State ====================
    
    def save_game_state(self, state: ChatGameState) -> None:
        """Save game state to database.
        
        Args:
            state: The game state to save
        """
        sql = """
        INSERT INTO game_states 
            (chat_id, message_id, input_in_progress, last_input, last_input_time, frame_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            message_id = excluded.message_id,
            input_in_progress = excluded.input_in_progress,
            last_input = excluded.last_input,
            last_input_time = excluded.last_input_time,
            frame_hash = excluded.frame_hash,
            updated_at = excluded.updated_at;
        """
        
        self.connection.execute(sql, (
            state.chat_id,
            state.message_id,
            1 if state.input_in_progress else 0,
            state.last_input.value if state.last_input else None,
            state.last_input_time.isoformat() if state.last_input_time else None,
            state.frame_hash,
            state.created_at.isoformat() if state.created_at else datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat()
        ))
        
        # Save user input counts
        self._save_user_input_counts(state.chat_id, state.user_input_counts)
        
        # Save recent inputs
        self._save_recent_inputs(state.chat_id, state.recent_inputs)
        
        # Save input queue if exists
        if state.input_queue:
            self._save_input_queue(state.chat_id, state.input_queue)
        
        self.connection.commit()
        logger.debug(f"Saved game state for chat {state.chat_id}")
    
    def load_game_state(self, chat_id: int) -> Optional[ChatGameState]:
        """Load game state from database.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            The saved game state, or None if not found
        """
        sql = "SELECT * FROM game_states WHERE chat_id = ?;"
        cursor = self.connection.execute(sql, (chat_id,))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        state = ChatGameState(
            chat_id=row['chat_id'],
            message_id=row['message_id'],
            input_in_progress=bool(row['input_in_progress']),
            last_input=GameButton(row['last_input']) if row['last_input'] else None,
            last_input_time=datetime.fromisoformat(row['last_input_time']) if row['last_input_time'] else None,
            frame_hash=row['frame_hash'],
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
            user_input_counts=self._load_user_input_counts(chat_id),
            recent_inputs=self._load_recent_inputs(chat_id),
            input_queue=self._load_input_queue(chat_id)
        )
        
        logger.debug(f"Loaded game state for chat {chat_id}")
        return state
    
    def delete_game_state(self, chat_id: int) -> bool:
        """Delete game state for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            True if deleted, False if didn't exist
        """
        sql = "DELETE FROM game_states WHERE chat_id = ?;"
        cursor = self.connection.execute(sql, (chat_id,))
        self.connection.commit()
        
        if cursor.rowcount > 0:
            logger.debug(f"Deleted game state for chat {chat_id}")
            return True
        return False
    
    def _save_user_input_counts(self, chat_id: int, counts: dict) -> None:
        """Save user input counts to database."""
        # Delete existing counts
        self.connection.execute(
            "DELETE FROM user_input_counts WHERE chat_id = ?;", 
            (chat_id,)
        )
        
        # Insert new counts
        for user_id_str, count in counts.items():
            user_id = int(user_id_str)  # Convert from string to int
            self.connection.execute(
                "INSERT INTO user_input_counts (chat_id, user_id, input_count) VALUES (?, ?, ?);",
                (chat_id, user_id, count)
            )
    
    def _load_user_input_counts(self, chat_id: int) -> dict:
        """Load user input counts from database."""
        cursor = self.connection.execute(
            "SELECT user_id, input_count FROM user_input_counts WHERE chat_id = ?;",
            (chat_id,)
        )
        return {str(row['user_id']): row['input_count'] for row in cursor.fetchall()}
    
    def _save_recent_inputs(self, chat_id: int, inputs: list) -> None:
        """Save recent inputs to database."""
        # Delete existing inputs
        self.connection.execute(
            "DELETE FROM recent_inputs WHERE chat_id = ?;",
            (chat_id,)
        )
        
        # Insert new inputs
        for inp in inputs:
            self.connection.execute(
                """INSERT INTO recent_inputs 
                    (chat_id, user_id, user_name, button, timestamp) 
                   VALUES (?, ?, ?, ?, ?);""",
                (chat_id, inp['user_id'], inp['user_name'], inp['buttons'][0] if inp['buttons'] else None, inp['timestamp'])
            )
    
    def _load_recent_inputs(self, chat_id: int) -> list:
        """Load recent inputs from database."""
        cursor = self.connection.execute(
            """SELECT user_id, user_name, button, timestamp 
               FROM recent_inputs WHERE chat_id = ? ORDER BY timestamp;""",
            (chat_id,)
        )
        
        inputs = []
        for row in cursor.fetchall():
            inputs.append({
                'user_id': row['user_id'],
                'user_name': row['user_name'],
                'buttons': [row['button']] if row['button'] else [],
                'timestamp': row['timestamp']
            })
        return inputs
```

**Step 4: Run tests**

Run: `pytest tests/db/test_manager.py::TestGameStateOperations -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/db/manager.py tests/db/test_manager.py
git commit -m "feat(db): add GameState CRUD operations with user input tracking"
```

---

## Task 5: Database Manager - Input Queue Operations

**Step 1: Write tests for InputQueue operations**

```python
class TestInputQueueOperations:
    """Test input queue persistence operations."""
    
    def test_save_input_queue_with_items(self, db_manager):
        """Verify saving input queue with items."""
        from src.models.input_queue import InputQueue, QueueItem
        from src.models.game_state import GameButton
        
        # Need game state first (foreign key constraint)
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        queue = InputQueue()
        queue.add_input(456, "Alice", GameButton.A)
        queue.add_input(789, "Bob", GameButton.B)
        
        db_manager._save_input_queue(123, queue)
        
        loaded_queue = db_manager._load_input_queue(123)
        assert loaded_queue is not None
        assert len(loaded_queue.items) == 2
        assert loaded_queue.items[0].user_name == "Alice"
        assert loaded_queue.items[1].user_name == "Bob"
    
    def test_load_input_queue_empty(self, db_manager):
        """Verify loading empty input queue returns None."""
        queue = db_manager._load_input_queue(123)
        assert queue is None
    
    def test_save_input_queue_with_multiple_buttons(self, db_manager):
        """Verify queue items can have multiple buttons."""
        from src.models.input_queue import InputQueue
        from src.models.game_state import GameButton
        
        # Need game state first
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        queue = InputQueue()
        queue.add_input(456, "Alice", GameButton.A)
        queue.add_input(456, "Alice", GameButton.B)  # Same user extends item
        
        db_manager._save_input_queue(123, queue)
        
        loaded_queue = db_manager._load_input_queue(123)
        assert len(loaded_queue.items) == 1
        assert len(loaded_queue.items[0].buttons) == 2
        assert loaded_queue.items[0].buttons[0] == GameButton.A
        assert loaded_queue.items[0].buttons[1] == GameButton.B
```

**Step 2: Run tests**

Run: `pytest tests/db/test_manager.py::TestInputQueueOperations -v`
Expected: FAIL - methods not implemented

**Step 3: Add InputQueue methods to DatabaseManager**

Add these methods to `src/db/manager.py`:

```python
    def _save_input_queue(self, chat_id: int, queue: InputQueue) -> None:
        """Save input queue to database."""
        # Delete existing queue items (cascade deletes buttons)
        self.connection.execute(
            "DELETE FROM input_queue_items WHERE chat_id = ?;",
            (chat_id,)
        )
        
        # Insert queue items
        for position, item in enumerate(queue.items):
            cursor = self.connection.execute(
                """INSERT INTO input_queue_items 
                    (chat_id, position, user_id, user_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?);""",
                (chat_id, position, item.user_id, item.user_name, 
                 item.created_at.isoformat(), item.updated_at.isoformat())
            )
            item_id = cursor.lastrowid
            
            # Insert buttons for this item
            for btn_position, button in enumerate(item.buttons):
                self.connection.execute(
                    """INSERT INTO input_queue_buttons 
                        (queue_item_id, button, position)
                       VALUES (?, ?, ?);""",
                    (item_id, button.value, btn_position)
                )
    
    def _load_input_queue(self, chat_id: int) -> Optional[InputQueue]:
        """Load input queue from database."""
        cursor = self.connection.execute(
            """SELECT id, position, user_id, user_name, created_at, updated_at
               FROM input_queue_items
               WHERE chat_id = ?
               ORDER BY position;""",
            (chat_id,)
        )
        
        items = []
        for row in cursor.fetchall():
            # Load buttons for this item
            btn_cursor = self.connection.execute(
                """SELECT button FROM input_queue_buttons
                   WHERE queue_item_id = ?
                   ORDER BY position;""",
                (row['id'],)
            )
            buttons = [GameButton(btn_row['button']) for btn_row in btn_cursor.fetchall()]
            
            item = QueueItem(
                user_id=row['user_id'],
                user_name=row['user_name'],
                buttons=buttons,
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at'])
            )
            items.append(item)
        
        if not items:
            return None
        
        queue = InputQueue()
        queue.items = items
        return queue
```

**Step 4: Run tests**

Run: `pytest tests/db/test_manager.py::TestInputQueueOperations -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/db/manager.py tests/db/test_manager.py
git commit -m "feat(db): add input queue persistence operations"
```

---

## Task 6: Database Manager - Save Slots Operations

**Step 1: Write tests for SaveSlots operations**

```python
class TestSaveSlotOperations:
    """Test save slot operations."""
    
    def test_save_to_slot_creates_metadata(self, db_manager, tmp_path):
        """Verify save creates slot metadata in database."""
        # Need game state first
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        state_data = b"fake_state_data"
        state_file_path = tmp_path / "state_file.state"
        
        info = db_manager.save_to_slot(
            chat_id=123,
            slot_number=0,
            state_data=state_data,
            state_file_path=state_file_path,
            description="Test save",
            is_auto_save=True
        )
        
        assert info.slot_number == 0
        assert info.is_auto_save is True
        assert info.description == "Test save"
        
        # Verify file was created
        assert state_file_path.exists()
        assert state_file_path.read_bytes() == state_data
    
    def test_get_slot_info(self, db_manager, tmp_path):
        """Verify loading slot info."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        db_manager.save_to_slot(
            chat_id=123,
            slot_number=1,
            state_data=b"data",
            state_file_path=tmp_path / "slot1.state",
            description="Manual save"
        )
        
        info = db_manager.get_slot_info(123, 1)
        assert info is not None
        assert info.slot_number == 1
        assert info.description == "Manual save"
        assert info.is_auto_save is False
    
    def test_list_save_slots(self, db_manager, tmp_path):
        """Verify listing save slots."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        db_manager.save_to_slot(123, 0, b"data1", tmp_path / "slot0.state")
        db_manager.save_to_slot(123, 2, b"data2", tmp_path / "slot2.state")
        
        slots = db_manager.list_save_slots(123)
        assert len(slots) == 2
        slot_numbers = [s.slot_number for s in slots]
        assert 0 in slot_numbers
        assert 2 in slot_numbers
    
    def test_delete_slot(self, db_manager, tmp_path):
        """Verify deleting slot removes metadata and file."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        state_file = tmp_path / "slot0.state"
        db_manager.save_to_slot(123, 0, b"data", state_file)
        
        deleted = db_manager.delete_slot(123, 0)
        assert deleted is True
        
        info = db_manager.get_slot_info(123, 0)
        assert info is None
        assert not state_file.exists()
```

**Step 2: Run tests**

Run: `pytest tests/db/test_manager.py::TestSaveSlotOperations -v`
Expected: FAIL - methods not implemented

**Step 3: Add SaveSlot methods to DatabaseManager**

Add these methods to `src/db/manager.py`:

```python
    # ==================== Save Slots ====================
    
    def save_to_slot(
        self,
        chat_id: int,
        slot_number: int,
        state_data: bytes,
        state_file_path: Path,
        description: Optional[str] = None,
        is_auto_save: bool = False,
    ) -> SaveSlotInfo:
        """Save game state to a specific slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number to save to
            state_data: The raw save state bytes from PyBoy
            state_file_path: Path where to save the binary state file
            description: Optional description of the save
            is_auto_save: Whether this is an auto-save
            
        Returns:
            SaveSlotInfo with metadata about the save
        """
        # Ensure parent directory exists
        state_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save binary state data to file
        with open(state_file_path, "wb") as f:
            f.write(state_data)
        
        # Save metadata to database
        now = datetime.utcnow()
        sql = """
        INSERT INTO save_slots 
            (chat_id, slot_number, is_auto_save, description, created_at, updated_at, state_file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, slot_number) DO UPDATE SET
            is_auto_save = excluded.is_auto_save,
            description = excluded.description,
            updated_at = excluded.updated_at,
            state_file_path = excluded.state_file_path;
        """
        
        self.connection.execute(sql, (
            chat_id, slot_number, 1 if is_auto_save else 0, description,
            now.isoformat(), now.isoformat(), str(state_file_path)
        ))
        self.connection.commit()
        
        info = SaveSlotInfo(
            slot_number=slot_number,
            created_at=now,
            updated_at=now,
            is_auto_save=is_auto_save,
            description=description
        )
        
        logger.info(f"Saved state to slot {slot_number} for chat {chat_id}")
        return info
    
    def load_from_slot(self, chat_id: int, slot_number: int) -> Optional[bytes]:
        """Load game state from a specific slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number to load from
            
        Returns:
            The raw save state bytes, or None if slot doesn't exist
        """
        sql = "SELECT state_file_path FROM save_slots WHERE chat_id = ? AND slot_number = ?;"
        cursor = self.connection.execute(sql, (chat_id, slot_number))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        state_file_path = Path(row['state_file_path'])
        
        if not state_file_path.exists():
            logger.error(f"State file missing for chat {chat_id}, slot {slot_number}")
            return None
        
        try:
            with open(state_file_path, "rb") as f:
                data = f.read()
            logger.info(f"Loaded state from slot {slot_number} for chat {chat_id}")
            return data
        except Exception as e:
            logger.error(f"Failed to load state from slot {slot_number} for chat {chat_id}: {e}")
            return None
    
    def get_slot_info(self, chat_id: int, slot_number: int) -> Optional[SaveSlotInfo]:
        """Get metadata for a save slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number
            
        Returns:
            SaveSlotInfo if slot exists, None otherwise
        """
        sql = "SELECT * FROM save_slots WHERE chat_id = ? AND slot_number = ?;"
        cursor = self.connection.execute(sql, (chat_id, slot_number))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        return SaveSlotInfo(
            slot_number=row['slot_number'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
            is_auto_save=bool(row['is_auto_save']),
            description=row['description']
        )
    
    def list_save_slots(self, chat_id: int, max_slots: int | None = None) -> list[SaveSlotInfo]:
        """List all save slots for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            max_slots: Maximum number of slots to check (ignored, kept for compatibility)
            
        Returns:
            List of SaveSlotInfo for existing slots
        """
        sql = "SELECT * FROM save_slots WHERE chat_id = ? ORDER BY slot_number;"
        cursor = self.connection.execute(sql, (chat_id,))
        
        slots = []
        for row in cursor.fetchall():
            slots.append(SaveSlotInfo(
                slot_number=row['slot_number'],
                created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
                updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
                is_auto_save=bool(row['is_auto_save']),
                description=row['description']
            ))
        
        return slots
    
    def delete_slot(self, chat_id: int, slot_number: int) -> bool:
        """Delete a save slot.
        
        Args:
            chat_id: The Telegram chat ID
            slot_number: The slot number to delete
            
        Returns:
            True if deleted, False if didn't exist
        """
        # Get file path before deleting
        sql = "SELECT state_file_path FROM save_slots WHERE chat_id = ? AND slot_number = ?;"
        cursor = self.connection.execute(sql, (chat_id, slot_number))
        row = cursor.fetchone()
        
        if row is None:
            return False
        
        # Delete file
        state_file_path = Path(row['state_file_path'])
        if state_file_path.exists():
            state_file_path.unlink()
        
        # Delete from database
        sql = "DELETE FROM save_slots WHERE chat_id = ? AND slot_number = ?;"
        self.connection.execute(sql, (chat_id, slot_number))
        self.connection.commit()
        
        logger.info(f"Deleted slot {slot_number} for chat {chat_id}")
        return True
    
    def find_next_auto_save_slot(self, chat_id: int, num_slots: int | None = None) -> int:
        """Find the next slot for auto-save using round-robin.
        
        Args:
            chat_id: The Telegram chat ID
            num_slots: Total number of slots (default: 5)
            
        Returns:
            Slot number for next auto-save
        """
        max_slots = num_slots if num_slots is not None else 5
        
        sql = """SELECT slot_number FROM save_slots 
                 WHERE chat_id = ? AND is_auto_save = 1
                 ORDER BY slot_number;"""
        cursor = self.connection.execute(sql, (chat_id,))
        auto_saves = [row['slot_number'] for row in cursor.fetchall()]
        
        if not auto_saves:
            return 0
        
        max_slot = max(auto_saves)
        return (max_slot + 1) % max_slots
```

**Step 4: Run tests**

Run: `pytest tests/db/test_manager.py::TestSaveSlotOperations -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/db/manager.py tests/db/test_manager.py
git commit -m "feat(db): add save slot operations with filesystem storage"
```

---

## Task 7: Database Manager - Utility Operations

**Step 1: Write tests for utility operations**

```python
class TestUtilityOperations:
    """Test utility operations."""
    
    def test_chat_exists_with_game_state(self, db_manager):
        """Verify chat_exists returns True with game state."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        assert db_manager.chat_exists(123) is True
    
    def test_chat_exists_with_config(self, db_manager):
        """Verify chat_exists returns True with config."""
        config = ChatConfig(chat_id=456)
        db_manager.save_chat_config(config)
        
        assert db_manager.chat_exists(456) is True
    
    def test_chat_exists_with_save_slot(self, db_manager, tmp_path):
        """Verify chat_exists returns True with save slot."""
        state = ChatGameState(chat_id=789)
        db_manager.save_game_state(state)
        
        db_manager.save_to_slot(789, 0, b"data", tmp_path / "slot.state")
        
        assert db_manager.chat_exists(789) is True
    
    def test_chat_exists_nonexistent(self, db_manager):
        """Verify chat_exists returns False for nonexistent chat."""
        assert db_manager.chat_exists(999) is False
    
    def test_delete_all_chat_data(self, db_manager, tmp_path):
        """Verify delete_all removes all data for chat."""
        state = ChatGameState(chat_id=123)
        db_manager.save_game_state(state)
        
        config = ChatConfig(chat_id=123)
        db_manager.save_chat_config(config)
        
        db_manager.save_to_slot(123, 0, b"data", tmp_path / "slot.state")
        
        deleted = db_manager.delete_all_chat_data(123)
        assert deleted is True
        
        assert db_manager.load_game_state(123) is None
        assert db_manager.load_chat_config(123) is None
        assert db_manager.list_save_slots(123) == []
    
    def test_delete_all_chat_data_nonexistent(self, db_manager):
        """Verify delete_all returns False for nonexistent chat."""
        result = db_manager.delete_all_chat_data(999)
        assert result is False
```

**Step 2: Run tests**

Run: `pytest tests/db/test_manager.py::TestUtilityOperations -v`
Expected: FAIL - methods not implemented

**Step 3: Add utility methods to DatabaseManager**

Add these methods to `src/db/manager.py`:

```python
    # ==================== Utility Methods ====================
    
    def chat_exists(self, chat_id: int) -> bool:
        """Check if any data exists for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            True if chat has any saved data
        """
        # Check for game state
        cursor = self.connection.execute(
            "SELECT 1 FROM game_states WHERE chat_id = ? LIMIT 1;",
            (chat_id,)
        )
        if cursor.fetchone():
            return True
        
        # Check for config
        cursor = self.connection.execute(
            "SELECT 1 FROM chat_configs WHERE chat_id = ? LIMIT 1;",
            (chat_id,)
        )
        if cursor.fetchone():
            return True
        
        # Check for saves
        cursor = self.connection.execute(
            "SELECT 1 FROM save_slots WHERE chat_id = ? LIMIT 1;",
            (chat_id,)
        )
        if cursor.fetchone():
            return True
        
        return False
    
    def delete_all_chat_data(self, chat_id: int) -> bool:
        """Delete all data for a chat.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            True if any data was deleted
        """
        deleted = False
        
        # Delete game state (cascade deletes user_input_counts, recent_inputs, queue)
        if self.delete_game_state(chat_id):
            deleted = True
        
        # Delete config
        cursor = self.connection.execute(
            "DELETE FROM chat_configs WHERE chat_id = ?;",
            (chat_id,)
        )
        if cursor.rowcount > 0:
            deleted = True
        
        # Delete saves (delete files first)
        cursor = self.connection.execute(
            "SELECT state_file_path FROM save_slots WHERE chat_id = ?;",
            (chat_id,)
        )
        for row in cursor.fetchall():
            state_file_path = Path(row['state_file_path'])
            if state_file_path.exists():
                state_file_path.unlink()
        
        cursor = self.connection.execute(
            "DELETE FROM save_slots WHERE chat_id = ?;",
            (chat_id,)
        )
        if cursor.rowcount > 0:
            deleted = True
        
        self.connection.commit()
        
        if deleted:
            logger.info(f"Deleted all data for chat {chat_id}")
        
        return deleted
```

**Step 4: Run tests**

Run: `pytest tests/db/test_manager.py::TestUtilityOperations -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/db/manager.py tests/db/test_manager.py
git commit -m "feat(db): add utility operations (chat_exists, delete_all)"
```

---

## Task 8: Database Package Initialization

**Step 1: Create __init__.py for db package**

**Files:**
- Create: `src/db/__init__.py`

```python
"""Database package for SQLite persistence."""

from src.db.manager import DatabaseManager
from src.db.connection import DatabaseConnection, get_db_path
from src.db.schema import get_schema_sql, SCHEMA_VERSION

__all__ = [
    'DatabaseManager',
    'DatabaseConnection', 
    'get_db_path',
    'get_schema_sql',
    'SCHEMA_VERSION',
]
```

**Step 2: Write test for package imports**

**Files:**
- Create: `tests/db/__init__.py` (empty)
- Modify: `tests/db/test_manager.py` to add import test

Add to `tests/db/test_manager.py`:

```python

def test_db_package_imports():
    """Verify all public exports are importable."""
    from src.db import DatabaseManager, DatabaseConnection, get_db_path
    from src.db import get_schema_sql, SCHEMA_VERSION
    
    assert DatabaseManager is not None
    assert DatabaseConnection is not None
    assert callable(get_db_path)
    assert callable(get_schema_sql)
    assert isinstance(SCHEMA_VERSION, int)
```

**Step 3: Run tests**

Run: `pytest tests/db/test_manager.py::test_db_package_imports -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/db/__init__.py tests/db/__init__.py
git add tests/db/test_manager.py
git commit -m "feat(db): add database package initialization"
```

---

## Task 9: Migration Script

**Step 1: Write migration script tests**

**Files:**
- Create: `tests/test_migration_script.py`
- Create: `scripts/migrate_to_sqlite.py`

```python
"""Tests for migration script."""
import json
import pytest
from pathlib import Path
from datetime import datetime

from src.models.game_state import ChatGameState, ChatConfig, SaveSlotInfo, GameButton
from src.db import DatabaseManager


class TestMigrationScript:
    """Test data migration from JSON files to SQLite."""
    
    def test_migrate_chat_config(self, tmp_path):
        """Verify chat config migration."""
        # Create old-style data directory
        data_dir = tmp_path / "data"
        config_dir = data_dir / "config"
        config_dir.mkdir(parents=True)
        
        # Create config JSON file
        config = ChatConfig(chat_id=123, input_hold_frames=10, running_mode=True)
        config_file = config_dir / "123.json"
        with open(config_file, 'w') as f:
            json.dump(config.to_dict(), f)
        
        # Run migration
        from scripts.migrate_to_sqlite import migrate_data
        db_manager = DatabaseManager(tmp_path / "bot.db")
        db_manager.initialize()
        
        migrate_data(data_dir, db_manager)
        
        # Verify migrated
        loaded = db_manager.load_chat_config(123)
        assert loaded is not None
        assert loaded.input_hold_frames == 10
        assert loaded.running_mode is True
    
    def test_migrate_game_state(self, tmp_path):
        """Verify game state migration."""
        data_dir = tmp_path / "data"
        polls_dir = data_dir / "polls"
        polls_dir.mkdir(parents=True)
        
        # Create game state JSON
        state = ChatGameState(
            chat_id=456,
            message_id=789,
            last_input=GameButton.A,
            user_input_counts={"111": 5, "222": 3},
            recent_inputs=[{
                "user_id": 111,
                "user_name": "Alice",
                "buttons": ["a"],
                "timestamp": datetime.utcnow().isoformat()
            }]
        )
        state_file = polls_dir / "456.json"
        with open(state_file, 'w') as f:
            json.dump(state.to_dict(), f)
        
        # Run migration
        from scripts.migrate_to_sqlite import migrate_data
        db_manager = DatabaseManager(tmp_path / "bot.db")
        db_manager.initialize()
        
        migrate_data(data_dir, db_manager)
        
        # Verify migrated
        loaded = db_manager.load_game_state(456)
        assert loaded is not None
        assert loaded.message_id == 789
        assert loaded.last_input == GameButton.A
        assert loaded.user_input_counts == {"111": "5", "222": "3"}  # Note: stored as strings in JSON
        assert len(loaded.recent_inputs) == 1
    
    def test_migrate_save_slot(self, tmp_path):
        """Verify save slot migration."""
        data_dir = tmp_path / "data"
        saves_dir = data_dir / "saves" / "789"
        saves_dir.mkdir(parents=True)
        
        # Create save slot metadata and binary file
        slot_info = SaveSlotInfo(slot_number=0, is_auto_save=True, description="Test")
        with open(saves_dir / "slot_0.json", 'w') as f:
            json.dump(slot_info.to_dict(), f)
        
        state_data = b"fake_save_state_data"
        with open(saves_dir / "slot_0.state", 'wb') as f:
            f.write(state_data)
        
        # Also need game state for foreign key
        polls_dir = data_dir / "polls"
        polls_dir.mkdir(parents=True)
        state = ChatGameState(chat_id=789)
        with open(polls_dir / "789.json", 'w') as f:
            json.dump(state.to_dict(), f)
        
        # Run migration
        from scripts.migrate_to_sqlite import migrate_data
        db_manager = DatabaseManager(tmp_path / "bot.db")
        db_manager.initialize()
        
        migrate_data(data_dir, db_manager)
        
        # Verify migrated
        info = db_manager.get_slot_info(789, 0)
        assert info is not None
        assert info.is_auto_save is True
        
        # Verify binary data accessible
        loaded_data = db_manager.load_from_slot(789, 0)
        assert loaded_data == state_data
```

**Step 2: Run tests**

Run: `pytest tests/test_migration_script.py -v`
Expected: FAIL - script not implemented

**Step 3: Implement migration script**

```python
#!/usr/bin/env python3
"""Migration script from JSON files to SQLite database.

This script migrates all existing bot data from JSON file storage
to the new SQLite database format. It should be run once before
deploying the new database-based code.

Usage:
    python scripts/migrate_to_sqlite.py [--data-dir PATH] [--db-path PATH] [--dry-run]

Example:
    python scripts/migrate_to_sqlite.py --data-dir data --db-path data/bot.db
"""

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.db import DatabaseManager
from src.models.game_state import ChatGameState, ChatConfig, SaveSlotInfo, GameButton
from src.models.input_queue import InputQueue

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_chat_configs(data_dir: Path, db_manager: DatabaseManager, dry_run: bool = False) -> int:
    """Migrate chat config JSON files to database.
    
    Args:
        data_dir: Root data directory
        db_manager: Database manager instance
        dry_run: If True, don't actually write to database
        
    Returns:
        Number of configs migrated
    """
    config_dir = data_dir / "config"
    if not config_dir.exists():
        logger.info("No config directory found, skipping config migration")
        return 0
    
    count = 0
    for config_file in config_dir.glob("*.json"):
        try:
            with open(config_file, 'r') as f:
                data = json.load(f)
            
            chat_id = int(config_file.stem)
            config = ChatConfig.from_dict(data)
            
            if not dry_run:
                db_manager.save_chat_config(config)
            
            count += 1
            logger.info(f"Migrated config for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to migrate config {config_file}: {e}")
    
    return count


def migrate_game_states(data_dir: Path, db_manager: DatabaseManager, dry_run: bool = False) -> int:
    """Migrate game state JSON files to database.
    
    Args:
        data_dir: Root data directory
        db_manager: Database manager instance
        dry_run: If True, don't actually write to database
        
    Returns:
        Number of game states migrated
    """
    polls_dir = data_dir / "polls"
    if not polls_dir.exists():
        logger.info("No polls directory found, skipping game state migration")
        return 0
    
    count = 0
    for state_file in polls_dir.glob("*.json"):
        try:
            with open(state_file, 'r') as f:
                data = json.load(f)
            
            chat_id = int(state_file.stem)
            
            # Handle potential missing fields for backward compatibility
            state = ChatGameState(
                chat_id=chat_id,
                message_id=data.get('message_id'),
                input_in_progress=data.get('input_in_progress', False),
                last_input=GameButton(data['last_input']) if data.get('last_input') else None,
                last_input_time=datetime.fromisoformat(data['last_input_time']) if data.get('last_input_time') else None,
                frame_hash=data.get('frame_hash'),
                user_input_counts=data.get('user_input_counts', {}),
                recent_inputs=data.get('recent_inputs', []),
                created_at=datetime.fromisoformat(data.get('created_at', datetime.utcnow().isoformat())),
                updated_at=datetime.fromisoformat(data.get('updated_at', datetime.utcnow().isoformat()))
            )
            
            # Handle input queue if present (note: queue items have user_id as int in new schema)
            if data.get('input_queue'):
                state.input_queue = InputQueue.from_dict(data['input_queue'])
            
            if not dry_run:
                db_manager.save_game_state(state)
            
            count += 1
            logger.info(f"Migrated game state for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to migrate game state {state_file}: {e}")
    
    return count


def migrate_save_slots(data_dir: Path, db_manager: DatabaseManager, new_states_dir: Path, dry_run: bool = False) -> int:
    """Migrate save slot JSON files and binary state files.
    
    Args:
        data_dir: Root data directory
        db_manager: Database manager instance
        new_states_dir: Directory for new binary state files
        dry_run: If True, don't actually write files or database
        
    Returns:
        Number of save slots migrated
    """
    saves_dir = data_dir / "saves"
    if not saves_dir.exists():
        logger.info("No saves directory found, skipping save slot migration")
        return 0
    
    if not dry_run:
        new_states_dir.mkdir(parents=True, exist_ok=True)
    
    count = 0
    
    # Iterate through chat directories
    for chat_dir in saves_dir.iterdir():
        if not chat_dir.is_dir():
            continue
        
        try:
            chat_id = int(chat_dir.name)
        except ValueError:
            logger.warning(f"Skipping non-integer chat directory: {chat_dir.name}")
            continue
        
        # Process each slot
        for slot_file in chat_dir.glob("slot_*.json"):
            try:
                slot_number = int(slot_file.stem.split('_')[1])
                
                # Load metadata
                with open(slot_file, 'r') as f:
                    data = json.load(f)
                
                # Load binary state data
                state_file = slot_file.parent / f"slot_{slot_number}.state"
                if not state_file.exists():
                    logger.warning(f"State file missing for chat {chat_id}, slot {slot_number}")
                    continue
                
                with open(state_file, 'rb') as f:
                    state_data = f.read()
                
                # Determine new file path
                new_state_file = new_states_dir / f"{chat_id}_{slot_number}.state"
                
                if not dry_run:
                    # Copy binary file
                    shutil.copy2(state_file, new_state_file)
                    
                    # Save metadata to database
                    db_manager.save_to_slot(
                        chat_id=chat_id,
                        slot_number=slot_number,
                        state_data=state_data,  # Will be written to file again, but that's ok
                        state_file_path=new_state_file,
                        description=data.get('description'),
                        is_auto_save=data.get('is_auto_save', False)
                    )
                
                count += 1
                logger.info(f"Migrated save slot {slot_number} for chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to migrate save slot {slot_file}: {e}")
    
    return count


def migrate_data(data_dir: Path, db_manager: DatabaseManager, dry_run: bool = False) -> dict:
    """Migrate all data from JSON files to SQLite database.
    
    Args:
        data_dir: Root data directory containing polls/, config/, saves/
        db_manager: Initialized DatabaseManager instance
        dry_run: If True, don't actually write any data
        
    Returns:
        Dictionary with migration statistics
    """
    stats = {
        'configs': 0,
        'game_states': 0,
        'save_slots': 0,
        'errors': []
    }
    
    new_states_dir = data_dir / "state_files"
    
    logger.info(f"Starting migration from {data_dir}")
    logger.info(f"{'DRY RUN - ' if dry_run else ''}Target database: {db_manager.connection.db_path}")
    
    # Migrate in order: configs -> game states -> save slots
    stats['configs'] = migrate_chat_configs(data_dir, db_manager, dry_run)
    stats['game_states'] = migrate_game_states(data_dir, db_manager, dry_run)
    stats['save_slots'] = migrate_save_slots(data_dir, db_manager, new_states_dir, dry_run)
    
    logger.info("Migration complete!")
    logger.info(f"  Configs: {stats['configs']}")
    logger.info(f"  Game states: {stats['game_states']}")
    logger.info(f"  Save slots: {stats['save_slots']}")
    
    return stats


def main():
    """Main entry point for migration script."""
    parser = argparse.ArgumentParser(
        description='Migrate Telegram GBC Bot data from JSON files to SQLite'
    )
    parser.add_argument(
        '--data-dir',
        type=Path,
        default=Path('data'),
        help='Path to data directory (default: data)'
    )
    parser.add_argument(
        '--db-path',
        type=Path,
        default=Path('data/bot.db'),
        help='Path for new SQLite database (default: data/bot.db)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview migration without writing changes'
    )
    
    args = parser.parse_args()
    
    if not args.data_dir.exists():
        logger.error(f"Data directory not found: {args.data_dir}")
        sys.exit(1)
    
    if args.db_path.exists() and not args.dry_run:
        logger.warning(f"Database already exists: {args.db_path}")
        response = input("Overwrite? (yes/no): ")
        if response.lower() != 'yes':
            logger.info("Migration cancelled")
            sys.exit(0)
        args.db_path.unlink()
    
    # Initialize database
    db_manager = DatabaseManager(args.db_path)
    db_manager.initialize()
    
    try:
        stats = migrate_data(args.data_dir, db_manager, args.dry_run)
        
        if not args.dry_run:
            print("\nMigration complete!")
            print(f"Next steps:")
            print(f"  1. Backup old data: cp -r {args.data_dir} {args.data_dir}.backup")
            print(f"  2. Deploy new code that uses DatabaseManager")
            print(f"  3. After confirming everything works, remove old JSON files:")
            print(f"     rm -rf {args.data_dir}/polls {args.data_dir}/config {args.data_dir}/saves")
        
        sys.exit(0)
    except Exception as e:
        logger.exception("Migration failed")
        sys.exit(1)
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `pytest tests/test_migration_script.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/migrate_to_sqlite.py tests/test_migration_script.py
git commit -m "feat(migration): add SQLite migration script with tests"
```

---

## Task 10: Integration and Compatibility Layer

**Goal:** Create compatibility layer so existing code using StateManager can work with either JSON or SQLite backend during transition period.

**Step 1: Write integration tests**

**Files:**
- Create: `tests/test_db_integration.py`

```python
"""Integration tests for database migration."""
import pytest
from pathlib import Path

from src.db import DatabaseManager
from src.utils.state_manager import StateManager
from src.models.game_state import ChatGameState, ChatConfig


class TestStateManagerCompatibility:
    """Test DatabaseManager provides same interface as StateManager."""
    
    def test_both_managers_have_same_methods(self):
        """Verify DatabaseManager has all StateManager methods."""
        state_methods = set(dir(StateManager))
        db_methods = set(dir(DatabaseManager))
        
        # Core methods that should exist in both
        required_methods = {
            'save_game_state', 'load_game_state', 'delete_game_state',
            'save_chat_config', 'load_chat_config', 'get_or_create_chat_config',
            'save_to_slot', 'load_from_slot', 'get_slot_info', 'list_save_slots', 'delete_slot',
            'find_next_auto_save_slot', 'chat_exists', 'delete_all_chat_data'
        }
        
        for method in required_methods:
            assert hasattr(DatabaseManager, method), f"DatabaseManager missing {method}"
    
    def test_game_state_roundtrip(self, tmp_path):
        """Verify game state saved by DatabaseManager can be loaded correctly."""
        db_manager = DatabaseManager(tmp_path / "test.db")
        db_manager.initialize()
        
        state = ChatGameState(
            chat_id=123,
            message_id=456,
            input_in_progress=True
        )
        
        db_manager.save_game_state(state)
        loaded = db_manager.load_game_state(123)
        
        assert loaded.chat_id == state.chat_id
        assert loaded.message_id == state.message_id
        assert loaded.input_in_progress == state.input_in_progress
```

**Step 2: Run tests**

Run: `pytest tests/test_db_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_db_integration.py
git commit -m "test(db): add integration tests for database compatibility"
```

---

## Task 11: Run Full Test Suite

**Step 1: Run all database tests**

```bash
poetry run pytest tests/db/ tests/test_migration_script.py tests/test_db_integration.py -v
```

Expected: All tests PASS

**Step 2: Verify no regressions in existing tests**

```bash
poetry run pytest tests/ -v --ignore=tests/test_integration.py
```

Expected: All tests PASS (excluding integration tests which may need real env)

**Step 3: Commit final changes**

```bash
git add -A
git commit -m "feat(db): complete SQLite migration with full test coverage"
```

---

## Deployment Instructions

After implementation is complete:

1. **Run migration on production:**
   ```bash
   python scripts/migrate_to_sqlite.py --data-dir data --db-path data/bot.db
   ```

2. **Backup old data:**
   ```bash
   cp -r data data.backup.$(date +%Y%m%d)
   ```

3. **Update code to use DatabaseManager** (next phase):
   - Replace `from src.utils.state_manager import state_manager` 
   - With `from src.db import DatabaseManager` and initialize

4. **Clean up old files** (after confirming everything works):
   ```bash
   rm -rf data/polls data/config data/saves
   ```

---

## Summary

This plan creates:
- **Database layer**: schema, connection management, CRUD operations
- **Full test coverage**: unit tests for all components
- **Migration script**: one-time import with dry-run support
- **Compatibility**: DatabaseManager maintains same API as StateManager

Total tasks: 11
Estimated time: 2-3 hours
All changes isolated to `src/db/` and `scripts/` directories
