"""Tests for reaction shop item and purchase."""

import os
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

import sqlite3
from src.shop.shop_manager import ShopManager
from src.shop.items import SHOP_CATEGORIES


def _make_manager(with_reaction_queue=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE user_player_profiles (
            platform TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            total_score_earned INTEGER NOT NULL DEFAULT 0,
            total_score_spent INTEGER NOT NULL DEFAULT 0,
            name_tag_color TEXT NOT NULL DEFAULT '#FFFFFF',
            UNIQUE(platform, user_id)
        );
    """)
    if with_reaction_queue:
        conn.execute("""
            CREATE TABLE reaction_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                reaction_type TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
    conn.execute("""
        CREATE TABLE shop_transactions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            platform     TEXT    NOT NULL,
            user_id      INTEGER NOT NULL,
            item_id      TEXT    NOT NULL,
            pts_spent    INTEGER NOT NULL,
            purchased_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()

    class FakeConn:
        def execute(self, sql, params=()):
            return conn.execute(sql, params)
        def commit(self):
            conn.commit()

    return ShopManager(FakeConn()), conn


def _all_items():
    return [item for cat in SHOP_CATEGORIES for item in cat.items]


def _get_item(category_id: str, item_id: str):
    category = next(cat for cat in SHOP_CATEGORIES if cat.id == category_id)
    return next(item for item in category.items if item.id == item_id)


class TestReactJoyItem:
    def test_react_joy_in_shop_items(self):
        ids = [i.id for i in _all_items()]
        assert "react_joy" in ids

    def test_react_joy_has_reaction_effect(self):
        item = next(i for i in _all_items() if i.id == "react_joy")
        assert item.effect.get("reaction") == "joy"


class TestPurchaseReaction:
    def _setup_user(self, conn, earned=100):
        conn.execute(
            "INSERT INTO user_player_profiles (platform, user_id, total_score_earned) VALUES (?, ?, ?);",
            ("telegram", 1, earned),
        )
        conn.commit()

    def test_reaction_purchase_enqueues_row(self):
        mgr, conn = _make_manager()
        self._setup_user(conn)
        result = mgr.purchase("telegram", 1, _get_item("reactions", "react_joy"), chat_id=42, user_name="Alice")
        assert result.success is True
        row = conn.execute("SELECT * FROM reaction_queue WHERE chat_id = 42").fetchone()
        assert row is not None
        assert row["user_name"] == "Alice"
        assert row["reaction_type"] == "joy"

    def test_reaction_purchase_deducts_score(self):
        mgr, conn = _make_manager()
        self._setup_user(conn)
        mgr.purchase("telegram", 1, _get_item("reactions", "react_joy"), chat_id=42, user_name="Alice")
        row = conn.execute(
            "SELECT total_score_spent FROM user_player_profiles WHERE user_id = 1"
        ).fetchone()
        assert row["total_score_spent"] == 50

    def test_reaction_purchase_insufficient_funds(self):
        mgr, conn = _make_manager()
        self._setup_user(conn, earned=0)
        result = mgr.purchase("telegram", 1, _get_item("reactions", "react_joy"), chat_id=42, user_name="Alice")
        assert result.success is False
        assert result.error_i18n_key == "shop.insufficient_funds"
