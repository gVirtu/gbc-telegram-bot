# tests/test_pkpcrystal_box_inspect.py
import os
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.shop.flow.handlers import PurchaseComplete, SelectionStep, ShopPurchaseContext
from src.shop.flow.screens import SelectionOption
from src.shop.items import ShopItem
from src.game_utils.pkpcrystal.charmap import encode_name, CHARMAP, REVERSE_CHARMAP

from src.game_utils.pkpcrystal.reader import (
    SAVEMON_STRUCT_LENGTH, S_SPECIES, S_ITEM, S_MOVES, S_EVS,
    S_PERSONALITY, S_LEVEL, S_NICKNAME,
    NEWBOX_STRIDE, NEWBOX_ENTRIES, NEWBOX_BANKS, NEWBOX_NAME,
    MONS_PER_BOX, NUM_BOXES,
    read_box_count, read_box_name, read_box_mon_raw,
    MONDB_ENTRIES_A, MONDB_ENTRIES_B,
)


def _make_pyboy_with_box(box_index: int, mons: list[dict | None]):
    pyboy = MagicMock()
    memory_store = {}

    def mem_get(key):
        if isinstance(key, tuple):
            if isinstance(key[1], slice):
                start, stop = key[1].start, key[1].stop
                return [memory_store.get(i, 0) for i in range(start, stop)]
            return memory_store.get(key[1], 0)
        return memory_store.get(key, 0)

    def mem_set(key, value):
        if isinstance(key, tuple):
            memory_store[key[1]] = value
        else:
            memory_store[key] = value

    pyboy.memory.__getitem__.side_effect = mem_get
    pyboy.memory.__setitem__.side_effect = mem_set

    sram_bank = 1
    base_entries_addr = 0xB0E4  # sNewBox1Entries
    entries_addr = base_entries_addr + box_index * NEWBOX_STRIDE

    banks_addr = entries_addr + NEWBOX_BANKS
    name_addr = entries_addr + NEWBOX_NAME

    pyboy.symbol_lookup.side_effect = lambda sym: {
        f"sNewBox{box_index + 1}Entries": (sram_bank, entries_addr),
        f"sNewBox{box_index + 1}Banks": (sram_bank, banks_addr),
        f"sNewBox{box_index + 1}Name": (sram_bank, name_addr),
        "sBoxMons1A": (2, 0xA000),
    }.get(sym, (0, 0))

    for slot, mon in enumerate(mons):
        pokedb_index = slot + 1 if mon is not None else 0
        memory_store[entries_addr + slot] = pokedb_index
        memory_store[banks_addr + slot // 8] = 0  # bank group 1

    return pyboy, memory_store


def _make_pyboy_with_savemon(species_id=25, item_id=0, move_ids=(0,0,0,0),
                               p1=0, p2=0, level=50, evs=None, nickname=""):
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

    addr = 0xA000
    memory_store[addr + S_SPECIES] = species_id
    memory_store[addr + S_ITEM] = item_id
    for i, m in enumerate(move_ids):
        memory_store[addr + S_MOVES + i] = m
    memory_store[addr + S_PERSONALITY] = p1
    memory_store[addr + S_PERSONALITY + 1] = p2
    memory_store[addr + S_LEVEL] = level
    if evs:
        for i, e in enumerate(evs):
            memory_store[addr + S_EVS + i] = e
    std_bytes = [REVERSE_CHARMAP.get(ch, 0x00) for ch in nickname]
    for i, b in enumerate(std_bytes):
        encoded = 0x7A if b == 0x7F else 0x7B if b == 0x53 else 0x7C if b == 0x00 else b & 0x7F
        memory_store[addr + S_NICKNAME + i] = encoded
    memory_store[addr + S_NICKNAME + len(nickname)] = 0x7B

    pyboy.symbol_lookup.side_effect = lambda sym: {
        f"sNewBox1Entries": (1, 0xB0E4),
        f"sNewBox1Banks": (1, 0xB0F8),
        "sBoxMons1A": (2, addr),
    }.get(sym, (0, 0))

    for slot in range(MONS_PER_BOX):
        memory_store[0xB0E4 + slot] = slot + 1
    memory_store[0xB0F8] = 0

    return pyboy, memory_store


class TestReadBoxCount:
    def test_empty_box(self):
        pyboy, _ = _make_pyboy_with_box(0, [None] * MONS_PER_BOX)
        assert read_box_count(pyboy, 0) == 0

    def test_partial_box(self):
        mons = [{"species_id": 25}] * 3 + [None] * 17
        pyboy, _ = _make_pyboy_with_box(0, mons)
        assert read_box_count(pyboy, 0) == 3

    def test_full_box(self):
        mons = [{"species_id": 25}] * MONS_PER_BOX
        pyboy, _ = _make_pyboy_with_box(0, mons)
        assert read_box_count(pyboy, 0) == MONS_PER_BOX

    def test_second_box(self):
        mons = [{"species_id": 25}] * 5 + [None] * 15
        pyboy, _ = _make_pyboy_with_box(1, mons)
        assert read_box_count(pyboy, 1) == 5


class TestReadBoxMonRaw:
    def test_reads_species_and_level(self):
        pyboy, _ = _make_pyboy_with_savemon(species_id=25, level=50)
        result = read_box_mon_raw(pyboy, 0, 0)
        assert result["species_id"] == 25
        assert result["level"] == 50

    def test_empty_slot_returns_none(self):
        pyboy, mem = _make_pyboy_with_savemon()
        mem[0xB0E4] = 0
        result = read_box_mon_raw(pyboy, 0, 0)
        assert result is None

    def test_reads_moves_and_item(self):
        pyboy, _ = _make_pyboy_with_savemon(species_id=4, item_id=255,
                                              move_ids=(1, 2, 3, 4))
        result = read_box_mon_raw(pyboy, 0, 0)
        assert result["species_id"] == 4
        assert result["item_id"] == 255
        assert result["move_ids"] == [1, 2, 3, 4]

    def test_reads_personality_and_evs(self):
        evs = [10, 20, 30, 40, 50, 60]
        pyboy, _ = _make_pyboy_with_savemon(p1=0x80, p2=0x80, evs=evs)
        result = read_box_mon_raw(pyboy, 0, 0)
        assert result["p1"] == 0x80
        assert result["p2"] == 0x80
        assert result["evs_raw"] == evs

    def test_reads_nickname(self):
        pyboy, _ = _make_pyboy_with_savemon(nickname="PIKACHU")
        result = read_box_mon_raw(pyboy, 0, 0)
        assert result["nickname"] == "PIKACHU"

    def test_nickname_drowzee(self):
        pyboy, _ = _make_pyboy_with_savemon(nickname="Drowzee")
        result = read_box_mon_raw(pyboy, 0, 0)
        assert result["nickname"] == "Drowzee"

    def test_nickname_geodude(self):
        pyboy, _ = _make_pyboy_with_savemon(nickname="Geodude")
        result = read_box_mon_raw(pyboy, 0, 0)
        assert result["nickname"] == "Geodude"

    def test_nickname_with_apostrophe(self):
        pyboy, _ = _make_pyboy_with_savemon(nickname="Farfetch'd")
        result = read_box_mon_raw(pyboy, 0, 0)
        assert result["nickname"] == "Farfetch'd"

    def test_nickname_all_uppercase(self):
        pyboy, _ = _make_pyboy_with_savemon(nickname="CHARIZARD")
        result = read_box_mon_raw(pyboy, 0, 0)
        assert result["nickname"] == "CHARIZARD"

    def test_nickname_empty_returns_empty_string(self):
        pyboy, _ = _make_pyboy_with_savemon(nickname="")
        result = read_box_mon_raw(pyboy, 0, 0)
        assert result["nickname"] == ""


def _make_resolved_mon(override=None):
    mon = {
        "is_egg": False, "species_name": "PIKACHU", "nickname": None,
        "gender": "M", "item_name": None, "ability_name": "Static",
        "level": 50, "is_shiny": False, "nature_name": "Hardy",
        "evs": [(85, "HP")], "move_names": ["Tackle"],
    }
    if override:
        mon.update(override)
    return mon


class TestInspectBoxHandler:
    @pytest.mark.asyncio
    async def test_returns_selection_step(self):
        pyboy, _ = _make_pyboy_with_box(0, [None] * MONS_PER_BOX)
        controller = MagicMock()
        controller.pyboy = pyboy

        item = ShopItem(id="inspect_box", name_i18n_key="k", cost=50, effect={})
        ctx = ShopPurchaseContext(
            platform="telegram", user_id=1, user_name="Ash",
            chat_id=100, item=item, game_controller=controller,
            session=MagicMock(),
        )

        from src.game_shops.pkpcrystal import inspect_box_handler
        outcome = await inspect_box_handler(ctx)

        assert isinstance(outcome, SelectionStep)
        assert len(outcome.options) == NUM_BOXES

    @pytest.mark.asyncio
    async def test_selection_step_shows_counts(self):
        mons = [{"species_id": 25}] * 5 + [None] * 15
        pyboy, _ = _make_pyboy_with_box(0, mons)
        controller = MagicMock()
        controller.pyboy = pyboy

        item = ShopItem(id="inspect_box", name_i18n_key="k", cost=50, effect={})
        ctx = ShopPurchaseContext(
            platform="telegram", user_id=1, user_name="Ash",
            chat_id=100, item=item, game_controller=controller,
            session=MagicMock(),
        )

        with patch("src.game_shops.pkpcrystal.shop_manager") as mock_sm, \
             patch("src.game_shops.pkpcrystal._resolve_mon_data", return_value=_make_resolved_mon()):
            mock_sm.purchase.return_value = MagicMock(success=True)

            from src.game_shops.pkpcrystal import _on_select_box
            outcome = await _on_select_box("0", ctx)

        assert isinstance(outcome, PurchaseComplete)
        assert outcome.success is True

    @pytest.mark.asyncio
    async def test_extra_messages_chunked_by_size(self):
        pyboy, _ = _make_pyboy_with_savemon(
            species_id=25, level=50, p1=0, p2=0,
            move_ids=(1, 2, 3, 4), nickname="PIKACHU",
        )

        controller = MagicMock()
        controller.pyboy = pyboy
        item = ShopItem(id="inspect_box", name_i18n_key="k", cost=50, effect={})
        ctx = ShopPurchaseContext(
            platform="telegram", user_id=1, user_name="Ash",
            chat_id=100, item=item, game_controller=controller,
            session=MagicMock(),
        )

        with patch("src.game_shops.pkpcrystal.shop_manager") as mock_sm, \
             patch("src.game_shops.pkpcrystal._resolve_mon_data", return_value=_make_resolved_mon()), \
             patch("src.game_shops.pkpcrystal._format_mon_report", return_value="X" * 500):
            mock_sm.purchase.return_value = MagicMock(success=True)

            from src.game_shops.pkpcrystal import _on_select_box
            outcome = await _on_select_box("0", ctx)

        assert isinstance(outcome, PurchaseComplete)
        assert outcome.success is True
        # 20 mons * 500 chars = 10000 chars -> chunked at 1600
        # Each chunk holds floor(1600 / 502) = 3 mons (500 + 2 for \n\n)
        # 20 / 3 = 7 chunks (last one has 2 mons)
        assert len(outcome.extra_messages) == 7
        assert outcome.extra_messages[0].startswith("```\n")
        assert outcome.extra_messages[0].endswith("\n```")

    @pytest.mark.asyncio
    async def test_no_game_controller_error(self):
        item = ShopItem(id="inspect_box", name_i18n_key="k", cost=50, effect={})
        ctx = ShopPurchaseContext(
            platform="telegram", user_id=1, user_name="Ash",
            chat_id=100, item=item, game_controller=None,
            session=MagicMock(),
        )

        from src.game_shops.pkpcrystal import inspect_box_handler
        outcome = await inspect_box_handler(ctx)

        assert isinstance(outcome, PurchaseComplete)
        assert outcome.success is False

    @pytest.mark.asyncio
    async def test_purchase_failure_in_on_select(self):
        pyboy, _ = _make_pyboy_with_box(0, [None] * MONS_PER_BOX)
        controller = MagicMock()
        controller.pyboy = pyboy

        item = ShopItem(id="inspect_box", name_i18n_key="k", cost=50, effect={})
        ctx = ShopPurchaseContext(
            platform="telegram", user_id=1, user_name="Ash",
            chat_id=100, item=item, game_controller=controller,
            session=MagicMock(),
        )

        with patch("src.game_shops.pkpcrystal.shop_manager") as mock_sm:
            mock_sm.purchase.return_value = MagicMock(success=False, error_i18n_key="shop.insufficient_funds")

            from src.game_shops.pkpcrystal import _on_select_box
            outcome = await _on_select_box("0", ctx)

        assert isinstance(outcome, PurchaseComplete)
        assert outcome.success is False
