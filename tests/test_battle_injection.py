"""Tests for battle injection (cache, dummy mon builder, hooks, purchase handler)."""

import pytest
from unittest.mock import MagicMock

from src.game_hooks.pkpcrystal import (
    _battle_requests,
    _build_dummy_party_mon,
    _resolve_battle_request,
    _remove_battle_request,
    queue_battle_request,
    begin_hooks,
    DITTO,
    MON_LEVEL,
    PARTYMON_STRUCT_LENGTH,
    SCRIPT_STARTBATTLE,
    SCRIPT_RELOADMAP,
    SCRIPT_END,
    TRANSFORM_MOVE_ID,
    TEXT_FAR,
    TEXT_TERM,
)


def _get_hook_callback(pyboy, hook_name):
    for call_ in pyboy.hook_register.call_args_list:
        args, _ = call_
        if args[1] == hook_name:
            return args[2]
    return None


def _make_mock_pyboy():
    pyboy = MagicMock()
    memory_store = {}

    def memory_getitem(key):
        if isinstance(key, tuple):
            return memory_store.get(key[1], 0)
        return memory_store.get(key, 0)

    def memory_setitem(key, value):
        if isinstance(key, tuple):
            memory_store[key[1]] = value
        else:
            memory_store[key] = value

    pyboy.memory.__getitem__.side_effect = memory_getitem
    pyboy.memory.__setitem__.side_effect = memory_setitem
    pyboy.symbol_lookup.side_effect = lambda sym: (0, 0xC000)

    return pyboy, memory_store


class TestBattleRequestCache:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _battle_requests.clear()

    def test_queue_creates_pending_entry(self):
        queue_battle_request(111, 222)
        assert _battle_requests[111] == {"state": "pending", "user_id": 222}

    def test_resolve_returns_entry(self):
        queue_battle_request(111, 222)
        entry = _resolve_battle_request(111)
        assert entry == {"state": "pending", "user_id": 222}

    def test_resolve_returns_none_for_missing(self):
        assert _resolve_battle_request(999) is None

    def test_remove_deletes_entry(self):
        queue_battle_request(111, 222)
        _remove_battle_request(111)
        assert _resolve_battle_request(111) is None

    def test_remove_nonexistent_does_not_raise(self):
        _remove_battle_request(999)

    def test_per_chat_isolation(self):
        queue_battle_request(111, 222)
        queue_battle_request(333, 444)
        _remove_battle_request(111)
        assert _resolve_battle_request(111) is None
        assert _resolve_battle_request(333) == {"state": "pending", "user_id": 444}


class TestBuildDummyPartyMon:
    def test_returns_48_bytes(self):
        data = _build_dummy_party_mon(5)
        assert len(data) == PARTYMON_STRUCT_LENGTH

    def test_species_is_ditto_at_offset_0(self):
        data = _build_dummy_party_mon(5)
        assert data[0] == DITTO

    def test_level_matches_input(self):
        data = _build_dummy_party_mon(42)
        assert data[MON_LEVEL] == 42

    def test_dvs_are_max(self):
        data = _build_dummy_party_mon(5)
        assert data[17] == 0xFF
        assert data[18] == 0xFF
        assert data[19] == 0xFF

    def test_hp_is_nonzero(self):
        data = _build_dummy_party_mon(5)
        hp = (data[34] << 8) | data[35]
        maxhp = (data[36] << 8) | data[37]
        assert hp > 0
        assert maxhp > 0
        assert hp == maxhp


