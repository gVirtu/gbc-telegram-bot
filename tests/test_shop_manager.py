"""Tests for ShopManager."""

import os

os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

import sqlite3
import pytest
from src.shop.shop_manager import ShopManager, PurchaseResult
from src.shop.items import SHOP_CATEGORIES


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


class TestGetCategories:
    def test_returns_all_categories(self, tmp_path):
        mgr = _make_manager(tmp_path)
        cats = mgr.get_categories()
        assert len(cats) == 2
        assert cats[0].id == "name_tags"
        assert cats[1].id == "reactions"

    def test_get_category_known(self, tmp_path):
        mgr = _make_manager(tmp_path)
        cat = mgr.get_category("reactions")
        assert cat is not None
        assert cat.id == "reactions"
        assert len(cat.items) == 18

    def test_get_category_unknown(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.get_category("does_not_exist") is None


class TestGetCategoryPage:
    def test_clamps_out_of_range_page(self, tmp_path):
        mgr = _make_manager(tmp_path)
        items, total_pages = mgr.get_category_page("name_tags", 99)
        assert items == mgr.get_category_page("name_tags", total_pages - 1)[0]

    def test_first_page_name_tags(self, tmp_path):
        mgr = _make_manager(tmp_path)
        items, total_pages = mgr.get_category_page("name_tags", 0)
        assert len(items) == 3
        assert items[0].id == "name_tag_white"
        assert total_pages == 3  # 7 items / 3 per page = 3 pages

    def test_second_page_name_tags(self, tmp_path):
        mgr = _make_manager(tmp_path)
        items, _ = mgr.get_category_page("name_tags", 1)
        assert len(items) == 3
        assert items[0].id == "name_tag_blue"

    def test_reactions_all_on_one_page(self, tmp_path):
        mgr = _make_manager(tmp_path)
        items, total_pages = mgr.get_category_page("reactions", 0)
        assert len(items) == 18
        assert total_pages == 1

    def test_unknown_category_returns_empty(self, tmp_path):
        mgr = _make_manager(tmp_path)
        items, total_pages = mgr.get_category_page("nope", 0)
        assert items == []
        assert total_pages == 1


class TestGetItem:
    def test_finds_item_in_name_tags(self, tmp_path):
        mgr = _make_manager(tmp_path)
        item = mgr.get_item("name_tag_red")
        assert item is not None
        assert item.cost == 25000

    def test_finds_item_in_reactions(self, tmp_path):
        mgr = _make_manager(tmp_path)
        item = mgr.get_item("react_joy")
        assert item is not None
        assert item.effect.get("reaction") == "joy"

    def test_returns_none_for_unknown(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.get_item("does_not_exist") is None


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
        mgr = self._setup(tmp_path, earned=30000)
        result = mgr.purchase("telegram", 1, "name_tag_red")
        assert result.success is True
        assert result.item.id == "name_tag_red"
        row = mgr._conn.execute(
            "SELECT name_tag_color, total_score_spent FROM user_player_profiles "
            "WHERE platform = ? AND user_id = ?;",
            ("telegram", 1),
        ).fetchone()
        assert row["name_tag_color"] == "#FF8888"
        assert row["total_score_spent"] == 25000

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
