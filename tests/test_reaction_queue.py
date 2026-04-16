"""Tests for reaction queue DB methods."""

import os
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

import pytest
from src.db.manager import DatabaseManager


@pytest.fixture
def db(tmp_path):
    m = DatabaseManager(tmp_path / "test.db")
    m.initialize()
    yield m
    m.close()


class TestEnqueueReaction:
    def test_inserts_row(self, db):
        db.enqueue_reaction(chat_id=1, user_id=10, user_name="Alice", reaction_type="joy")
        row = db.connection.execute(
            "SELECT * FROM reaction_queue WHERE chat_id = 1"
        ).fetchone()
        assert row is not None
        assert row["user_name"] == "Alice"
        assert row["reaction_type"] == "joy"

    def test_multiple_chats_isolated(self, db):
        db.enqueue_reaction(1, 10, "Alice", "joy")
        db.enqueue_reaction(2, 20, "Bob", "joy")
        rows = db.connection.execute("SELECT * FROM reaction_queue WHERE chat_id = 1").fetchall()
        assert len(rows) == 1


class TestListNextReactions:
    def test_returns_empty_when_queue_empty(self, db):
        result = db.list_next_reactions(chat_id=1, limit=3)
        assert result == []

    def test_lists_oldest_first(self, db):
        db.enqueue_reaction(1, 10, "Alice", "joy")
        db.enqueue_reaction(1, 11, "Bob", "joy")
        db.enqueue_reaction(1, 12, "Carol", "joy")
        result = db.list_next_reactions(chat_id=1, limit=3)
        assert [r["user_name"] for r in result] == ["Alice", "Bob", "Carol"]
        assert [r["reaction_type"] for r in result] == ["joy", "joy", "joy"]
        assert [r["id"] for r in result] == [1, 2, 3]

    def test_does_not_remove_listed_rows(self, db):
        db.enqueue_reaction(1, 10, "Alice", "joy")
        db.list_next_reactions(chat_id=1, limit=3)
        remaining = db.connection.execute("SELECT * FROM reaction_queue WHERE chat_id = 1").fetchall()
        assert len(remaining) == 1

    def test_respects_limit(self, db):
        for i in range(5):
            db.enqueue_reaction(1, i, f"User{i}", "joy")
        result = db.list_next_reactions(chat_id=1, limit=3)
        assert len(result) == 3

    def test_only_lists_own_chat(self, db):
        db.enqueue_reaction(chat_id=1, user_id=10, user_name="Alice", reaction_type="joy")
        db.enqueue_reaction(chat_id=2, user_id=20, user_name="Bob", reaction_type="joy")
        result = db.list_next_reactions(chat_id=1, limit=3)
        assert len(result) == 1
        assert result[0]["user_name"] == "Alice"
        remaining = db.connection.execute("SELECT * FROM reaction_queue WHERE chat_id = 2").fetchall()
        assert len(remaining) == 1


class TestDeleteReactions:
    def test_removes_specified_rows(self, db):
        db.enqueue_reaction(1, 10, "Alice", "joy")
        db.enqueue_reaction(1, 11, "Bob", "joy")

        listed = db.list_next_reactions(chat_id=1, limit=1)
        db.delete_reactions([listed[0]["id"]])

        remaining = db.connection.execute(
            "SELECT user_name FROM reaction_queue WHERE chat_id = 1 ORDER BY id ASC"
        ).fetchall()
        assert [row["user_name"] for row in remaining] == ["Bob"]

    def test_empty_ids_is_no_op(self, db):
        db.enqueue_reaction(1, 10, "Alice", "joy")

        db.delete_reactions([])

        remaining = db.connection.execute("SELECT * FROM reaction_queue WHERE chat_id = 1").fetchall()
        assert len(remaining) == 1

    def test_list_then_delete_matches_previous_pop_behavior(self, db):
        for i, name in enumerate(["Alice", "Bob", "Carol", "Dave"]):
            db.enqueue_reaction(1, i, name, "joy")

        listed = db.list_next_reactions(chat_id=1, limit=3)
        db.delete_reactions([row["id"] for row in listed])

        assert [row["user_name"] for row in listed] == ["Alice", "Bob", "Carol"]
        remaining = db.connection.execute(
            "SELECT user_name FROM reaction_queue WHERE chat_id = 1 ORDER BY id ASC"
        ).fetchall()
        assert [row["user_name"] for row in remaining] == ["Dave"]
