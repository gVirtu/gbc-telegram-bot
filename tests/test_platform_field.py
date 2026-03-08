"""Tests for the platform field in ChatConfig: dataclass, migration, and DB persistence."""

import sqlite3
import pytest

from src.db.manager import DatabaseManager
from src.models.game_state import ChatConfig


@pytest.fixture
def db_manager(tmp_path):
    """Create a fresh DatabaseManager for testing."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    yield manager
    manager.close()


# ---------------------------------------------------------------------------
# ChatConfig dataclass
# ---------------------------------------------------------------------------

class TestChatConfigPlatformField:
    def test_default_is_telegram(self):
        config = ChatConfig(chat_id=1)
        assert config.platform == "telegram"

    def test_set_custom_platform(self):
        config = ChatConfig(chat_id=2, platform="discord")
        assert config.platform == "discord"

    def test_to_dict_includes_platform(self):
        config = ChatConfig(chat_id=3, platform="discord")
        assert config.to_dict()["platform"] == "discord"

    def test_from_dict_round_trip(self):
        config = ChatConfig(chat_id=4, platform="discord")
        loaded = ChatConfig.from_dict(config.to_dict())
        assert loaded.platform == "discord"

    def test_from_dict_missing_key_defaults_telegram(self):
        d = ChatConfig(chat_id=5).to_dict()
        del d["platform"]
        loaded = ChatConfig.from_dict(d)
        assert loaded.platform == "telegram"


# ---------------------------------------------------------------------------
# DatabaseManager: save/load platform
# ---------------------------------------------------------------------------

class TestDatabaseManagerPlatformField:
    def test_save_and_load_platform(self, db_manager):
        config = ChatConfig(chat_id=100, platform="discord")
        db_manager.save_chat_config(config)

        loaded = db_manager.load_chat_config(100)
        assert loaded is not None
        assert loaded.platform == "discord"

    def test_default_platform_persisted(self, db_manager):
        config = ChatConfig(chat_id=101)
        db_manager.save_chat_config(config)

        loaded = db_manager.load_chat_config(101)
        assert loaded.platform == "telegram"

    def test_update_platform(self, db_manager):
        config = ChatConfig(chat_id=102, platform="telegram")
        db_manager.save_chat_config(config)

        config.platform = "discord"
        db_manager.save_chat_config(config)

        loaded = db_manager.load_chat_config(102)
        assert loaded.platform == "discord"


# ---------------------------------------------------------------------------
# Migration 010
# ---------------------------------------------------------------------------

class TestMigration010:
    def test_migration_adds_platform_column(self, tmp_path):
        """Migration 010 adds platform column to chat_configs."""
        import importlib
        migration = importlib.import_module(
            "src.db.migrations.010_add_platform_to_chat_configs"
        )

        conn = sqlite3.connect(str(tmp_path / "test_migrate.db"))
        conn.row_factory = sqlite3.Row

        # Create chat_configs table without platform column
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

        cursor = conn.execute("PRAGMA table_info(chat_configs);")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "platform" in columns
        conn.close()

    def test_migration_default_value(self, tmp_path):
        """Existing rows get 'telegram' as default after migration."""
        import importlib
        migration = importlib.import_module(
            "src.db.migrations.010_add_platform_to_chat_configs"
        )

        conn = sqlite3.connect(str(tmp_path / "test_migrate2.db"))
        conn.row_factory = sqlite3.Row

        conn.execute("""
            CREATE TABLE chat_configs (
                chat_id INTEGER PRIMARY KEY,
                auto_save_enabled INTEGER DEFAULT 1,
                modifier_states TEXT,
                maintenance_mode INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("INSERT INTO chat_configs (chat_id) VALUES (1);")
        conn.commit()

        migration.upgrade(conn)
        conn.commit()

        cursor = conn.execute("SELECT platform FROM chat_configs WHERE chat_id = 1;")
        row = cursor.fetchone()
        assert row["platform"] == "telegram"
        conn.close()

    def test_migration_downgrade_removes_column(self, tmp_path):
        """Migration 010 downgrade drops platform column."""
        import importlib
        migration = importlib.import_module(
            "src.db.migrations.010_add_platform_to_chat_configs"
        )

        conn = sqlite3.connect(str(tmp_path / "test_migrate3.db"))
        conn.row_factory = sqlite3.Row

        conn.execute("""
            CREATE TABLE chat_configs (
                chat_id INTEGER PRIMARY KEY,
                auto_save_enabled INTEGER DEFAULT 1,
                modifier_states TEXT,
                maintenance_mode INTEGER DEFAULT 0,
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
        columns = {row["name"] for row in cursor.fetchall()}
        assert "platform" not in columns
        conn.close()
