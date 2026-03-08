"""Tests for the mirrors_chat_id data model, migration, and StateManager method."""

import sqlite3
import pytest
from pathlib import Path

from src.db.manager import DatabaseManager
from src.models.game_state import ChatConfig
from src.utils.state_manager import StateManager


@pytest.fixture
def db_manager(tmp_path):
    """Create a fresh DatabaseManager for testing."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def state_manager(tmp_path):
    """Create a fresh StateManager for testing."""
    return StateManager(data_dir=tmp_path)


# ---------------------------------------------------------------------------
# ChatConfig dataclass
# ---------------------------------------------------------------------------

class TestChatConfigMirrorsChatId:
    def test_default_is_none(self):
        config = ChatConfig(chat_id=1)
        assert config.mirrors_chat_id is None

    def test_set_mirrors_chat_id(self):
        config = ChatConfig(chat_id=2, mirrors_chat_id=1)
        assert config.mirrors_chat_id == 1

    def test_to_dict_includes_mirrors_chat_id(self):
        config = ChatConfig(chat_id=2, mirrors_chat_id=1)
        d = config.to_dict()
        assert d["mirrors_chat_id"] == 1

    def test_to_dict_none_mirrors_chat_id(self):
        config = ChatConfig(chat_id=3)
        d = config.to_dict()
        assert d["mirrors_chat_id"] is None

    def test_from_dict_round_trip(self):
        config = ChatConfig(chat_id=4, mirrors_chat_id=99)
        d = config.to_dict()
        loaded = ChatConfig.from_dict(d)
        assert loaded.mirrors_chat_id == 99

    def test_from_dict_missing_key_defaults_none(self):
        d = ChatConfig(chat_id=5).to_dict()
        del d["mirrors_chat_id"]
        loaded = ChatConfig.from_dict(d)
        assert loaded.mirrors_chat_id is None


# ---------------------------------------------------------------------------
# DatabaseManager: save/load mirrors_chat_id
# ---------------------------------------------------------------------------

class TestDatabaseManagerMirrorsChatId:
    def test_save_and_load_mirrors_chat_id(self, db_manager):
        # Leader must exist first (FK constraint)
        db_manager.save_chat_config(ChatConfig(chat_id=200))
        config = ChatConfig(chat_id=100, mirrors_chat_id=200)
        db_manager.save_chat_config(config)

        loaded = db_manager.load_chat_config(100)
        assert loaded is not None
        assert loaded.mirrors_chat_id == 200

    def test_save_and_load_none_mirrors_chat_id(self, db_manager):
        config = ChatConfig(chat_id=101)
        db_manager.save_chat_config(config)

        loaded = db_manager.load_chat_config(101)
        assert loaded is not None
        assert loaded.mirrors_chat_id is None

    def test_update_mirrors_chat_id(self, db_manager):
        db_manager.save_chat_config(ChatConfig(chat_id=999))
        config = ChatConfig(chat_id=102)
        db_manager.save_chat_config(config)

        config.mirrors_chat_id = 999
        db_manager.save_chat_config(config)

        loaded = db_manager.load_chat_config(102)
        assert loaded.mirrors_chat_id == 999

    def test_clear_mirrors_chat_id(self, db_manager):
        db_manager.save_chat_config(ChatConfig(chat_id=500))
        config = ChatConfig(chat_id=103, mirrors_chat_id=500)
        db_manager.save_chat_config(config)

        config.mirrors_chat_id = None
        db_manager.save_chat_config(config)

        loaded = db_manager.load_chat_config(103)
        assert loaded.mirrors_chat_id is None


# ---------------------------------------------------------------------------
# DatabaseManager.get_mirror_chat_ids
# ---------------------------------------------------------------------------

class TestGetMirrorChatIds:
    def test_no_mirrors_returns_empty(self, db_manager):
        db_manager.save_chat_config(ChatConfig(chat_id=1))
        result = db_manager.get_mirror_chat_ids(1)
        assert result == []

    def test_single_mirror(self, db_manager):
        db_manager.save_chat_config(ChatConfig(chat_id=10))
        db_manager.save_chat_config(ChatConfig(chat_id=20, mirrors_chat_id=10))

        result = db_manager.get_mirror_chat_ids(10)
        assert result == [20]

    def test_multiple_mirrors(self, db_manager):
        db_manager.save_chat_config(ChatConfig(chat_id=10))
        db_manager.save_chat_config(ChatConfig(chat_id=21, mirrors_chat_id=10))
        db_manager.save_chat_config(ChatConfig(chat_id=22, mirrors_chat_id=10))
        db_manager.save_chat_config(ChatConfig(chat_id=23, mirrors_chat_id=10))

        result = db_manager.get_mirror_chat_ids(10)
        assert sorted(result) == [21, 22, 23]

    def test_does_not_return_unrelated_chats(self, db_manager):
        db_manager.save_chat_config(ChatConfig(chat_id=10))
        db_manager.save_chat_config(ChatConfig(chat_id=11))
        db_manager.save_chat_config(ChatConfig(chat_id=30, mirrors_chat_id=11))

        result = db_manager.get_mirror_chat_ids(10)
        assert result == []

    def test_state_manager_exposes_get_mirror_chat_ids(self, state_manager):
        state_manager.save_chat_config(ChatConfig(chat_id=50))
        state_manager.save_chat_config(ChatConfig(chat_id=51, mirrors_chat_id=50))

        result = state_manager.get_mirror_chat_ids(50)
        assert result == [51]


# ---------------------------------------------------------------------------
# Migration 009
# ---------------------------------------------------------------------------

class TestMigration009:
    def test_migration_adds_mirrors_chat_id_column(self, tmp_path):
        """Migration 009 adds mirrors_chat_id column to chat_configs."""
        import importlib
        migration = importlib.import_module(
            "src.db.migrations.009_add_mirrors_chat_id_to_chat_configs"
        )

        conn = sqlite3.connect(str(tmp_path / "test_migrate.db"))
        conn.row_factory = sqlite3.Row

        # Create a minimal chat_configs table without mirrors_chat_id
        conn.execute("""
            CREATE TABLE chat_configs (
                chat_id INTEGER PRIMARY KEY,
                input_hold_frames INTEGER,
                animation_duration INTEGER,
                auto_save_enabled INTEGER DEFAULT 1,
                modifier_states TEXT,
                message_base_text TEXT,
                maintenance_mode INTEGER DEFAULT 0,
                language TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        # Run upgrade
        migration.upgrade(conn)
        conn.commit()

        # Verify column exists
        cursor = conn.execute("PRAGMA table_info(chat_configs);")
        columns = [row["name"] for row in cursor.fetchall()]
        assert "mirrors_chat_id" in columns

        # Verify column is nullable (can insert NULL)
        conn.execute("INSERT INTO chat_configs (chat_id, modifier_states, mirrors_chat_id) VALUES (1, '{}', NULL)")
        conn.execute("INSERT INTO chat_configs (chat_id, modifier_states, mirrors_chat_id) VALUES (2, '{}', 1)")
        conn.commit()

        row = conn.execute("SELECT mirrors_chat_id FROM chat_configs WHERE chat_id = 2").fetchone()
        assert row["mirrors_chat_id"] == 1

        conn.close()

    def test_migration_downgrade_removes_column(self, tmp_path):
        """Migration 009 downgrade removes mirrors_chat_id column."""
        import importlib
        migration = importlib.import_module(
            "src.db.migrations.009_add_mirrors_chat_id_to_chat_configs"
        )

        conn = sqlite3.connect(str(tmp_path / "test_migrate2.db"))
        conn.row_factory = sqlite3.Row

        conn.execute("""
            CREATE TABLE chat_configs (
                chat_id INTEGER PRIMARY KEY,
                input_hold_frames INTEGER,
                animation_duration INTEGER,
                auto_save_enabled INTEGER DEFAULT 1,
                modifier_states TEXT,
                message_base_text TEXT,
                maintenance_mode INTEGER DEFAULT 0,
                language TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        migration.upgrade(conn)
        conn.commit()

        migration.downgrade(conn)
        conn.commit()

        cursor = conn.execute("PRAGMA table_info(chat_configs);")
        columns = [row["name"] for row in cursor.fetchall()]
        assert "mirrors_chat_id" not in columns

        conn.close()
