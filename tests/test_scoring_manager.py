"""Tests for the ScoringManager and player points system."""

import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ["PYTEST_CURRENT_TEST"] = "1"

from src.db.connection import DatabaseConnection
from src.utils.scoring_manager import ScoringManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "test_scoring.db"


@pytest.fixture
def db_conn(db_path) -> DatabaseConnection:
    conn = DatabaseConnection(db_path)
    conn.initialize()
    return conn


@pytest.fixture
def manager(db_conn) -> ScoringManager:
    return ScoringManager(db_conn)


def _ensure_game_state(db_conn: DatabaseConnection, chat_id: int) -> None:
    """Insert a game_states row so recent_inputs FK is satisfied."""
    db_conn.execute(
        """INSERT OR IGNORE INTO game_states
           (chat_id, input_in_progress, created_at, updated_at)
           VALUES (?, 0, '2026-01-01T00:00:00', '2026-01-01T00:00:00');""",
        (chat_id,),
    )
    db_conn.commit()


def _insert_recent_inputs(db_conn: DatabaseConnection, chat_id: int, user_id: int, count: int) -> None:
    """Insert N recent_inputs rows for a given user in a given chat."""
    _ensure_game_state(db_conn, chat_id)
    for i in range(count):
        db_conn.execute(
            "INSERT INTO recent_inputs (chat_id, user_id, user_name, button, timestamp) VALUES (?, ?, ?, ?, ?);",
            (chat_id, user_id, "user", "a", f"2026-01-01T00:00:{i:02d}"),
        )
    db_conn.commit()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _yesterday() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _two_days_ago() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()


# ---------------------------------------------------------------------------
# Base score (diversity window)
# ---------------------------------------------------------------------------

class TestBaseScore:
    def test_no_prior_inputs_gives_max_score(self, manager):
        """With empty window, user gets player_input_max_score base points."""
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = 10
            mock_settings.daily_streak_score_bonus = 0
            scored = manager.score_input("telegram", 1, 100, "a")
        assert scored.base_score == 10

    def test_same_user_inputs_reduce_score(self, manager, db_conn):
        """Each prior same-user input in the window reduces base score by 1."""
        _insert_recent_inputs(db_conn, chat_id=100, user_id=1, count=3)
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = 10
            mock_settings.daily_streak_score_bonus = 0
            scored = manager.score_input("telegram", 1, 100, "a")
        assert scored.base_score == 10 - 3

    def test_score_never_goes_below_1(self, manager, db_conn):
        """Score is clamped to at least 1 even if user filled the entire window."""
        _insert_recent_inputs(db_conn, chat_id=100, user_id=1, count=15)
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = 10
            mock_settings.daily_streak_score_bonus = 0
            scored = manager.score_input("telegram", 1, 100, "a")
        assert scored.base_score == 1

    def test_eleven_inputs_in_a_row(self, manager, db_conn):
        """Simulate 11 consecutive inputs by the same user; scores: 10,9,...,1,1."""
        max_score = 10
        chat_id = 200
        _ensure_game_state(db_conn, chat_id)
        scores = []
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = max_score
            mock_settings.daily_streak_score_bonus = 0
            for i in range(11):
                ts = f"{_today()}T00:00:{i:02d}+00:00"
                scored = manager.score_input("telegram", 1, chat_id, "a")
                scores.append(scored.base_score)
                # Simulate what append_recent_input does: insert the row
                db_conn.execute(
                    "INSERT INTO recent_inputs (chat_id, user_id, user_name, button, timestamp) VALUES (?, ?, ?, ?, ?);",
                    (chat_id, 1, "u", "a", ts),
                )
                db_conn.commit()
        assert scores == [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1]

    def test_other_users_in_window_do_not_reduce_score(self, manager, db_conn):
        """Other users in the window don't count against the target user."""
        _insert_recent_inputs(db_conn, chat_id=100, user_id=2, count=5)
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = 10
            mock_settings.daily_streak_score_bonus = 0
            scored = manager.score_input("telegram", 1, 100, "a")
        assert scored.base_score == 10


# ---------------------------------------------------------------------------
# Streak logic
# ---------------------------------------------------------------------------

