"""Unit tests for the pkpcrystal status bar module."""

import pytest
from unittest.mock import MagicMock


class TestPkpcrystalGetStatusBarData:
    """Test get_status_bar_data for pkpcrystal."""

    def _make_pyboy(self, memory: dict):
        """Create a mock pyboy with the given memory dict."""
        mock = MagicMock()
        mock.memory.__getitem__.side_effect = memory.__getitem__
        return mock

    def test_returns_map_group_and_number(self):
        """Test that map group and number are read from memory."""
        from src.game_status_bars.pkpcrystal import get_status_bar_data

        memory = {
            "wMapGroup": 3,
            "wMapNumber": 7,
            "wPartyMon1Species": 155,
            "wPartyMon2Species": 0,
            "wPartyMon3Species": 0,
            "wPartyMon4Species": 0,
            "wPartyMon5Species": 0,
            "wPartyMon6Species": 0,
        }
        pyboy = self._make_pyboy(memory)

        result = get_status_bar_data(pyboy)

        assert result["map_group"] == 3
        assert result["map_number"] == 7

    def test_returns_party_species(self):
        """Test that all 6 party species are returned."""
        from src.game_status_bars.pkpcrystal import get_status_bar_data

        memory = {
            "wMapGroup": 1,
            "wMapNumber": 1,
            "wPartyMon1Species": 155,
            "wPartyMon2Species": 158,
            "wPartyMon3Species": 152,
            "wPartyMon4Species": 0,
            "wPartyMon5Species": 0,
            "wPartyMon6Species": 0,
        }
        pyboy = self._make_pyboy(memory)

        result = get_status_bar_data(pyboy)

        assert result["party"] == [155, 158, 152, 0, 0, 0]

    def test_returns_all_expected_keys(self):
        """Test that result contains all required keys."""
        from src.game_status_bars.pkpcrystal import get_status_bar_data

        memory = {
            "wMapGroup": 0,
            "wMapNumber": 0,
            "wPartyMon1Species": 0,
            "wPartyMon2Species": 0,
            "wPartyMon3Species": 0,
            "wPartyMon4Species": 0,
            "wPartyMon5Species": 0,
            "wPartyMon6Species": 0,
        }
        pyboy = self._make_pyboy(memory)

        result = get_status_bar_data(pyboy)

        assert "map_group" in result
        assert "map_number" in result
        assert "party" in result
        assert len(result["party"]) == 6