class TestHookABasicBehavior:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _battle_requests.clear()

    def test_hook_a_skips_without_cache(self):
        pyboy, memory_store = _make_mock_pyboy()
        begin_hooks(pyboy, chat_id=111)
        callback = _get_hook_callback(pyboy, "PlayerEvents")
        assert callback is not None
        callback(None)
        assert len(memory_store) == 0

    def test_hook_a_skips_wrong_state(self):
        pyboy, memory_store = _make_mock_pyboy()
        begin_hooks(pyboy, chat_id=111)
        queue_battle_request(111, 222)
        _battle_requests[111]["state"] = "starting"
        callback = _get_hook_callback(pyboy, "PlayerEvents")
        assert callback is not None
        callback(None)
        assert _battle_requests[111]["state"] == "starting"
        assert len(memory_store) == 0

    def test_hook_a_revalidates_state(self):
        pyboy, memory_store = _make_mock_pyboy()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        begin_hooks(pyboy, chat_id=111)
        queue_battle_request(111, 222)
        memory_store[0xD001] = 1
        callback = _get_hook_callback(pyboy, "PlayerEvents")
        assert callback is not None
        callback(None)
        assert _battle_requests[111]["state"] == "pending"

    def test_hook_a_writes_script_data(self):
        pyboy, memory_store = _make_mock_pyboy()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
            "wPartyMon1Level": (0, 0xD004),
            "wFootprintQueue": (0, 0xC100),
            "hScriptBank": (0, 0xFFEB),
            "hScriptPos": (0, 0xFFEC),
            "wOtherTrainerClass": (0, 0xD010),
            "wScriptMode": (0, 0xD011),
            "wBattleScriptFlags": (0, 0xD012),
            "wWinTextPointer": (1, 0xD047),
            "YoungsterGordonBeatenText": (0x17, 0x7C1B),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        begin_hooks(pyboy, chat_id=111)
        queue_battle_request(111, 222)
        memory_store[0xD001] = 0
        memory_store[0xD002] = 0
        memory_store[0xD003] = 3
        memory_store[0xD004] = 7
        callback = _get_hook_callback(pyboy, "PlayerEvents")
        assert callback is not None
        callback(None)
        assert _battle_requests[111]["state"] == "starting"
        assert _battle_requests[111]["level"] == 7
        assert memory_store[0xC107] == SCRIPT_STARTBATTLE
        assert memory_store[0xC108] == SCRIPT_RELOADMAP
        assert memory_store[0xC109] == SCRIPT_END
        far_addr = 0xC10A
        assert memory_store[far_addr] == TEXT_FAR
        assert memory_store[far_addr + 1] == (0x7C1B & 0xFF)
        assert memory_store[far_addr + 2] == ((0x7C1B >> 8) & 0xFF)
        assert memory_store[far_addr + 3] == 0x17
        assert memory_store[far_addr + 4] == TEXT_TERM
        assert memory_store[0xFFEB] == 0
        assert memory_store[0xFFEC] == (0xC107 & 0xFF)
        assert memory_store[0xFFED] == ((0xC107 >> 8) & 0xFF)
        assert memory_store[0xD002] == 1
        assert memory_store[0xD011] == 1
        assert memory_store[0xD010] == 1
        assert memory_store[0xD012] == 0x81
        assert memory_store[0xD047] == (far_addr & 0xFF)
        assert memory_store[0xD048] == ((far_addr >> 8) & 0xFF)
        assert memory_store[0xD049] == (far_addr & 0xFF)
        assert memory_store[0xD04A] == ((far_addr >> 8) & 0xFF)


