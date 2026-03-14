"""Tests for append-only recent_inputs log in DatabaseManager."""
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from src.db.manager import DatabaseManager
from src.models.game_state import ChatGameState


@pytest.fixture
def db_manager(tmp_path):
    """Create a DatabaseManager with temporary database."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    yield manager
    manager.close()


def _create_game_state(db_manager, chat_id: int) -> None:
    """Helper: insert a game_states row so FK constraints are satisfied."""
    state = ChatGameState(chat_id=chat_id)
    db_manager.save_game_state(state)


def _ts(offset_seconds: int = 0) -> str:
    """Return an ISO timestamp offset from a fixed base time."""
    base = datetime(2026, 1, 1, 12, 0, 0)
    return (base + timedelta(seconds=offset_seconds)).isoformat()


class TestAppendRecentInput:
    def test_append_recent_input_inserts_row(self, db_manager):
        """append_recent_input inserts a single row into recent_inputs."""
        _create_game_state(db_manager, chat_id=1)

        db_manager.append_recent_input(
            chat_id=1,
            user_id=100,
            user_name="Alice",
            button="A",
            timestamp=_ts(0),
        )

        cursor = db_manager.connection.execute(
            "SELECT * FROM recent_inputs WHERE chat_id = 1;"
        )
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["user_id"] == 100
        assert rows[0]["user_name"] == "Alice"
        assert rows[0]["button"] == "A"


class TestGetRecentInputsForOverlay:
    def test_get_recent_inputs_for_overlay_returns_limit(self, db_manager):
        """Only the most recent `limit` rows are returned (default 30)."""
        _create_game_state(db_manager, chat_id=2)

        for i in range(35):
            db_manager.append_recent_input(
                chat_id=2,
                user_id=200,
                user_name="Bob",
                button="B",
                timestamp=_ts(i),
            )

        results = db_manager.get_recent_inputs_for_overlay(chat_id=2)
        assert len(results) == 30

    def test_get_recent_inputs_for_overlay_ordered_oldest_first(self, db_manager):
        """Results are ordered oldest-first."""
        _create_game_state(db_manager, chat_id=3)

        timestamps = [_ts(0), _ts(10), _ts(20)]
        for ts in timestamps:
            db_manager.append_recent_input(
                chat_id=3, user_id=300, user_name="Carol", button="UP", timestamp=ts
            )

        results = db_manager.get_recent_inputs_for_overlay(chat_id=3)
        assert len(results) == 3
        assert results[0]["timestamp"] == timestamps[0]
        assert results[1]["timestamp"] == timestamps[1]
        assert results[2]["timestamp"] == timestamps[2]

    def test_get_recent_inputs_for_overlay_returns_correct_keys(self, db_manager):
        """Each row has the expected keys."""
        _create_game_state(db_manager, chat_id=4)
        db_manager.append_recent_input(
            chat_id=4, user_id=400, user_name="Dave", button="START", timestamp=_ts(0)
        )

        results = db_manager.get_recent_inputs_for_overlay(chat_id=4)
        assert len(results) == 1
        row = results[0]
        assert set(row.keys()) == {"user_id", "user_name", "button", "timestamp"}
        assert row["button"] == "START"
        assert row["user_name"] == "Dave"


class TestPurgeOldRecentInputs:
    def test_purge_old_recent_inputs_deletes_old_rows(self, db_manager):
        """Rows older than N days are deleted; newer rows are preserved."""
        _create_game_state(db_manager, chat_id=5)

        old_ts = (datetime.utcnow() - timedelta(days=10)).isoformat()
        new_ts = datetime.utcnow().isoformat()

        db_manager.append_recent_input(
            chat_id=5, user_id=500, user_name="Eve", button="A", timestamp=old_ts
        )
        db_manager.append_recent_input(
            chat_id=5, user_id=500, user_name="Eve", button="B", timestamp=new_ts
        )

        deleted = db_manager.purge_old_recent_inputs(older_than_days=5)
        assert deleted == 1

        cursor = db_manager.connection.execute(
            "SELECT button FROM recent_inputs WHERE chat_id = 5;"
        )
        remaining = [r["button"] for r in cursor.fetchall()]
        assert remaining == ["B"]

    def test_purge_old_recent_inputs_noop_when_zero(self, db_manager):
        """older_than_days=0 is a no-op: nothing is deleted."""
        _create_game_state(db_manager, chat_id=6)

        old_ts = (datetime.utcnow() - timedelta(days=100)).isoformat()
        db_manager.append_recent_input(
            chat_id=6, user_id=600, user_name="Frank", button="A", timestamp=old_ts
        )

        deleted = db_manager.purge_old_recent_inputs(older_than_days=0)
        assert deleted == 0

        cursor = db_manager.connection.execute(
            "SELECT COUNT(*) as cnt FROM recent_inputs WHERE chat_id = 6;"
        )
        assert cursor.fetchone()["cnt"] == 1


class TestLoadRecentInputsGroupedView:
    def test_load_recent_inputs_reconstructs_grouped_view(self, db_manager):
        """Individual rows are collapsed into max-3 consecutive same-user groups."""
        _create_game_state(db_manager, chat_id=7)

        # User 700 presses A, B (consecutive), then user 701 presses UP,
        # then user 700 presses START — 3 groups total.
        rows = [
            (700, "Alice", "A", _ts(0)),
            (700, "Alice", "B", _ts(1)),
            (701, "Bob", "UP", _ts(2)),
            (700, "Alice", "START", _ts(3)),
        ]
        for user_id, user_name, button, ts in rows:
            db_manager.append_recent_input(
                chat_id=7, user_id=user_id, user_name=user_name,
                button=button, timestamp=ts
            )

        groups = db_manager._load_recent_inputs(chat_id=7)
        assert len(groups) == 3
        # First group: Alice with A + B
        assert groups[0]["user_id"] == 700
        assert groups[0]["buttons"] == ["A", "B"]
        # Second group: Bob with UP
        assert groups[1]["user_id"] == 701
        assert groups[1]["buttons"] == ["UP"]
        # Third group: Alice with START
        assert groups[2]["user_id"] == 700
        assert groups[2]["buttons"] == ["START"]

    def test_load_recent_inputs_max_3_groups(self, db_manager):
        """Only the last 3 groups are returned even if there are more."""
        _create_game_state(db_manager, chat_id=8)

        # Create 5 groups by alternating users
        for i in range(5):
            user_id = 800 + (i % 2)
            db_manager.append_recent_input(
                chat_id=8, user_id=user_id, user_name=f"User{i % 2}",
                button="A", timestamp=_ts(i * 10)
            )

        groups = db_manager._load_recent_inputs(chat_id=8)
        assert len(groups) <= 3

    def test_load_recent_inputs_each_group_has_required_keys(self, db_manager):
        """Each group dict has the expected keys."""
        _create_game_state(db_manager, chat_id=9)
        db_manager.append_recent_input(
            chat_id=9, user_id=900, user_name="Grace", button="DOWN", timestamp=_ts(0)
        )

        groups = db_manager._load_recent_inputs(chat_id=9)
        assert len(groups) == 1
        g = groups[0]
        assert "user_id" in g
        assert "user_name" in g
        assert "buttons" in g
        assert "timestamp" in g
        assert isinstance(g["buttons"], list)


class TestSaveRecentInputsIsNoop:
    def test_save_recent_inputs_is_noop(self, db_manager):
        """_save_recent_inputs must not delete existing rows (it's a no-op)."""
        _create_game_state(db_manager, chat_id=10)

        # Pre-populate via append
        db_manager.append_recent_input(
            chat_id=10, user_id=1000, user_name="Hank", button="A", timestamp=_ts(0)
        )
        db_manager.append_recent_input(
            chat_id=10, user_id=1000, user_name="Hank", button="B", timestamp=_ts(1)
        )

        # Call _save_recent_inputs with arbitrary data — rows must survive
        db_manager._save_recent_inputs(chat_id=10, inputs=[
            {"user_id": 999, "user_name": "Ghost", "buttons": ["X"], "timestamp": _ts(5)}
        ])

        cursor = db_manager.connection.execute(
            "SELECT COUNT(*) as cnt FROM recent_inputs WHERE chat_id = 10;"
        )
        assert cursor.fetchone()["cnt"] == 2
