"""Tests for ShopManager."""

import os

os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

import sqlite3
import pytest
from src.shop.shop_manager import ShopManager, PurchaseResult


def _make_manager(tmp_path):
    """Create an in-memory ShopManager with a minimal DB schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE chat_configs (
            chat_id INTEGER PRIMARY KEY,
            platform TEXT NOT NULL DEFAULT 'telegram'
        );
    """)
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
    conn.commit()

    class FakeConn:
        def execute(self, sql, params=()):
            return conn.execute(sql, params)
        def commit(self):
            conn.commit()

    return ShopManager(FakeConn())


class TestGetBalance:
    def test_returns_zero_for_no_profile(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.get_balance("telegram", 999) == 0

    def test_returns_earned_minus_spent(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._conn.execute(
            "INSERT INTO user_player_profiles (platform, user_id, total_score_earned, total_score_spent) "
            "VALUES (?, ?, ?, ?);",
            ("telegram", 1, 10000, 3000),
        )
        assert mgr.get_balance("telegram", 1) == 7000

    def test_returns_zero_if_fully_spent(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._conn.execute(
            "INSERT INTO user_player_profiles (platform, user_id, total_score_earned, total_score_spent) "
            "VALUES (?, ?, ?, ?);",
            ("telegram", 2, 5000, 5000),
        )
        assert mgr.get_balance("telegram", 2) == 0


class TestGetPage:
    def test_first_page(self, tmp_path):
        mgr = _make_manager(tmp_path)
        items, total_pages = mgr.get_page(0)
        assert len(items) == 3
        assert items[0].id == "name_tag_white"
        assert total_pages == 3

    def test_last_page(self, tmp_path):
        mgr = _make_manager(tmp_path)
        items, total_pages = mgr.get_page(2)
        assert len(items) == 2  # 8 items, page 2 has 2
        assert total_pages == 3

    def test_single_page_case(self, tmp_path):
        """Clamps out-of-range page to valid range."""
        mgr = _make_manager(tmp_path)
        items, total_pages = mgr.get_page(99)
        assert items == mgr.get_page(total_pages - 1)[0]

    def test_boundary_index(self, tmp_path):
        mgr = _make_manager(tmp_path)
        items1, _ = mgr.get_page(1)
        assert len(items1) == 3
        assert items1[0].id == "name_tag_blue"


class TestValidateShopAccess:
    def test_unknown_chat_returns_false_none(self, tmp_path):
        mgr = _make_manager(tmp_path)
        ok, key = mgr.validate_shop_access("telegram", 1, chat_id=999)
        assert ok is False
        assert key is None

    def test_no_profile_returns_false_error_key(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._conn.execute("INSERT INTO chat_configs (chat_id) VALUES (?);", (42,))
        ok, key = mgr.validate_shop_access("telegram", 1, chat_id=42)
        assert ok is False
        assert key == "shop.no_profile"

    def test_valid_returns_true_none(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._conn.execute("INSERT INTO chat_configs (chat_id) VALUES (?);", (42,))
        mgr._conn.execute(
            "INSERT INTO user_player_profiles (platform, user_id, total_score_earned) VALUES (?, ?, ?);",
            ("telegram", 1, 0),
        )
        ok, key = mgr.validate_shop_access("telegram", 1, chat_id=42)
        assert ok is True
        assert key is None


class TestPurchase:
    def _setup(self, tmp_path, earned=10000, spent=0):
        mgr = _make_manager(tmp_path)
        mgr._conn.execute(
            "INSERT INTO user_player_profiles (platform, user_id, total_score_earned, total_score_spent) "
            "VALUES (?, ?, ?, ?);",
            ("telegram", 1, earned, spent),
        )
        return mgr

    def test_success_updates_color_and_spent(self, tmp_path):
        mgr = self._setup(tmp_path, earned=10000)
        result = mgr.purchase("telegram", 1, "name_tag_red")
        assert result.success is True
        assert result.item.id == "name_tag_red"
        row = mgr._conn.execute(
            "SELECT name_tag_color, total_score_spent FROM user_player_profiles "
            "WHERE platform = ? AND user_id = ?;",
            ("telegram", 1),
        ).fetchone()
        assert row["name_tag_color"] == "#FF0000"
        assert row["total_score_spent"] == 5000

    def test_insufficient_funds(self, tmp_path):
        mgr = self._setup(tmp_path, earned=100, spent=0)
        result = mgr.purchase("telegram", 1, "name_tag_red")
        assert result.success is False
        assert result.error_i18n_key == "shop.insufficient_funds"
        assert result.item is not None

    def test_unknown_item_returns_error_no_key(self, tmp_path):
        mgr = self._setup(tmp_path, earned=10000)
        result = mgr.purchase("telegram", 1, "does_not_exist")
        assert result.success is False
        assert result.error_i18n_key is None
        assert result.item is None

    def test_free_item_can_be_purchased_with_zero_balance(self, tmp_path):
        mgr = self._setup(tmp_path, earned=0, spent=0)
        result = mgr.purchase("telegram", 1, "name_tag_white")
        assert result.success is True
        row = mgr._conn.execute(
            "SELECT name_tag_color FROM user_player_profiles WHERE platform = ? AND user_id = ?;",
            ("telegram", 1),
        ).fetchone()
        assert row["name_tag_color"] == "#FFFFFF"
