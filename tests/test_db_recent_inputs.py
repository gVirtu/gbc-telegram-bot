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
        assert set(row.keys()) == {"user_id", "user_name", "button", "timestamp", "current_streak", "modifier"}
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


class TestModifierPersistence:
    def test_append_and_retrieve_modifier(self, db_manager):
        """modifier value is stored and returned by get_recent_inputs_for_overlay."""
        _create_game_state(db_manager, chat_id=10)

        db_manager.append_recent_input(
            chat_id=10,
            user_id=1,
            user_name="Alice",
            button="up",
            timestamp=_ts(0),
            modifier="b",
        )

        rows = db_manager.get_recent_inputs_for_overlay(chat_id=10)
        assert len(rows) == 1
        assert rows[0]["modifier"] == "b"

    def test_append_without_modifier_returns_none(self, db_manager):
        """Omitting modifier defaults to None in get_recent_inputs_for_overlay."""
        _create_game_state(db_manager, chat_id=11)

        db_manager.append_recent_input(
            chat_id=11,
            user_id=2,
            user_name="Bob",
            button="a",
            timestamp=_ts(0),
        )

        rows = db_manager.get_recent_inputs_for_overlay(chat_id=11)
        assert rows[0]["modifier"] is None


class TestGetRecentInputsForOverlayStreak:
    """Tests for streak JOIN in get_recent_inputs_for_overlay."""

    def test_overlay_returns_streak_from_profile(self, db_manager):
        """Row with matching user_player_profiles returns correct streak."""
        _create_game_state(db_manager, chat_id=5)
        db_manager.append_recent_input(
            chat_id=5, user_id=42, user_name="Alice", button="a", timestamp=_ts(0)
        )
        # Insert player profile with streak=5
        db_manager.connection.execute(
            """INSERT INTO user_player_profiles
               (platform, user_id, total_score_earned, total_score_spent,
                current_streak, best_streak, best_streak_date, last_input_at)
               VALUES ('telegram', 42, 0, 0, 5, 5, '2026-01-01', '2026-01-01T00:00:00');"""
        )
        db_manager.connection.commit()

        rows = db_manager.get_recent_inputs_for_overlay(chat_id=5)
        assert len(rows) == 1
        assert rows[0]["current_streak"] == 5

    def test_overlay_unmatched_user_gets_streak_zero(self, db_manager):
        """Row without matching user_player_profiles gets current_streak=0."""
        _create_game_state(db_manager, chat_id=6)
        db_manager.append_recent_input(
            chat_id=6, user_id=99, user_name="Bob", button="b", timestamp=_ts(0)
        )

        rows = db_manager.get_recent_inputs_for_overlay(chat_id=6)
        assert len(rows) == 1
        assert rows[0]["current_streak"] == 0


class TestInputStats:
    """Tests for get_today_input_stats and get_alltime_input_stats."""

    @pytest.fixture
    def manager(self, tmp_path):
        from src.utils.state_manager import StateManager
        return StateManager(data_dir=tmp_path)

    def _insert_input(self, manager, chat_id, user_id, user_name, timestamp):
        manager.connection.execute(
            """INSERT INTO recent_inputs
               (chat_id, user_id, user_name, button, timestamp)
               VALUES (?, ?, ?, 'a', ?);""",
            (chat_id, user_id, user_name, timestamp),
        )
        manager.connection.commit()

    def _ensure_state(self, manager, chat_id):
        manager.connection.execute(
            """INSERT OR IGNORE INTO game_states
               (chat_id, input_in_progress, created_at, updated_at)
               VALUES (?, 0, '2026-01-01T00:00:00', '2026-01-01T00:00:00');""",
            (chat_id,),
        )
        manager.connection.commit()

    def test_get_today_input_stats_empty(self, manager):
        """Returns zero total and empty list when no inputs today."""
        self._ensure_state(manager, chat_id=1)
        stats = manager.get_today_input_stats(chat_id=1)
        assert stats["total"] == 0
        assert stats["top_players"] == []

    def test_get_today_input_stats_counts_today_only(self, manager):
        """Only counts inputs with today's UTC date."""
        self._ensure_state(manager, chat_id=1)
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        yesterday = "2000-01-01"

        self._insert_input(manager, 1, 10, "Alice", f"{today}T10:00:00")
        self._insert_input(manager, 1, 10, "Alice", f"{today}T11:00:00")
        self._insert_input(manager, 1, 20, "Bob",   f"{yesterday}T10:00:00")

        stats = manager.get_today_input_stats(chat_id=1)
        assert stats["total"] == 2
        assert len(stats["top_players"]) == 1
        assert stats["top_players"][0]["user_name"] == "Alice"
        assert stats["top_players"][0]["count"] == 2

    def test_get_today_input_stats_top3_order(self, manager):
        """top_players sorted descending by count, max 3 entries."""
        self._ensure_state(manager, chat_id=2)
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        for _ in range(5):
            self._insert_input(manager, 2, 1, "A", f"{today}T10:00:00")
        for _ in range(3):
            self._insert_input(manager, 2, 2, "B", f"{today}T10:00:00")
        for _ in range(2):
            self._insert_input(manager, 2, 3, "C", f"{today}T10:00:00")
        self._insert_input(manager, 2, 4, "D", f"{today}T10:00:00")

        stats = manager.get_today_input_stats(chat_id=2)
        assert stats["total"] == 11
        names = [p["user_name"] for p in stats["top_players"]]
        assert names == ["A", "B", "C"]

    def test_get_alltime_input_stats_empty(self, manager):
        """Returns zero total and empty list when no all-time counts."""
        self._ensure_state(manager, chat_id=3)
        stats = manager.get_alltime_input_stats(chat_id=3)
        assert stats["total"] == 0
        assert stats["top_players"] == []

    def test_get_alltime_input_stats_uses_user_input_counts(self, manager):
        """Uses user_input_counts table, joins user_player_profiles for names."""
        self._ensure_state(manager, chat_id=4)
        # Insert user_input_counts rows
        manager.connection.execute(
            "INSERT INTO user_input_counts (chat_id, user_id, input_count) VALUES (?, ?, ?);",
            (4, 10, 100),
        )
        manager.connection.execute(
            "INSERT INTO user_input_counts (chat_id, user_id, input_count) VALUES (?, ?, ?);",
            (4, 20, 50),
        )
        # Insert profiles with user_name
        manager.connection.execute(
            """INSERT INTO user_player_profiles
               (platform, user_id, user_name, total_score_earned, total_score_spent,
                current_streak, best_streak, last_input_at)
               VALUES ('telegram', 10, 'Alice', 0, 0, 0, 0, '2026-01-01');"""
        )
        manager.connection.execute(
            """INSERT INTO user_player_profiles
               (platform, user_id, user_name, total_score_earned, total_score_spent,
                current_streak, best_streak, last_input_at)
               VALUES ('telegram', 20, 'Bob', 0, 0, 0, 0, '2026-01-01');"""
        )
        manager.connection.commit()

        stats = manager.get_alltime_input_stats(chat_id=4)
        assert stats["total"] == 150
        assert stats["top_players"][0]["user_name"] == "Alice"
        assert stats["top_players"][0]["count"] == 100
        assert stats["top_players"][1]["user_name"] == "Bob"
        assert stats["top_players"][1]["count"] == 50
