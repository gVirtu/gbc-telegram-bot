"""Tests for _build_recent_inputs_grouped helper."""

import unittest
from src.handlers.input_handler import _build_recent_inputs_grouped


def _row(user_id, user_name, button, timestamp="2024-01-01T00:00:00"):
    return {"user_id": user_id, "user_name": user_name, "button": button, "timestamp": timestamp}


class TestBuildRecentInputsGrouped(unittest.TestCase):

    def test_empty_inputs_returns_empty(self):
        result = _build_recent_inputs_grouped([], [])
        self.assertEqual(result, [])

    def test_single_input_returns_one_group(self):
        pre = [_row(1, "alice", "A")]
        result = _build_recent_inputs_grouped(pre, [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["user_id"], 1)
        self.assertEqual(result[0]["buttons"], ["A"])

    def test_consecutive_same_user_collapses(self):
        pre = [_row(1, "alice", "A"), _row(1, "alice", "B")]
        result = _build_recent_inputs_grouped(pre, [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["buttons"], ["A", "B"])

    def test_different_users_separate_groups(self):
        pre = [_row(1, "alice", "A"), _row(2, "bob", "B")]
        result = _build_recent_inputs_grouped(pre, [])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["user_id"], 1)
        self.assertEqual(result[1]["user_id"], 2)

    def test_alternating_users_no_collapse(self):
        pre = [_row(1, "alice", "A"), _row(2, "bob", "B"), _row(1, "alice", "C")]
        result = _build_recent_inputs_grouped(pre, [])
        self.assertEqual(len(result), 3)

    def test_capped_at_group_limit(self):
        pre = [_row(i, f"user{i}", "A") for i in range(10)]
        result = _build_recent_inputs_grouped(pre, [], group_limit=3)
        self.assertEqual(len(result), 3)
        # Should be the last 3 users
        self.assertEqual(result[0]["user_id"], 7)
        self.assertEqual(result[1]["user_id"], 8)
        self.assertEqual(result[2]["user_id"], 9)

    def test_pre_existing_ordered_before_new(self):
        pre = [_row(1, "alice", "A")]
        new = [(_row(2, "bob", "B"), 0)]
        result = _build_recent_inputs_grouped(pre, new)
        self.assertEqual(result[0]["user_id"], 1)
        self.assertEqual(result[1]["user_id"], 2)

    def test_new_inputs_from_same_user_collapses_with_pre_existing(self):
        pre = [_row(1, "alice", "A")]
        new = [(_row(1, "alice", "B"), 0)]
        result = _build_recent_inputs_grouped(pre, new)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["buttons"], ["A", "B"])

    def test_row_without_button_produces_empty_buttons(self):
        pre = [{"user_id": 1, "user_name": "alice", "timestamp": "2024-01-01T00:00:00"}]
        result = _build_recent_inputs_grouped(pre, [])
        self.assertEqual(result[0]["buttons"], [])

    def test_fewer_groups_than_limit_returns_all(self):
        pre = [_row(1, "alice", "A"), _row(2, "bob", "B")]
        result = _build_recent_inputs_grouped(pre, [], group_limit=5)
        self.assertEqual(len(result), 2)

    def test_only_new_inputs(self):
        new = [(_row(1, "alice", "A"), 0), (_row(2, "bob", "B"), 5)]
        result = _build_recent_inputs_grouped([], new)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["user_id"], 1)


if __name__ == "__main__":
    unittest.main()
