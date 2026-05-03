import pytest
from datetime import datetime, timezone, timedelta

from src.db.manager import DatabaseManager
from src.models.game_state import ChatConfig, ChatGameState


@pytest.fixture
def db_manager(tmp_path):
    """Create a temporary database manager for testing."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    yield manager
    manager.close()


def test_save_and_load_chat_config_with_modifier_states(db_manager):
    """Test that modifier_states is saved and loaded correctly."""
    config = ChatConfig(
        chat_id=123,
        maintenance_mode=True,
        modifier_states={"run": True},
        auto_save_enabled=True,
    )

    db_manager.save_chat_config(config)

    loaded = db_manager.load_chat_config(123)
    assert loaded is not None
    assert loaded.maintenance_mode is True
    assert loaded.modifier_states == {"run": True}
    assert loaded.chat_id == 123


def test_save_and_load_chat_config_empty_modifier_states(db_manager):
    """Test that empty modifier_states is saved and loaded correctly."""
    config = ChatConfig(chat_id=456, modifier_states={})
    db_manager.save_chat_config(config)
    loaded = db_manager.load_chat_config(456)
    assert loaded is not None
    assert loaded.modifier_states == {}


def test_get_or_create_chat_config_default_modifier_states(db_manager):
    """Test that get_or_create_chat_config defaults modifier_states to {}."""
    config = db_manager.get_or_create_chat_config(789)
    assert config.modifier_states == {}


def test_get_or_create_chat_config_default_maintenance_mode(db_manager):
    """Test that get_or_create_chat_config defaults maintenance_mode to False."""
    config = db_manager.get_or_create_chat_config(999)
    assert config.maintenance_mode is False


def test_load_chat_config_with_null_modifier_states_defaults_to_empty(db_manager):
    """Test that loading config with NULL modifier_states defaults to {}.

    The modifier_states column is NOT NULL in the live schema, but a row with
    NULL can appear after a manual migration or schema repair.  We simulate
    that by inserting a row into a temporary table that has no NOT NULL
    constraint and then mocking the cursor so load_chat_config sees NULL.
    """
    from unittest.mock import patch, MagicMock
    import datetime

    now = datetime.datetime.utcnow().isoformat()

    # Build a fake sqlite3.Row-like mapping that load_chat_config will read
    fake_row = {
        'chat_id': 111,
        'input_hold_frames': None,
        'animation_duration': None,
        'auto_save_enabled': 1,
        'modifier_states': None,   # <-- the NULL case under test
        'message_base_text': None,
        'maintenance_mode': 0,
        'language': None,
        'created_at': now,
        'updated_at': now,
    }

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fake_row

    with patch.object(db_manager.connection, 'execute', return_value=mock_cursor):
        loaded = db_manager.load_chat_config(111)

    assert loaded is not None
    assert loaded.modifier_states == {}


def test_save_and_load_chat_config_multiple_modifier_states(db_manager):
    """Test round-trip with multiple modifier keys."""
    config = ChatConfig(chat_id=222, modifier_states={"run": True, "turbo": False})
    db_manager.save_chat_config(config)
    loaded = db_manager.load_chat_config(222)
    assert loaded is not None
    assert loaded.modifier_states == {"run": True, "turbo": False}


# ── helpers ──────────────────────────────────────────────────────────────────

def _ensure_chat(db_manager, chat_id: int) -> None:
    """Upsert a game_states row so FK constraints on recent_inputs are satisfied."""
    db_manager.save_game_state(ChatGameState(chat_id=chat_id))


def _insert_recent_input(db_manager, chat_id: int, user_id: int, timestamp: str):
    _ensure_chat(db_manager, chat_id)
    db_manager.append_recent_input(
        chat_id=chat_id, user_id=user_id, user_name="u",
        button="a", timestamp=timestamp,
    )


def _today_ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _yesterday_ts() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0).isoformat()


def _insert_alltime_count(db_manager, chat_id: int, user_id: int, count: int):
    _ensure_chat(db_manager, chat_id)
    db_manager.connection.execute(  # user_input_counts also has a FK on chat_id
        "INSERT INTO user_input_counts (chat_id, user_id, input_count) VALUES (?, ?, ?);",
        (chat_id, user_id, count),
    )
    db_manager.connection.commit()


# ── TestGetPlayerTodayInputCount ──────────────────────────────────────────────

class TestGetPlayerTodayInputCount:
    def test_returns_zero_when_no_rows(self, db_manager):
        assert db_manager.get_player_today_input_count(1, 99) == 0

    def test_returns_count_for_matching_user(self, db_manager):
        ts = _today_ts()
        _insert_recent_input(db_manager, 1, 42, ts)
        _insert_recent_input(db_manager, 1, 42, ts)
        _insert_recent_input(db_manager, 1, 42, ts)
        assert db_manager.get_player_today_input_count(1, 42) == 3

    def test_ignores_other_users(self, db_manager):
        ts = _today_ts()
        _insert_recent_input(db_manager, 1, 10, ts)
        _insert_recent_input(db_manager, 1, 10, ts)
        _insert_recent_input(db_manager, 1, 20, ts)
        assert db_manager.get_player_today_input_count(1, 10) == 2

    def test_ignores_other_chats(self, db_manager):
        ts = _today_ts()
        _insert_recent_input(db_manager, 1, 5, ts)
        _insert_recent_input(db_manager, 2, 5, ts)
        assert db_manager.get_player_today_input_count(1, 5) == 1

    def test_ignores_yesterday_rows(self, db_manager):
        _insert_recent_input(db_manager, 1, 7, _yesterday_ts())
        assert db_manager.get_player_today_input_count(1, 7) == 0


# ── TestGetPlayerAlltimeInputCount ────────────────────────────────────────────

class TestGetPlayerAlltimeInputCount:
    def test_returns_zero_when_no_rows(self, db_manager):
        assert db_manager.get_player_alltime_input_count(1, 99) == 0

    def test_returns_count_for_matching_user(self, db_manager):
        _insert_alltime_count(db_manager, 1, 42, 500)
        assert db_manager.get_player_alltime_input_count(1, 42) == 500

    def test_ignores_other_users(self, db_manager):
        _insert_alltime_count(db_manager, 1, 10, 100)
        _insert_alltime_count(db_manager, 1, 20, 200)
        assert db_manager.get_player_alltime_input_count(1, 10) == 100

    def test_ignores_other_chats(self, db_manager):
        _insert_alltime_count(db_manager, 1, 5, 50)
        _insert_alltime_count(db_manager, 2, 5, 999)
        assert db_manager.get_player_alltime_input_count(1, 5) == 50
