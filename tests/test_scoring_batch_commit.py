"""Tests for deferred-commit behavior in score_input and append_recent_input."""

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from src.db.connection import DatabaseConnection
from src.db.manager import DatabaseManager
from src.utils.scoring_manager import ScoringManager


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "test_batch.db"


@pytest.fixture
def db_conn(db_path) -> DatabaseConnection:
    conn = DatabaseConnection(db_path)
    conn.initialize()
    return conn


@pytest.fixture
def manager(db_conn) -> ScoringManager:
    return ScoringManager(db_conn)


@pytest.fixture
def state_mgr(db_conn) -> DatabaseManager:
    return DatabaseManager.__new__(DatabaseManager)


def _ensure_game_state(db_conn: DatabaseConnection, chat_id: int) -> None:
    db_conn.execute(
        """INSERT OR IGNORE INTO game_states
           (chat_id, input_in_progress, created_at, updated_at)
           VALUES (?, 0, '2026-01-01T00:00:00', '2026-01-01T00:00:00');""",
        (chat_id,),
    )
    db_conn.commit()


def _second_conn(db_path: Path) -> sqlite3.Connection:
    """Open a separate connection to observe externally committed data."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


class TestScoreInputDeferredCommit:
    def test_commit_true_is_default_and_visible_immediately(self, manager, db_path):
        _ensure_game_state(manager._conn, 100)
        with patch("src.utils.scoring_manager.settings") as s:
            s.player_input_max_score = 5
            s.daily_streak_score_bonus = 10
            manager.score_input("telegram", 1, 100, "A", "2026-01-01T00:00:00")

        ext = _second_conn(db_path)
        rows = ext.execute(
            "SELECT * FROM user_player_profiles WHERE user_id = 1;"
        ).fetchall()
        ext.close()
        assert len(rows) == 1

    def test_commit_false_not_visible_on_external_connection(self, manager, db_path):
        _ensure_game_state(manager._conn, 101)
        with patch("src.utils.scoring_manager.settings") as s:
            s.player_input_max_score = 5
            s.daily_streak_score_bonus = 10
            manager.score_input("telegram", 2, 101, "B", "2026-01-01T00:00:00", commit=False)

        ext = _second_conn(db_path)
        rows = ext.execute(
            "SELECT * FROM user_player_profiles WHERE user_id = 2;"
        ).fetchall()
        ext.close()
        assert len(rows) == 0  # not yet committed

    def test_commit_false_then_explicit_commit_makes_visible(self, manager, db_path):
        _ensure_game_state(manager._conn, 102)
        with patch("src.utils.scoring_manager.settings") as s:
            s.player_input_max_score = 5
            s.daily_streak_score_bonus = 10
            for i in range(3):
                manager.score_input("telegram", 3, 102, "A", f"2026-01-01T00:0{i}:00", commit=False)

        manager._conn.commit()

        ext = _second_conn(db_path)
        rows = ext.execute(
            "SELECT * FROM user_player_profiles WHERE user_id = 3;"
        ).fetchall()
        ext.close()
        assert len(rows) == 1  # upserted, so still 1 row

    def test_diversity_window_sees_uncommitted_inserts_same_connection(self, manager, db_path):
        """Score for button N accounts for buttons 0..N-1 even without intermediate commits."""
        _ensure_game_state(manager._conn, 103)
        scores = []
        with patch("src.utils.scoring_manager.settings") as s:
            s.player_input_max_score = 5
            s.daily_streak_score_bonus = 0
            for i in range(3):
                scored = manager.score_input("telegram", 4, 103, "A", f"2026-01-01T00:0{i}:00", commit=False)
                # Insert into recent_inputs so diversity window grows
                manager._conn.execute(
                    "INSERT INTO recent_inputs (chat_id, user_id, user_name, button, timestamp) VALUES (103, 4, 'u', 'A', ?);",
                    (f"2026-01-01T00:0{i}:00",),
                )
                scores.append(scored.base_score)
        manager._conn.commit()
        # Later scores should be lower as same_user_count grows
        assert scores[0] >= scores[1] >= scores[2]


class TestAppendRecentInputDeferredCommit:
    def test_commit_true_default_visible_immediately(self, db_conn, db_path):
        _ensure_game_state(db_conn, 200)
        mgr = DatabaseManager.__new__(DatabaseManager)
        mgr.connection = db_conn
        mgr.append_recent_input(200, 10, "alice", "A", "2026-01-01T00:00:00")

        ext = _second_conn(db_path)
        rows = ext.execute("SELECT * FROM recent_inputs WHERE chat_id = 200;").fetchall()
        ext.close()
        assert len(rows) == 1

    def test_commit_false_not_visible_externally(self, db_conn, db_path):
        _ensure_game_state(db_conn, 201)
        mgr = DatabaseManager.__new__(DatabaseManager)
        mgr.connection = db_conn
        mgr.append_recent_input(201, 11, "bob", "B", "2026-01-01T00:00:00", commit=False)

        ext = _second_conn(db_path)
        rows = ext.execute("SELECT * FROM recent_inputs WHERE chat_id = 201;").fetchall()
        ext.close()
        assert len(rows) == 0

    def test_batch_insert_then_commit(self, db_conn, db_path):
        _ensure_game_state(db_conn, 202)
        mgr = DatabaseManager.__new__(DatabaseManager)
        mgr.connection = db_conn
        for i in range(5):
            mgr.append_recent_input(202, 12, "carol", "A", f"2026-01-01T00:0{i}:00", commit=False)
        db_conn.commit()

        ext = _second_conn(db_path)
        rows = ext.execute("SELECT * FROM recent_inputs WHERE chat_id = 202;").fetchall()
        ext.close()
        assert len(rows) == 5
