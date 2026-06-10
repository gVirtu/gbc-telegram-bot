"""Tests for extended species ID reconstruction (Polished Crystal species > 255)."""

import os
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

import pytest
from unittest.mock import MagicMock

from src.game_utils.pkpcrystal.reader import (
    combine_species_id, MON_EXTSPECIES_F, EXTSPECIES_MASK,
    read_party_mon_species, parse_party_struct, read_box_mon_raw,
    PARTYMON_STRUCT_LENGTH, P_PERSONALITY,
    SAVEMON_STRUCT_LENGTH, S_SPECIES, S_PERSONALITY, S_ITEM, S_MOVES,
    S_LEVEL, S_NICKNAME, MONS_PER_BOX,
    NEWBOX_ENTRIES, NEWBOX_BANKS, NEWBOX_STRIDE, MONDB_ENTRIES_A,
)
from src.game_utils.pkpcrystal.charmap import REVERSE_CHARMAP


class TestCombineSpeciesId:
    def test_regular_species(self):
        assert combine_species_id(0x04, 0x00) == 0x04

    def test_extended_species_bit5_set(self):
        assert combine_species_id(0x04, 0x20) == 0x0104  # 256 + 4

    def test_max_species_255(self):
        assert combine_species_id(0xFF, 0x20) == 0x01FF  # 256 + 255 = 511

    def test_max_species_255_no_ext(self):
        assert combine_species_id(0xFF, 0x00) == 0xFF

    def test_ext_bit_with_form_bits(self):
        assert combine_species_id(0x01, 0x20 | 0x03) == 0x0101  # ext+form

    def test_form_bits_dont_affect_ext(self):
        assert combine_species_id(0x01, 0x1F) == 0x01

    def test_zero_species_with_ext(self):
        assert combine_species_id(0x00, 0x20) == 0x0100


class TestReadPartyMonSpecies:
    def test_regular_species(self):
        pyboy = MagicMock()
        pyboy.symbol_lookup.return_value = (0, 0)
        pyboy.memory.__getitem__.side_effect = lambda key: {
            (0, 0): 0x04,
            (0, 0): 0x00,
        }.get(key, 0)

        def mem_get(key):
            if key == (0, 0):
                return pyboy.memory._side_effect_calls and pyboy.memory._side_effect_lookup.get(key, 0) or 0

        # custom mock: symbol_lookup returns same addr for both symbols
        # we need different stored values
        store = {}
        pyboy.memory.__getitem__.side_effect = lambda key: store.get(key, 0)
        pyboy.symbol_lookup.side_effect = lambda sym: {
            "wPartyMon1Species": (0, 0x10),
            "wPartyMon1ExtSpecies": (0, 0x11),
        }.get(sym, (0, 0))

        store[(0, 0x10)] = 0x19  # species 25 (Pikachu)
        store[(0, 0x11)] = 0x00  # no ext

        assert read_party_mon_species(pyboy, 1) == 0x19

    def test_extended_species(self):
        pyboy = MagicMock()
        store = {}
        pyboy.memory.__getitem__.side_effect = lambda key: store.get(key, 0)
        pyboy.symbol_lookup.side_effect = lambda sym: {
            "wPartyMon1Species": (0, 0x10),
            "wPartyMon1ExtSpecies": (0, 0x11),
        }.get(sym, (0, 0))

        store[(0, 0x10)] = 0x1D  # species 29 (Nidoran F base)
        store[(0, 0x11)] = 0x20  # ExtSpecies bit set -> 256 + 29 = 285 (e.g., Ursaluna)

        assert read_party_mon_species(pyboy, 1) == 0x011D


class TestParsePartyStruct:
    def _make_data(self, species_lo, p2):
        data = bytearray(PARTYMON_STRUCT_LENGTH)
        data[0] = species_lo
        data[P_PERSONALITY + 1] = p2
        return bytes(data)

    def test_regular_species(self):
        data = self._make_data(0x19, 0x00)
        result = parse_party_struct(data)
        assert result["species_id"] == 0x19

    def test_extended_species(self):
        data = self._make_data(0x1D, 0x20)
        result = parse_party_struct(data)
        assert result["species_id"] == 0x011D

    def test_p2_preserves_form_data(self):
        data = self._make_data(0x01, 0x23)  # ExtSpecies=1, form=3
        result = parse_party_struct(data)
        assert result["species_id"] == 0x0101


class TestReadBoxMonRaw:
    def test_extended_species(self):
        pyboy = MagicMock()
        memory_store = {}

        def mem_get(key):
            if isinstance(key, tuple):
                return memory_store.get(key[1], 0)
            return memory_store.get(key, 0)

        def mem_set(key, value):
            if isinstance(key, tuple):
                memory_store[key[1]] = value
            else:
                memory_store[key] = value

        pyboy.memory.__getitem__.side_effect = mem_get
        pyboy.memory.__setitem__.side_effect = mem_set

        sram_bank = 2
        addr = 0xA000
        pyboy.symbol_lookup.side_effect = lambda sym: {
            "sNewBox1Entries": (1, 0xB0E4),
            "sNewBox1Banks": (1, 0xB0F8),
            "sBoxMons1A": (sram_bank, addr),
        }.get(sym, (0, 0))

        for slot in range(MONS_PER_BOX):
            memory_store[0xB0E4 + slot] = slot + 1
        memory_store[0xB0F8] = 0

        memory_store[addr + S_SPECIES] = 0x01
        memory_store[addr + S_ITEM] = 0
        memory_store[addr + S_PERSONALITY] = 0x00
        memory_store[addr + S_PERSONALITY + 1] = 0x20
        memory_store[addr + S_LEVEL] = 50
        memory_store[addr + S_NICKNAME] = 0x7B

        result = read_box_mon_raw(pyboy, 0, 0)
        assert result is not None
        assert result["species_id"] == 0x0101

    def test_regular_species_box(self):
        pyboy = MagicMock()
        memory_store = {}

        def mem_get(key):
            if isinstance(key, tuple):
                return memory_store.get(key[1], 0)
            return memory_store.get(key, 0)

        def mem_set(key, value):
            if isinstance(key, tuple):
                memory_store[key[1]] = value
            else:
                memory_store[key] = value

        pyboy.memory.__getitem__.side_effect = mem_get
        pyboy.memory.__setitem__.side_effect = mem_set

        sram_bank = 2
        addr = 0xA000
        pyboy.symbol_lookup.side_effect = lambda sym: {
            "sNewBox1Entries": (1, 0xB0E4),
            "sNewBox1Banks": (1, 0xB0F8),
            "sBoxMons1A": (sram_bank, addr),
        }.get(sym, (0, 0))

        for slot in range(MONS_PER_BOX):
            memory_store[0xB0E4 + slot] = slot + 1
        memory_store[0xB0F8] = 0

        memory_store[addr + S_SPECIES] = 0x19
        memory_store[addr + S_ITEM] = 0
        memory_store[addr + S_PERSONALITY] = 0xAA
        memory_store[addr + S_PERSONALITY + 1] = 0x80  # Female, no ext
        memory_store[addr + S_LEVEL] = 50
        memory_store[addr + S_NICKNAME] = 0x7B

        result = read_box_mon_raw(pyboy, 0, 0)
        assert result is not None
        assert result["species_id"] == 0x19
