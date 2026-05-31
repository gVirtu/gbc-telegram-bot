"""Tests for the move tutor (teach_level_move) shop handler and learnset reader."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from src.game_utils.pkpcrystal.party_builder import BATTLE_STRUCT_SIZE
from src.shop.flow.handlers import PurchaseComplete, SelectionStep, FlowSession


def _make_mock_battle_struct(species: int = 0x84, level: int = 5, moves: list[int] | None = None) -> bytes:
    buf = bytearray(35)
    buf[0] = species
    buf[1] = 0x00
    if moves:
        for i in range(min(4, len(moves))):
            buf[2 + i] = moves[i]
    else:
        buf[2] = 0x90
        buf[3] = 0x00
        buf[4] = 0x00
        buf[5] = 0x00
    buf[6] = 0xFF
    buf[7] = 0xFE
    buf[8] = 0xFD
    buf[9] = 0x00
    buf[10] = 0x00
    buf[11] = 0x14
    buf[12] = 0x0F
    buf[13] = 0x0A
    buf[14] = 0x05
    buf[15] = 0x80
    buf[16] = level
    buf[17] = 0x00
    buf[18] = 0x00
    buf[19] = 0x90
    buf[20] = 0x01
    buf[21] = 0x90
    buf[22] = 0x01
    buf[23] = 0x50
    buf[24] = 0x00
    buf[25] = 0x4F
    buf[26] = 0x00
    buf[27] = 0x48
    buf[28] = 0x00
    buf[29] = 0x47
    buf[30] = 0x00
    buf[31] = 0x46
    buf[32] = 0x00
    buf[33] = 0x0F
    buf[34] = 0x0F
    return bytes(buf) + bytes(7)


def _mock_memory_getitem(memory_store: dict[int, int]):
    """Returns a __getitem__ side_effect that reads from a dict, with slice support."""
    def memory_getitem(key):
        if isinstance(key, tuple):
            if isinstance(key[1], slice):
                start = key[1].start
                stop = key[1].stop
                return [memory_store.get(i, 0) for i in range(start, stop)]
            return memory_store.get(key[1], 0)
        return memory_store.get(key, 0)
    return memory_getitem


def _make_learnset_memory():
    store = {}

    EVOS_ATTACKS_PTRS = 0x46D1
    EVOS_ATTACKS = 0x4973

    species1_data = [
        0x01, 0x10, 0x02,
        0xFF,
        1, 0x21,
        2, 0x2D,
        7, 0x4A,
        10, 0x45,
        13, 0x2B,
        0xFF,
    ]
    for i, b in enumerate(species1_data):
        store[EVOS_ATTACKS + i] = b
    s1_end = EVOS_ATTACKS + len(species1_data)

    species2_data = [
        0xFF,
        1, 0x01,
        4, 0x2D,
        8, 0x52,
        0xFF,
    ]
    for i, b in enumerate(species2_data):
        store[s1_end + i] = b
    s2_end = s1_end + len(species2_data)

    species3_data = [
        0x03,
        0xFF,
        1, 0x01,
        99, 0xFF,
        0xFF,
    ]
    for i, b in enumerate(species3_data):
        store[s2_end + i] = b

    s1_ptr = EVOS_ATTACKS
    s2_ptr = s1_end
    s3_ptr = s2_end

    store[EVOS_ATTACKS_PTRS] = s1_ptr & 0xFF
    store[EVOS_ATTACKS_PTRS + 1] = (s1_ptr >> 8) & 0xFF
    store[EVOS_ATTACKS_PTRS + 2] = s2_ptr & 0xFF
    store[EVOS_ATTACKS_PTRS + 3] = (s2_ptr >> 8) & 0xFF
    store[EVOS_ATTACKS_PTRS + 4] = s3_ptr & 0xFF
    store[EVOS_ATTACKS_PTRS + 5] = (s3_ptr >> 8) & 0xFF

    expected_species1 = [(1, 0x21), (2, 0x2D), (7, 0x4A), (10, 0x45), (13, 0x2B)]
    expected_species2 = [(1, 0x01), (4, 0x2D), (8, 0x52)]
    expected_species3 = [(1, 0x01), (99, 0xFF)]

    return store, expected_species1, expected_species2, expected_species3


# ─── get_species_learnset ────────────────────────────────────────────

class TestGetSpeciesLearnset:
    def test_reads_learnset_for_species1(self):
        from src.game_utils.pkpcrystal.reader import get_species_learnset
        pyboy = MagicMock()
        sym_addrs = {"EvosAttacksPointers": (6, 0x46D1)}
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store, expected, _, _ = _make_learnset_memory()
        pyboy.memory.__getitem__.side_effect = _mock_memory_getitem(memory_store)

        result = get_species_learnset(pyboy, 1)
        assert result == expected

    def test_reads_learnset_for_species2_no_evo(self):
        from src.game_utils.pkpcrystal.reader import get_species_learnset
        pyboy = MagicMock()
        sym_addrs = {"EvosAttacksPointers": (6, 0x46D1)}
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store, _, expected, _ = _make_learnset_memory()
        pyboy.memory.__getitem__.side_effect = _mock_memory_getitem(memory_store)

        result = get_species_learnset(pyboy, 2)
        assert result == expected

    def test_reads_learnset_for_species3(self):
        from src.game_utils.pkpcrystal.reader import get_species_learnset
        pyboy = MagicMock()
        sym_addrs = {"EvosAttacksPointers": (6, 0x46D1)}
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store, _, _, expected = _make_learnset_memory()
        pyboy.memory.__getitem__.side_effect = _mock_memory_getitem(memory_store)

        result = get_species_learnset(pyboy, 3)
        assert result == expected


# ─── teach_level_move handler ────────────────────────────────────────

class TestTeachLevelMoveHandler:
    @pytest.mark.asyncio
    async def test_no_controller(self):
        from src.game_shops.pkpcrystal import teach_level_move_handler
        ctx = MagicMock()
        ctx.game_controller = None
        result = await teach_level_move_handler(ctx)
        assert result.success is False
        assert "no_game_controller" in result.error_message

    @pytest.mark.asyncio
    async def test_insufficient_balance(self):
        from src.game_shops.pkpcrystal import teach_level_move_handler
        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.check_balance = AsyncMock(return_value=False)
        result = await teach_level_move_handler(ctx)
        assert result.success is False
        assert "insufficient_funds" in result.error_message

    @pytest.mark.asyncio
    async def test_no_party_mons(self):
        from src.game_shops.pkpcrystal import teach_level_move_handler
        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.check_balance = AsyncMock(return_value=True)
        ctx.platform = "test"
        ctx.user_id = 1
        with patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", return_value=None):
            result = await teach_level_move_handler(ctx)
        assert result.success is False
        assert "no_party_mons" in result.error_message

    @pytest.mark.asyncio
    async def test_returns_mon_selection(self):
        from src.game_shops.pkpcrystal import teach_level_move_handler
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0, 0])

        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.check_balance = AsyncMock(return_value=True)
        ctx.platform = "test"
        ctx.user_id = 1

        def mock_pref(platform, uid, key):
            if key == "pkpcrystal_trainer_card_mon_0":
                return raw.hex()
            return None

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=mock_pref),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
        ):
            result = await teach_level_move_handler(ctx)

        assert isinstance(result, SelectionStep)
        assert len(result.options) == 1
        assert result.options[0].label == "Bulbasaur Lv.10"
        assert result.options[0].value == "0"

    @pytest.mark.asyncio
    async def test_skips_invalid_mon_slots(self):
        from src.game_shops.pkpcrystal import teach_level_move_handler
        raw = _make_mock_battle_struct(species=0x01, level=10)
        raw_zero = bytes(BATTLE_STRUCT_SIZE)

        def mock_pref(platform, uid, key):
            prefs = {
                "pkpcrystal_trainer_card_mon_0": "nothex",
                "pkpcrystal_trainer_card_mon_1": raw.hex(),
                "pkpcrystal_trainer_card_mon_2": raw_zero.hex(),
                "pkpcrystal_trainer_card_mon_3": "00" * BATTLE_STRUCT_SIZE,
            }
            return prefs.get(key)

        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.check_balance = AsyncMock(return_value=True)
        ctx.platform = "test"
        ctx.user_id = 1

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=mock_pref),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
        ):
            result = await teach_level_move_handler(ctx)

        assert isinstance(result, SelectionStep)
        assert len(result.options) == 1


class TestOnSelectTeachMon:
    @pytest.mark.asyncio
    async def test_no_valid_moves(self):
        from src.game_shops.pkpcrystal import _on_select_teach_mon
        # All learnset moves are already known by the mon
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0x4A, 0x45])
        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.user_name = "TestUser"
        ctx.item = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=lambda p, u, k: prefs.get(k)),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
            patch("src.game_shops.pkpcrystal.get_species_learnset", return_value=[(1, 0x21), (2, 0x2D), (7, 0x4A), (10, 0x45)]),
            patch("src.game_shops.pkpcrystal.get_move_name", return_value="Tackle"),
            patch("src.game_shops.pkpcrystal.shop_manager.purchase") as mock_purchase,
        ):
            result = await _on_select_teach_mon("0", ctx)

        # Should return error since all learnset moves are already known
        assert isinstance(result, PurchaseComplete), f"Expected PurchaseComplete, got {type(result).__name__}"
        assert result.success is False
        assert "no_moves" in result.error_message
        mock_purchase.assert_not_called()

    @pytest.mark.asyncio
    async def test_deducts_points_and_returns_move_selection(self):
        from src.game_shops.pkpcrystal import _on_select_teach_mon
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0, 0])
        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.user_name = "TestUser"
        ctx.item = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=lambda p, u, k: prefs.get(k)),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
            patch("src.game_shops.pkpcrystal.get_species_learnset",
                  return_value=[(1, 0x21), (2, 0x2D), (7, 0x4A), (10, 0x45), (13, 0x2B)]),
            patch("src.game_shops.pkpcrystal.get_move_name", return_value="Tackle"),
            patch("src.game_shops.pkpcrystal.shop_manager.purchase", return_value=MagicMock(success=True)),
            patch("src.game_shops.pkpcrystal.random.sample", return_value=[(0x4A, "Vine Whip"), (0x45, "Leech Seed"), (0x2B, "Razor Leaf")]),
        ):
            result = await _on_select_teach_mon("0", ctx)

        assert isinstance(result, SelectionStep)
        assert len(result.options) == 3

    @pytest.mark.asyncio
    async def test_purchase_fails_insufficient_funds(self):
        from src.game_shops.pkpcrystal import _on_select_teach_mon
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0, 0])
        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.user_name = "TestUser"
        ctx.item = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        class FailResult:
            success = False
            error_i18n_key = "shop.insufficient_funds"

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=lambda p, u, k: prefs.get(k)),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
            patch("src.game_shops.pkpcrystal.get_species_learnset",
                  return_value=[(1, 0x21), (7, 0x4A), (13, 0x2B)]),
            patch("src.game_shops.pkpcrystal.get_move_name", return_value="Tackle"),
            patch("src.game_shops.pkpcrystal.shop_manager.purchase", return_value=FailResult()),
            patch("src.game_shops.pkpcrystal.random.sample", return_value=[(0x4A, "Vine Whip")]),
        ):
            result = await _on_select_teach_mon("0", ctx)

        assert result.success is False
        assert "insufficient_funds" in result.error_message

    @pytest.mark.asyncio
    async def test_filters_moves_above_level(self):
        from src.game_shops.pkpcrystal import _on_select_teach_mon
        raw = _make_mock_battle_struct(species=0x01, level=5, moves=[0x21, 0, 0, 0])
        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.user_name = "TestUser"
        ctx.item = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=lambda p, u, k: prefs.get(k)),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
            patch("src.game_shops.pkpcrystal.get_species_learnset",
                  return_value=[(1, 0x21), (2, 0x2D), (7, 0x4A), (10, 0x45), (13, 0x2B)]),
            patch("src.game_shops.pkpcrystal.get_move_name", return_value="Tackle"),
            patch("src.game_shops.pkpcrystal.shop_manager.purchase", return_value=MagicMock(success=True)),
            patch("src.game_shops.pkpcrystal.random.sample", return_value=[(0x2D, "Growl")]),
        ):
            result = await _on_select_teach_mon("0", ctx)

        assert isinstance(result, SelectionStep)
        assert len(result.options) == 1


class TestOnSelectTeachMove:
    @pytest.mark.asyncio
    async def test_all_slots_filled_shows_replace_step(self):
        from src.game_shops.pkpcrystal import _on_select_teach_move
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0x4A, 0x45])

        candidates = [(0x2B, "Razor Leaf")]
        current_moves = [(0x21, "Scratch"), (0x2D, "Growl"), (0x4A, "Vine Whip"), (0x45, "Leech Seed")]

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)
        session.state["teach_mon_slot"] = 0
        session.state["teach_mon_hex"] = raw.hex()
        session.state["teach_species_name"] = "Bulbasaur"
        session.state["teach_candidates"] = candidates
        session.state["teach_current_moves"] = current_moves
        session.state["teach_message_prefix"] = "teach_level_move"

        ctx = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        result = await _on_select_teach_move("0", ctx)
        assert isinstance(result, SelectionStep)
        assert len(result.options) == 4
        assert result.options[0].label == "Scratch"

    @pytest.mark.asyncio
    async def test_empty_slot_skips_replace_writes_directly(self):
        from src.game_shops.pkpcrystal import _on_select_teach_move
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0, 0])

        candidates = [(0x4A, "Vine Whip")]
        current_moves = [(0x21, "Scratch"), (0x2D, "Growl"), (0, None), (0, None)]

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)
        session.state["teach_mon_slot"] = 0
        session.state["teach_mon_hex"] = raw.hex()
        session.state["teach_species_name"] = "Bulbasaur"
        session.state["teach_candidates"] = candidates
        session.state["teach_current_moves"] = current_moves
        session.state["teach_message_prefix"] = "teach_level_move"

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.set_user_preference") as mock_set,
            patch("src.game_shops.pkpcrystal.get_move_name", return_value="Scratch"),
        ):
            result = await _on_select_teach_move("0", ctx)

        assert result.success is True
        assert "learned" in result.success_message
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[2] == "pkpcrystal_trainer_card_mon_0"
        updated_raw = bytes.fromhex(args[3])
        # Empty slot at index 2 → raw[2 + 2] = raw[4] should be the new move
        assert updated_raw[2] == 0x21  # unchanged
        assert updated_raw[4] == 0x4A  # new move at empty slot


class TestOnSelectTeachReplace:
    @pytest.mark.asyncio
    async def test_overwrites_move_and_returns_success(self):
        from src.game_shops.pkpcrystal import _on_select_teach_replace
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0x4A, 0x45])

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)
        session.state["teach_mon_slot"] = 0
        session.state["teach_mon_hex"] = raw.hex()
        session.state["teach_species_name"] = "Bulbasaur"
        session.state["teach_move_to_learn"] = 0x2B
        session.state["teach_move_to_learn_name"] = "Razor Leaf"
        session.state["teach_message_prefix"] = "teach_level_move"

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.set_user_preference") as mock_set,
            patch("src.game_shops.pkpcrystal.get_move_name", return_value="Scratch"),
        ):
            result = await _on_select_teach_replace("0", ctx)

        assert result.success is True
        assert "replaced" in result.success_message
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[2] == "pkpcrystal_trainer_card_mon_0"
        updated_raw = bytes.fromhex(args[3])
        assert updated_raw[2] == 0x2B  # slot 0 overwritten
        assert updated_raw[3] == 0x2D  # unchanged

    @pytest.mark.asyncio
    async def test_overwrites_at_slot_3(self):
        from src.game_shops.pkpcrystal import _on_select_teach_replace
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0x4A, 0x45])

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)
        session.state["teach_mon_slot"] = 0
        session.state["teach_mon_hex"] = raw.hex()
        session.state["teach_species_name"] = "Bulbasaur"
        session.state["teach_move_to_learn"] = 0x2B
        session.state["teach_move_to_learn_name"] = "Razor Leaf"
        session.state["teach_message_prefix"] = "teach_level_move"

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.set_user_preference") as mock_set,
            patch("src.game_shops.pkpcrystal.get_move_name", return_value="Leech Seed"),
        ):
            result = await _on_select_teach_replace("3", ctx)

        assert result.success is True
        args = mock_set.call_args[0]
        updated_raw = bytes.fromhex(args[3])
        assert updated_raw[2] == 0x21  # unchanged
        assert updated_raw[5] == 0x2B  # slot 3 overwritten


class TestFullFlow:
    @pytest.mark.asyncio
    async def test_full_flow_all_slots_filled(self):
        from src.game_shops.pkpcrystal import (
            _on_select_teach_mon, _on_select_teach_move, _on_select_teach_replace,
        )
        raw = _make_mock_battle_struct(species=0x01, level=13, moves=[0x21, 0x2D, 0x4A, 0x45])

        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.user_name = "TestUser"
        ctx.item = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=lambda p, u, k: prefs.get(k)),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
            patch("src.game_shops.pkpcrystal.get_move_name", side_effect=lambda pyboy, mid: {
                0x21: "Scratch", 0x2D: "Growl", 0x4A: "Vine Whip",
                0x45: "Leech Seed", 0x2B: "Razor Leaf",
            }.get(mid, f"Move_{mid:02X}")),
            patch("src.game_shops.pkpcrystal.get_species_learnset",
                  return_value=[(1, 0x21), (2, 0x2D), (7, 0x4A), (10, 0x45), (13, 0x2B)]),
            patch("src.game_shops.pkpcrystal.shop_manager.purchase", return_value=MagicMock(success=True)),
            patch("src.game_shops.pkpcrystal.random.sample", return_value=[(0x2B, "Razor Leaf")]),
            patch("src.game_shops.pkpcrystal.state_manager.set_user_preference") as mock_set,
        ):
            # Step 1 (mon select) -> shows move candidates
            step1 = await _on_select_teach_mon("0", ctx)
            assert isinstance(step1, SelectionStep), f"Expected SelectionStep, got {step1}"
            assert step1.on_select == _on_select_teach_move
            assert len(step1.options) == 1  # only Razor Leaf candidate

            # Step 2 (move select) -> all slots filled, shows replace step
            step2 = await _on_select_teach_move("0", ctx)
            assert isinstance(step2, SelectionStep), f"Expected SelectionStep, got {step2}"
            assert step2.on_select == _on_select_teach_replace
            assert len(step2.options) == 4

            # Step 3 (replace) -> success
            final = await _on_select_teach_replace("0", ctx)

            assert final.success is True
            assert "replaced" in final.success_message
            mock_set.assert_called_once()
            updated_raw = bytes.fromhex(mock_set.call_args[0][3])
            assert updated_raw[2] == 0x2B  # slot 0 overwritten with Razor Leaf


# ─── teach_tmhm_move tests ──────────────────────────────────────────

class TestTeachTmhmMoveHandler:
    @pytest.mark.asyncio
    async def test_no_controller(self):
        from src.game_shops.pkpcrystal import teach_tmhm_move_handler
        ctx = MagicMock()
        ctx.game_controller = None
        result = await teach_tmhm_move_handler(ctx)
        assert result.success is False
        assert "no_game_controller" in result.error_message

    @pytest.mark.asyncio
    async def test_insufficient_balance(self):
        from src.game_shops.pkpcrystal import teach_tmhm_move_handler
        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.check_balance = AsyncMock(return_value=False)
        result = await teach_tmhm_move_handler(ctx)
        assert result.success is False
        assert "insufficient_funds" in result.error_message

    @pytest.mark.asyncio
    async def test_no_party_mons(self):
        from src.game_shops.pkpcrystal import teach_tmhm_move_handler
        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.check_balance = AsyncMock(return_value=True)
        ctx.platform = "test"
        ctx.user_id = 1
        with patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", return_value=None):
            result = await teach_tmhm_move_handler(ctx)
        assert result.success is False
        assert "no_party_mons" in result.error_message

    @pytest.mark.asyncio
    async def test_returns_mon_selection(self):
        from src.game_shops.pkpcrystal import teach_tmhm_move_handler
        raw = _make_mock_battle_struct(species=0x01, level=10)

        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.check_balance = AsyncMock(return_value=True)
        ctx.platform = "test"
        ctx.user_id = 1

        def mock_pref(platform, uid, key):
            if key == "pkpcrystal_trainer_card_mon_0":
                return raw.hex()
            return None

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=mock_pref),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
        ):
            result = await teach_tmhm_move_handler(ctx)

        assert isinstance(result, SelectionStep)
        assert result.on_select is not None


class TestOnSelectTmhmMon:
    @pytest.mark.asyncio
    async def test_no_compatible_tmhm_moves(self):
        from src.game_shops.pkpcrystal import _on_select_tmhm_mon
        raw = _make_mock_battle_struct(species=0x01, level=10)
        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.user_name = "TestUser"
        ctx.item = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=lambda p, u, k: prefs.get(k)),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
            patch("src.game_shops.pkpcrystal.get_species_tmhm_moves", return_value=[]),
            patch("src.game_shops.pkpcrystal.shop_manager.purchase") as mock_purchase,
        ):
            result = await _on_select_tmhm_mon("0", ctx)

        assert isinstance(result, PurchaseComplete), f"Expected PurchaseComplete, got {type(result).__name__}"
        assert result.success is False
        assert "no_moves" in result.error_message
        mock_purchase.assert_not_called()

    @pytest.mark.asyncio
    async def test_deducts_points_and_returns_move_selection(self):
        from src.game_shops.pkpcrystal import _on_select_tmhm_mon
        raw = _make_mock_battle_struct(species=0x01, level=10)
        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.user_name = "TestUser"
        ctx.item = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=lambda p, u, k: prefs.get(k)),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
            patch("src.game_shops.pkpcrystal.get_species_tmhm_moves", return_value=[0x56, 0x91, 0x5E, 0x3A, 0x42]),
            patch("src.game_shops.pkpcrystal.get_move_name", return_value="TM Move"),
            patch("src.game_shops.pkpcrystal.shop_manager.purchase", return_value=MagicMock(success=True)),
            patch("src.game_shops.pkpcrystal.random.sample", return_value=[(0x56, "Flamethrower"), (0x91, "Ice Beam")]),
        ):
            result = await _on_select_tmhm_mon("0", ctx)

        assert isinstance(result, SelectionStep)
        assert len(result.options) == 2
        assert session.state["teach_message_prefix"] == "teach_tmhm_move"


class TestTmhmFullFlow:
    @pytest.mark.asyncio
    async def test_tmhm_full_flow_all_slots_filled(self):
        from src.game_shops.pkpcrystal import (
            _on_select_tmhm_mon, _on_select_teach_move, _on_select_teach_replace,
        )
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0x4A, 0x45])

        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.user_name = "TestUser"
        ctx.item = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=lambda p, u, k: prefs.get(k)),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
            patch("src.game_shops.pkpcrystal.get_move_name", side_effect=lambda pyboy, mid: {
                0x21: "Scratch", 0x2D: "Growl", 0x4A: "Vine Whip",
                0x45: "Leech Seed", 0x56: "Flamethrower", 0x91: "Ice Beam",
            }.get(mid, f"Move_{mid:02X}")),
            patch("src.game_shops.pkpcrystal.get_species_tmhm_moves", return_value=[0x56, 0x91]),
            patch("src.game_shops.pkpcrystal.shop_manager.purchase", return_value=MagicMock(success=True)),
            patch("src.game_shops.pkpcrystal.random.sample", return_value=[(0x56, "Flamethrower")]),
            patch("src.game_shops.pkpcrystal.state_manager.set_user_preference") as mock_set,
        ):
            step1 = await _on_select_tmhm_mon("0", ctx)
            assert isinstance(step1, SelectionStep), f"Expected SelectionStep, got {step1}"
            assert step1.on_select == _on_select_teach_move

            step2 = await _on_select_teach_move("0", ctx)
            assert isinstance(step2, SelectionStep), f"Expected SelectionStep, got {step2}"
            assert step2.on_select == _on_select_teach_replace
            assert len(step2.options) == 4

            final = await _on_select_teach_replace("0", ctx)

            assert final.success is True
            assert "replaced" in final.success_message
            mock_set.assert_called_once()
            updated_raw = bytes.fromhex(mock_set.call_args[0][3])
            assert updated_raw[2] == 0x56  # slot 0 overwritten with Flamethrower


# ─── teach_egg_move tests ───────────────────────────────────────────

class TestTeachEggMoveHandler:
    @pytest.mark.asyncio
    async def test_no_controller(self):
        from src.game_shops.pkpcrystal import teach_egg_move_handler
        ctx = MagicMock()
        ctx.game_controller = None
        result = await teach_egg_move_handler(ctx)
        assert result.success is False
        assert "no_game_controller" in result.error_message

    @pytest.mark.asyncio
    async def test_insufficient_balance(self):
        from src.game_shops.pkpcrystal import teach_egg_move_handler
        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.check_balance = AsyncMock(return_value=False)
        result = await teach_egg_move_handler(ctx)
        assert result.success is False
        assert "insufficient_funds" in result.error_message


class TestOnSelectEggMon:
    @pytest.mark.asyncio
    async def test_no_valid_egg_moves(self):
        from src.game_shops.pkpcrystal import _on_select_egg_mon
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0x4A, 0x45])
        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.user_name = "TestUser"
        ctx.item = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=lambda p, u, k: prefs.get(k)),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
            patch("src.game_shops.pkpcrystal.get_species_egg_moves", return_value=[]),
            patch("src.game_shops.pkpcrystal.shop_manager.purchase") as mock_purchase,
        ):
            result = await _on_select_egg_mon("0", ctx)

        assert isinstance(result, PurchaseComplete)
        assert result.success is False
        assert "no_moves" in result.error_message
        mock_purchase.assert_not_called()

    @pytest.mark.asyncio
    async def test_egg_move_full_flow(self):
        from src.game_shops.pkpcrystal import _on_select_egg_mon, _on_select_teach_move, _on_select_teach_replace
        raw = _make_mock_battle_struct(species=0x01, level=10, moves=[0x21, 0x2D, 0x4A, 0x45])

        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.user_name = "TestUser"
        ctx.item = MagicMock()
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=lambda p, u, k: prefs.get(k)),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Bulbasaur"),
            patch("src.game_shops.pkpcrystal.get_move_name", side_effect=lambda pyboy, mid: {
                0x21: "Scratch", 0x2D: "Growl", 0x4A: "Vine Whip",
                0x45: "Leech Seed", 0xCC: "Petal Dance",
            }.get(mid, f"Move_{mid:02X}")),
            patch("src.game_shops.pkpcrystal.get_species_egg_moves", return_value=[0xCC]),
            patch("src.game_shops.pkpcrystal.shop_manager.purchase", return_value=MagicMock(success=True)),
            patch("src.game_shops.pkpcrystal.random.sample", return_value=[(0xCC, "Petal Dance")]),
            patch("src.game_shops.pkpcrystal.state_manager.set_user_preference") as mock_set,
        ):
            step1 = await _on_select_egg_mon("0", ctx)
            assert isinstance(step1, SelectionStep), f"Expected SelectionStep, got {step1}"
            assert step1.on_select == _on_select_teach_move

            step2 = await _on_select_teach_move("0", ctx)
            assert isinstance(step2, SelectionStep)
            assert step2.on_select == _on_select_teach_replace

            final = await _on_select_teach_replace("0", ctx)
            assert final.success is True
            assert "replaced" in final.success_message
            mock_set.assert_called_once()
            updated_raw = bytes.fromhex(mock_set.call_args[0][3])
            assert updated_raw[2] == 0xCC
