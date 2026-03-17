"""Tests for user_preferences table and DatabaseManager get/set methods."""
import os
import pytest
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")


@pytest.fixture
def db_manager(tmp_path):
    from src.db.manager import DatabaseManager
    manager = DatabaseManager(tmp_path / "test.db")
    manager.initialize()
    yield manager
    manager.close()


def test_user_preferences_table_exists_after_migration(db_manager):
    """user_preferences table must exist after initialize()."""
    cursor = db_manager.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_preferences';"
    )
    assert cursor.fetchone() is not None, "user_preferences table should exist"


def test_get_user_preference_returns_none_when_missing(db_manager):
    """Returns None when no preference exists."""
    result = db_manager.get_user_preference("discord", 123456789, "sequence_mapping")
    assert result is None


def test_set_and_get_user_preference_round_trip(db_manager):
    """set_user_preference persists, get_user_preference retrieves it."""
    db_manager.set_user_preference("discord", 123456789, "sequence_mapping", "WASD ZX CV")
    result = db_manager.get_user_preference("discord", 123456789, "sequence_mapping")
    assert result == "WASD ZX CV"


def test_set_user_preference_overwrites_existing(db_manager):
    """Calling set again replaces the previous value."""
    db_manager.set_user_preference("discord", 111, "sequence_mapping", "ULDR AB ST")
    db_manager.set_user_preference("discord", 111, "sequence_mapping", "8426 13 79")
    assert db_manager.get_user_preference("discord", 111, "sequence_mapping") == "8426 13 79"


def test_preferences_are_isolated_by_platform_and_user(db_manager):
    """Different (platform, user_id) pairs do not share preferences."""
    db_manager.set_user_preference("discord", 1, "sequence_mapping", "WASD ZX CV")
    db_manager.set_user_preference("telegram", 1, "sequence_mapping", "IJKL NM UO")
    db_manager.set_user_preference("discord", 2, "sequence_mapping", "8426 13 79")

    assert db_manager.get_user_preference("discord", 1, "sequence_mapping") == "WASD ZX CV"
    assert db_manager.get_user_preference("telegram", 1, "sequence_mapping") == "IJKL NM UO"
    assert db_manager.get_user_preference("discord", 2, "sequence_mapping") == "8426 13 79"