class TestHookBBasicBehavior:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _battle_requests.clear()

    def test_hook_b_skips_without_cache(self):
        pyboy, memory_store = _make_mock_pyboy()
        begin_hooks(pyboy, chat_id=111)
        callback = _get_hook_callback(pyboy, "ComputeTrainerReward")
        assert callback is not None
        callback(None)
        assert len(memory_store) == 0

    def test_hook_b_skips_without_starting(self):
        pyboy, memory_store = _make_mock_pyboy()
        begin_hooks(pyboy, chat_id=111)
        queue_battle_request(111, 222)
        callback = _get_hook_callback(pyboy, "ComputeTrainerReward")
        assert callback is not None
        callback(None)
        assert _battle_requests[111]["state"] == "pending"
        assert len(memory_store) == 0

    def test_hook_b_writes_data_and_clears_cache(self):
        pyboy, memory_store = _make_mock_pyboy()
        sym_addrs = {
            "wOTPartyCount": (0, 0xD100),
            "wOTPartyMon1": (0, 0xD101),
            "wOTPartyMonNicknames": (0, 0xD200),
            "wCurPartySpecies": (0, 0xD300),
            "wCurPartyLevel": (0, 0xD301),
            "wCurForm": (0, 0xD302),
            "wMonType": (0, 0xD303),
            "wOtherTrainerType": (0, 0xD304),
            "wEnemyTrainerAIFlags": (0, 0xD400),
            "wBattleReward": (0, 0xD500),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        begin_hooks(pyboy, chat_id=111)
        _battle_requests[111] = {"state": "starting", "level": 5, "user_id": 222}
        callback = _get_hook_callback(pyboy, "ComputeTrainerReward")
        assert callback is not None
        callback(None)
        assert _resolve_battle_request(111) is None
        dummy = _build_dummy_party_mon(5)
        for i in range(48):
            assert memory_store[0xD101 + i] == dummy[i], f"Mismatch at offset {i}"
        ditto_name = [0x83, 0x88, 0x93, 0x93, 0x8e]
        for i, c in enumerate(ditto_name):
            assert memory_store[0xD200 + i] == c
        assert memory_store[0xD205] == 0x53
        for i in range(6, 11):
            assert memory_store[0xD200 + i] == 0x53


class TestPurchaseHandler:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _battle_requests.clear()

    @pytest.mark.asyncio
    async def test_redeem_battle_no_controller(self):
        from src.game_shops.pkpcrystal import redeem_battle_handler

        ctx = MagicMock()
        ctx.game_controller = None
        result = await redeem_battle_handler(ctx)
        assert result.success is False
        assert "no_game_controller" in result.error_message

    @pytest.mark.asyncio
    async def test_redeem_battle_in_battle(self):
        from src.game_shops.pkpcrystal import redeem_battle_handler

        pyboy = MagicMock()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store = {}
        pyboy.memory.__getitem__.side_effect = (
            lambda k: memory_store.get(k[1] if isinstance(k, tuple) else k, 0)
        )
        pyboy.memory.__setitem__.side_effect = (
            lambda k, v: memory_store.update(
                {k[1] if isinstance(k, tuple) else k: v}
            )
        )
        memory_store[0xD001] = 1

        controller = MagicMock()
        controller.pyboy = pyboy

        ctx = MagicMock()
        ctx.game_controller = controller
        ctx.chat_id = 111
        ctx.user_id = 222

        result = await redeem_battle_handler(ctx)
        assert result.success is False
        assert "in_battle" in result.error_message
        assert _resolve_battle_request(111) is None

    @pytest.mark.asyncio
    async def test_redeem_battle_success(self):
        from src.game_shops.pkpcrystal import redeem_battle_handler

        pyboy = MagicMock()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store = {}
        pyboy.memory.__getitem__.side_effect = (
            lambda k: memory_store.get(k[1] if isinstance(k, tuple) else k, 0)
        )
        pyboy.memory.__setitem__.side_effect = (
            lambda k, v: memory_store.update(
                {k[1] if isinstance(k, tuple) else k: v}
            )
        )
        memory_store[0xD001] = 0
        memory_store[0xD002] = 0
        memory_store[0xD003] = 6

        controller = MagicMock()
        controller.pyboy = pyboy

        ctx = MagicMock()
        ctx.game_controller = controller
        ctx.chat_id = 111
        ctx.user_id = 222

        result = await redeem_battle_handler(ctx)
        assert result.success is True
        entry = _resolve_battle_request(111)
        assert entry is not None
        assert entry["state"] == "pending"
        assert entry["user_id"] == 222
