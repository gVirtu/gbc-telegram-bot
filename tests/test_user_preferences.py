"""Tests for user_preferences table and DatabaseManager get/set methods."""
import os
import pytest

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


def test_get_user_preference_caches_result(db_manager):
    """Second get returns cached value without hitting the DB."""
    db_manager.set_user_preference("discord", 1, "sequence_mapping", "WASD ZX CV")
    # Populate cache
    db_manager.get_user_preference("discord", 1, "sequence_mapping")
    # Bypass cache by writing directly to DB
    db_manager.connection.execute(
        "UPDATE user_preferences SET value = 'DIRECT' WHERE platform = 'discord' AND user_id = 1 AND key = 'sequence_mapping';"
    )
    db_manager.connection.commit()
    # Should still return cached value
    assert db_manager.get_user_preference("discord", 1, "sequence_mapping") == "WASD ZX CV"


def test_set_user_preference_invalidates_cache(db_manager):
    """set_user_preference clears the cache for that key."""
    db_manager.set_user_preference("discord", 1, "sequence_mapping", "WASD ZX CV")
    db_manager.get_user_preference("discord", 1, "sequence_mapping")  # populate cache
    db_manager.set_user_preference("discord", 1, "sequence_mapping", "NEW VALUE")
    assert db_manager.get_user_preference("discord", 1, "sequence_mapping") == "NEW VALUE"


def test_set_user_preference_only_invalidates_matching_key(db_manager):
    """set_user_preference does not invalidate cache entries for other keys."""
    db_manager.set_user_preference("discord", 1, "key_a", "A")
    db_manager.set_user_preference("discord", 1, "key_b", "B")
    db_manager.get_user_preference("discord", 1, "key_a")  # populate cache for key_a
    db_manager.set_user_preference("discord", 1, "key_b", "B2")
    # key_a cache entry should still be intact
    db_manager.connection.execute(
        "UPDATE user_preferences SET value = 'DIRECT' WHERE platform = 'discord' AND user_id = 1 AND key = 'key_a';"
    )
    db_manager.connection.commit()
    assert db_manager.get_user_preference("discord", 1, "key_a") == "A"


def test_get_user_preference_caches_none(db_manager):
    """Missing preference (None) is also cached."""
    db_manager.get_user_preference("discord", 999, "sequence_mapping")  # caches None
    # Insert directly to DB bypassing set_user_preference
    db_manager.connection.execute(
        "INSERT INTO user_preferences (platform, user_id, key, value) VALUES ('discord', 999, 'sequence_mapping', 'DIRECT');"
    )
    db_manager.connection.commit()
    # Cache still returns None
    assert db_manager.get_user_preference("discord", 999, "sequence_mapping") is None


def test_preferences_are_isolated_by_platform_and_user(db_manager):
    """Different (platform, user_id) pairs do not share preferences."""
    db_manager.set_user_preference("discord", 1, "sequence_mapping", "WASD ZX CV")
    db_manager.set_user_preference("telegram", 1, "sequence_mapping", "IJKL NM UO")
    db_manager.set_user_preference("discord", 2, "sequence_mapping", "8426 13 79")

    assert db_manager.get_user_preference("discord", 1, "sequence_mapping") == "WASD ZX CV"
    assert db_manager.get_user_preference("telegram", 1, "sequence_mapping") == "IJKL NM UO"
    assert db_manager.get_user_preference("discord", 2, "sequence_mapping") == "8426 13 79"
