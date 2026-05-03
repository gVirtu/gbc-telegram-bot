# tests/test_shop_handlers.py
import os
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

import sqlite3
from src.shop.shop_manager import ShopManager
from src.shop.items import ShopItem


def _make_manager():
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

    return ShopManager(FakeConn())


def _add_profile(mgr, platform="telegram", user_id=1, earned=10000, spent=0):
    mgr._conn.execute(
        "INSERT INTO user_player_profiles (platform, user_id, total_score_earned, total_score_spent) "
        "VALUES (?, ?, ?, ?);",
        (platform, user_id, earned, spent),
    )


class TestValidatePurchase:
    def test_can_afford_returns_true_and_cost(self):
        mgr = _make_manager()
        _add_profile(mgr, earned=5000)
        item = ShopItem(id="react_fire", name_i18n_key="k", cost=50, effect={})
        can_afford, cost = mgr.validate_purchase("telegram", 1, item, 50)
        assert can_afford is True
        assert cost == 50

    def test_cannot_afford_returns_false(self):
        mgr = _make_manager()
        _add_profile(mgr, earned=10, spent=0)
        item = ShopItem(id="react_fire", name_i18n_key="k", cost=50, effect={})
        can_afford, cost = mgr.validate_purchase("telegram", 1, item, 50)
        assert can_afford is False
        assert cost == 50

    def test_one_time_already_owned_costs_zero(self):
        mgr = _make_manager()
        _add_profile(mgr, earned=0, spent=0)
        item = ShopItem(id="name_tag_red", name_i18n_key="k", cost=25000, effect={}, one_time_purchase=True)
        mgr._conn.execute(
            "INSERT INTO shop_transactions (platform, user_id, item_id, pts_spent) VALUES (?,?,?,?);",
            ("telegram", 1, "name_tag_red", 25000),
        )
        can_afford, cost = mgr.validate_purchase("telegram", 1, item, 50)
        assert can_afford is True
        assert cost == 0


class TestRecordTransaction:
    def test_records_transaction_and_deducts_balance(self):
        mgr = _make_manager()
        _add_profile(mgr, earned=5000, spent=0)
        mgr.record_transaction("telegram", 1, "react_fire", 50)
        assert mgr.get_balance("telegram", 1) == 4950
        row = mgr._conn.execute(
            "SELECT item_id, pts_spent FROM shop_transactions WHERE platform=? AND user_id=?;",
            ("telegram", 1),
        ).fetchone()
        assert row[0] == "react_fire"
        assert row[1] == 50

    def test_zero_cost_transaction_does_not_change_balance(self):
        mgr = _make_manager()
        _add_profile(mgr, earned=5000, spent=0)
        mgr.record_transaction("telegram", 1, "name_tag_white", 0)
        assert mgr.get_balance("telegram", 1) == 5000