class TestStreakLogic:
    def test_new_player_gets_streak_1_and_bonus(self, manager):
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = 10
            mock_settings.daily_streak_score_bonus = 50
            scored = manager.score_input("telegram", 42, 100, "a")
        assert scored.streak_bonus == 50
        profile = manager.get_player_profile("telegram", 42)
        assert profile.current_streak == 1
        assert profile.best_streak == 1

    def test_same_day_no_streak_change_no_bonus(self, manager):
        ts = f"{_today()}T00:00:00+00:00"
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = 10
            mock_settings.daily_streak_score_bonus = 50
            manager.score_input("telegram", 42, 100, "a")
            scored2 = manager.score_input("telegram", 42, 100, "b")
        assert scored2.streak_bonus == 0
        profile = manager.get_player_profile("telegram", 42)
        assert profile.current_streak == 1

    def test_next_day_increments_streak(self, manager):
        yesterday_ts = f"{_yesterday()}T00:00:00+00:00"
        today_ts = f"{_today()}T00:00:00+00:00"
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = 10
            mock_settings.daily_streak_score_bonus = 50
            # First play yesterday (simulate by manually inserting profile)
            manager._conn.execute(
                """INSERT INTO user_player_profiles
                   (platform, user_id, total_score_earned, total_score_spent,
                    current_streak, best_streak, best_streak_date, last_input_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
                ("telegram", 42, 60, 0, 1, 1, _yesterday(), yesterday_ts),
            )
            manager._conn.commit()
            scored = manager.score_input("telegram", 42, 100, "a")
        assert scored.streak_bonus == 2 * 50  # streak 2 × 50
        profile = manager.get_player_profile("telegram", 42)
        assert profile.current_streak == 2

    def test_gap_resets_streak(self, manager):
        old_ts = f"{_two_days_ago()}T00:00:00+00:00"
        today_ts = f"{_today()}T00:00:00+00:00"
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = 10
            mock_settings.daily_streak_score_bonus = 50
            manager._conn.execute(
                """INSERT INTO user_player_profiles
                   (platform, user_id, total_score_earned, total_score_spent,
                    current_streak, best_streak, best_streak_date, last_input_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
                ("telegram", 42, 110, 0, 2, 2, _two_days_ago(), old_ts),
            )
            manager._conn.commit()
            scored = manager.score_input("telegram", 42, 100, "a")
        assert scored.streak_bonus == 1 * 50
        profile = manager.get_player_profile("telegram", 42)
        assert profile.current_streak == 1
        assert profile.best_streak == 2  # best_streak preserved

    def test_best_streak_updates_when_exceeded(self, manager):
        yesterday_ts = f"{_yesterday()}T00:00:00+00:00"
        today_ts = f"{_today()}T00:00:00+00:00"
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = 10
            mock_settings.daily_streak_score_bonus = 50
            manager._conn.execute(
                """INSERT INTO user_player_profiles
                   (platform, user_id, total_score_earned, total_score_spent,
                    current_streak, best_streak, best_streak_date, last_input_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
                ("telegram", 42, 0, 0, 5, 5, _yesterday(), yesterday_ts),
            )
            manager._conn.commit()
            manager.score_input("telegram", 42, 100, "a")
        profile = manager.get_player_profile("telegram", 42)
        assert profile.current_streak == 6
        assert profile.best_streak == 6
        assert profile.best_streak_date == _today()

    def test_streak_only_increments_once_across_midnight_with_queued_inputs(self, manager):
        """Queued inputs from yesterday processed after midnight must not inflate streak."""
        from datetime import date, datetime, timezone
        # Pre-set a profile: streak=5, last_input_at=yesterday at 23:59
        manager._conn.execute(
            """INSERT INTO user_player_profiles
               (platform, user_id, total_score_earned, total_score_spent,
                current_streak, best_streak, best_streak_date, last_input_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
            ("telegram", 42, 500, 0, 5, 5, "2026-01-01", "2026-01-01T23:59:00+00:00"),
        )
        manager._conn.commit()
        with patch("src.utils.scoring_manager.settings") as s:
            s.player_input_max_score = 10
            s.daily_streak_score_bonus = 50
            with patch("src.utils.scoring_manager.datetime") as mock_dt:
                # Processing happens after midnight on the new day
                mock_dt.now.return_value = datetime(2026, 1, 2, 0, 0, 1, tzinfo=timezone.utc)
                mock_dt.fromisoformat = datetime.fromisoformat
                for i in range(3):
                    ts = f"2026-01-01T23:59:{i:02d}+00:00"  # all timestamps from yesterday
                    scored = manager.score_input("telegram", 42, 100, "a")

        profile = manager.get_player_profile("telegram", 42)
        assert profile.current_streak == 6, (
            f"Expected streak=6 (only one increment for crossing midnight)"
            f" but got {profile.current_streak}"
        )


# ---------------------------------------------------------------------------
# total_score_earned accumulation
# ---------------------------------------------------------------------------

class TestTotalScoreEarned:
    def test_total_score_earned_accumulates(self, manager):
        today_ts = f"{_today()}T00:00:00+00:00"
        with patch("src.utils.scoring_manager.settings") as mock_settings:
            mock_settings.player_input_max_score = 10
            mock_settings.daily_streak_score_bonus = 50
            s1 = manager.score_input("telegram", 1, 100, "a")
            # same day, no streak bonus
            s2 = manager.score_input("telegram", 1, 100, "b")
        profile = manager.get_player_profile("telegram", 1)
        assert profile.total_score_earned == s1.total_score + s2.total_score


# ---------------------------------------------------------------------------
# Error resilience
# ---------------------------------------------------------------------------

class TestErrorResilience:
    def test_db_failure_returns_zero_scores(self, manager):
        """Any DB error produces a zero-score ScoredInput so gameplay continues."""
        with patch.object(manager._conn, "execute", side_effect=RuntimeError("db gone")):
            scored = manager.score_input("telegram", 1, 100, "a")
        assert scored.base_score == 0
        assert scored.streak_bonus == 0
        assert scored.total_score == 0


# ---------------------------------------------------------------------------
# Migration: DEFAULT 0 on pre-existing rows
# ---------------------------------------------------------------------------

class TestMigrationDefaults:
    def test_pre_migration_rows_have_zero_scores(self, db_path):
        """Existing recent_inputs rows before migration have DEFAULT 0 scores."""
        conn = DatabaseConnection(db_path)
        conn.initialize()
        # Run only up to migration 013 by temporarily inserting a row before 015
        # Verify columns exist with default 0 after running all migrations (015 adds them)
        raw = sqlite3.connect(str(db_path))
        raw.execute("PRAGMA foreign_keys = ON;")
        raw.row_factory = sqlite3.Row
        raw.execute(
            "INSERT OR IGNORE INTO game_states (chat_id, input_in_progress, created_at, updated_at) VALUES (1, 0, '2026-01-01T00:00:00', '2026-01-01T00:00:00');"
        )
        raw.execute(
            "INSERT INTO recent_inputs (chat_id, user_id, user_name, button, timestamp) VALUES (1, 1, 'u', 'a', '2026-01-01T00:00:00');"
        )
        raw.commit()
        row = raw.execute("SELECT base_score, streak_bonus, total_score FROM recent_inputs LIMIT 1;").fetchone()
        assert row["base_score"] == 0
        assert row["streak_bonus"] == 0
        assert row["total_score"] == 0
        raw.close()


class TestPlayerProfileNameTagColor:
    def test_player_profile_has_name_tag_color_default(self, manager):
        """PlayerProfile has name_tag_color field defaulting to #FFFFFF."""
        from unittest.mock import patch
        _ensure_game_state(manager._conn, chat_id=1)
        with patch("src.utils.scoring_manager.settings") as s:
            s.player_input_max_score = 5
            s.daily_streak_score_bonus = 10
            manager.score_input("telegram", 1, 1, "a")
        profile = manager.get_player_profile("telegram", 1)
        assert profile is not None
        assert profile.name_tag_color == "#FFFFFF"


class TestScoredInputCurrentStreak:
    """Verify that score_input returns correct current_streak in ScoredInput."""

    def test_new_player_scored_input_has_streak_1(self, manager):
        _ensure_game_state(manager._conn, chat_id=99)
        with patch("src.utils.scoring_manager.settings") as s:
            s.player_input_max_score = 5
            s.daily_streak_score_bonus = 10
            result = manager.score_input("telegram", 99, 99, "a")
        assert result.current_streak == 1

    def test_next_day_scored_input_increments_streak(self, manager):
        from datetime import datetime, timezone
        _ensure_game_state(manager._conn, chat_id=100)
        day1_dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        day2_dt = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
        with patch("src.utils.scoring_manager.settings") as s:
            s.player_input_max_score = 5
            s.daily_streak_score_bonus = 10
            with patch("src.utils.scoring_manager.datetime") as mock_dt:
                mock_dt.now.return_value = day1_dt
                mock_dt.fromisoformat = datetime.fromisoformat
                manager.score_input("telegram", 100, 100, "a")
            with patch("src.utils.scoring_manager.datetime") as mock_dt:
                mock_dt.now.return_value = day2_dt
                mock_dt.fromisoformat = datetime.fromisoformat
                result = manager.score_input("telegram", 100, 100, "b")
        assert result.current_streak == 2

    def test_error_fallback_has_streak_0(self, manager):
        """score_input fallback on error returns current_streak=0."""
        with patch.object(manager, "_score_input_unsafe", side_effect=Exception("fail")):
            result = manager.score_input("telegram", 1, 1, "a")
        assert result.current_streak == 0


# ---------------------------------------------------------------------------
# get_player_profiles_batch
# ---------------------------------------------------------------------------

class TestGetPlayerProfilesBatch:
    def _insert_profile(self, db_conn, platform, user_id, color="#ffffff"):
        db_conn.execute(
            """INSERT INTO user_player_profiles
               (platform, user_id, total_score_earned, total_score_spent,
                current_streak, best_streak, best_streak_date, last_input_at, name_tag_color)
               VALUES (?, ?, 0, 0, 1, 1, '2026-01-01', '2026-01-01T00:00:00', ?);""",
            (platform, user_id, color),
        )
        db_conn.commit()

    def test_empty_user_ids_returns_empty(self, manager):
        result = manager.get_player_profiles_batch("telegram", [])
        assert result == {}

    def test_missing_users_absent_from_result(self, manager):
        result = manager.get_player_profiles_batch("telegram", [999, 1000])
        assert result == {}

    def test_single_user_returned(self, manager, db_conn):
        self._insert_profile(db_conn, "telegram", 1, "#ff0000")
        result = manager.get_player_profiles_batch("telegram", [1])
        assert 1 in result
        assert result[1].name_tag_color == "#ff0000"

    def test_multiple_users_returned(self, manager, db_conn):
        self._insert_profile(db_conn, "telegram", 10, "#aaaaaa")
        self._insert_profile(db_conn, "telegram", 20, "#bbbbbb")
        self._insert_profile(db_conn, "telegram", 30, "#cccccc")
        result = manager.get_player_profiles_batch("telegram", [10, 20, 30])
        assert set(result.keys()) == {10, 20, 30}

    def test_platform_filter(self, manager, db_conn):
        self._insert_profile(db_conn, "telegram", 5, "#111111")
        self._insert_profile(db_conn, "discord", 5, "#222222")
        result = manager.get_player_profiles_batch("discord", [5])
        assert 5 in result
        assert result[5].name_tag_color == "#222222"

    def test_partial_match_returns_only_found(self, manager, db_conn):
        self._insert_profile(db_conn, "telegram", 7, "#333333")
        result = manager.get_player_profiles_batch("telegram", [7, 8, 9])
        assert set(result.keys()) == {7}


def test_score_input_persists_user_name(manager, db_conn):
    """score_input saves user_name to user_player_profiles."""
    _ensure_game_state(db_conn, chat_id=1)
    manager.score_input(
        platform="telegram",
        user_id=42,
        chat_id=1,
        button="a",
        user_name="Alice",
    )
    cursor = db_conn.execute(
        "SELECT user_name FROM user_player_profiles WHERE user_id = 42;"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["user_name"] == "Alice"

def test_score_input_updates_user_name(manager, db_conn):
    """score_input updates user_name when user changes their name."""
    _ensure_game_state(db_conn, chat_id=1)
    manager.score_input(
        platform="telegram", user_id=42, chat_id=1,
        button="a", user_name="OldName",
    )
    manager.score_input(
        platform="telegram", user_id=42, chat_id=1,
        button="b", user_name="NewName",
    )
    cursor = db_conn.execute(
        "SELECT user_name FROM user_player_profiles WHERE user_id = 42;"
    )
    assert cursor.fetchone()["user_name"] == "NewName"
