import unittest
from unittest.mock import MagicMock

from src.game_utils.pkpcrystal.stat_recalc import recalc_pkmn_stats, compute_target_levels
from src.game_utils.pkpcrystal.party_builder import (
    P_SPECIES, P_DVS, P_DVS_LEN, P_NATURE, P_LEVEL, P_STATUS,
    P_HP, P_MAXHP, P_ATTACK, P_DEFENSE, P_SPEED, P_SPATK, P_SPDEF,
    PARTY_STRUCT_SIZE,
)


def _make_mock_pyboy(base_stats):
    mock = MagicMock()
    bank = 0x1C
    addr = 0xA000
    mock.symbol_lookup.return_value = (bank, addr)
    entry = bytes(base_stats) + bytes([0] * (34 - 6))

    def side_effect(key):
        if isinstance(key, tuple) and len(key) == 2:
            b, a = key
            if isinstance(a, slice):
                return [entry[i - addr] for i in range(a.start, a.stop)]
            return entry[a - addr]
        return 0

    mock.memory.__getitem__.side_effect = side_effect
    return mock


def _make_party(species, dvs, nature, level, evs=None):
    buf = bytearray(PARTY_STRUCT_SIZE)
    buf[P_SPECIES] = species
    buf[P_DVS:P_DVS + P_DVS_LEN] = dvs
    buf[P_NATURE] = nature
    buf[P_LEVEL] = level
    if evs:
        from src.game_utils.pkpcrystal.party_builder import P_EVS, P_EVS_LEN
        buf[P_EVS:P_EVS + P_EVS_LEN] = evs
    return bytes(buf)


BULBASAUR_BASE = [45, 49, 49, 45, 65, 65]


class TestRecalcPkmnStats(unittest.TestCase):

    def test_bulbasaur_50_dv0_ev252_nature0(self):
        mon = _make_party(1, bytes([0, 0, 0]), 0, 50)
        pyboy = _make_mock_pyboy(BULBASAUR_BASE)
        result = recalc_pkmn_stats(pyboy, mon, 50)

        self.assertEqual(result[P_LEVEL], 50)
        self.assertEqual(result[P_STATUS], 0)

        maxhp = (result[P_HP] << 8) | result[P_HP + 1]
        self.assertEqual(maxhp, 137)
        maxhp2 = (result[P_MAXHP] << 8) | result[P_MAXHP + 1]
        self.assertEqual(maxhp2, maxhp)

        atk = (result[P_ATTACK] << 8) | result[P_ATTACK + 1]
        self.assertEqual(atk, 86)
        defense = (result[P_DEFENSE] << 8) | result[P_DEFENSE + 1]
        self.assertEqual(defense, 86)
        spe = (result[P_SPEED] << 8) | result[P_SPEED + 1]
        self.assertEqual(spe, 82)
        satk = (result[P_SPATK] << 8) | result[P_SPATK + 1]
        self.assertEqual(satk, 102)
        sdef = (result[P_SPDEF] << 8) | result[P_SPDEF + 1]
        self.assertEqual(sdef, 102)

    def test_bulbasaur_50_dv15_ev252_nature0(self):
        mon = _make_party(1, bytes([0xFF, 0xFF, 0xFF]), 0, 50)
        pyboy = _make_mock_pyboy(BULBASAUR_BASE)
        result = recalc_pkmn_stats(pyboy, mon, 50)

        maxhp = (result[P_HP] << 8) | result[P_HP + 1]
        self.assertEqual(maxhp, 152)
        atk = (result[P_ATTACK] << 8) | result[P_ATTACK + 1]
        self.assertEqual(atk, 101)
        defense = (result[P_DEFENSE] << 8) | result[P_DEFENSE + 1]
        self.assertEqual(defense, 101)
        spe = (result[P_SPEED] << 8) | result[P_SPEED + 1]
        self.assertEqual(spe, 97)
        satk = (result[P_SPATK] << 8) | result[P_SPATK + 1]
        self.assertEqual(satk, 117)
        sdef = (result[P_SPDEF] << 8) | result[P_SPDEF + 1]
        self.assertEqual(sdef, 117)

    def test_bulbasaur_50_dv0_ev252_nature1_lonely(self):
        mon = _make_party(1, bytes([0, 0, 0]), 1, 50)
        pyboy = _make_mock_pyboy(BULBASAUR_BASE)
        result = recalc_pkmn_stats(pyboy, mon, 50)

        atk = (result[P_ATTACK] << 8) | result[P_ATTACK + 1]
        self.assertEqual(atk, 94)
        defense = (result[P_DEFENSE] << 8) | result[P_DEFENSE + 1]
        self.assertEqual(defense, 77)

    def test_perfect_dvs_give_different_stats_from_zero_dvs(self):
        mon_zero = _make_party(1, bytes([0, 0, 0]), 0, 50)
        mon_perfect = _make_party(1, bytes([0xFF, 0xFF, 0xFF]), 0, 50)
        pyboy = _make_mock_pyboy(BULBASAUR_BASE)
        result_zero = recalc_pkmn_stats(pyboy, mon_zero, 50)
        result_perfect = recalc_pkmn_stats(pyboy, mon_perfect, 50)

        for offset in [P_HP, P_ATTACK, P_DEFENSE, P_SPEED, P_SPATK, P_SPDEF]:
            val_zero = (result_zero[offset] << 8) | result_zero[offset + 1]
            val_perfect = (result_perfect[offset] << 8) | result_perfect[offset + 1]
            self.assertGreater(val_perfect, val_zero,
                               f"Stat at offset {offset} should be higher with perfect DVs")

    def test_compute_target_levels_player_larger(self):
        result = compute_target_levels([5, 10, 15, 20], 2)
        self.assertEqual(result, [15, 20])

    def test_compute_target_levels_player_smaller(self):
        result = compute_target_levels([10, 20], 4)
        self.assertEqual(result, [20, 20, 20, 20])

    def test_compute_target_levels_equal(self):
        result = compute_target_levels([5, 10], 2)
        self.assertEqual(result, [5, 10])

    def test_compute_target_levels_clamp_low(self):
        result = compute_target_levels([1, 0, -5], 3)
        self.assertEqual(result, [2, 2, 2])

    def test_compute_target_levels_clamp_high(self):
        result = compute_target_levels([101, 200, 150], 3)
        self.assertEqual(result, [100, 100, 100])
