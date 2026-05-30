"""Tests for battle injection (cache, party builder, name encoder, hooks, purchase handler)."""

import pytest
from unittest.mock import MagicMock, patch

from src.game_hooks.pkpcrystal import (
    _battle_requests,
    _resolve_battle_request,
    _remove_battle_request,
    queue_battle_request,
    begin_hooks,
    PARTYMON_STRUCT_LENGTH,
    _read_player_party_levels,
    BATTLE_SCRIPT,
    SCRIPT_STARTBATTLE,
    SCRIPT_RELOADMAP,
    SCRIPT_END,
    SCRIPT_OPENTEXT,
    SCRIPT_FARWRITETEXT,
    SCRIPT_CLOSETEXT,
    SCRIPT_PLAYSOUND,
    SCRIPT_WAITSFX,
    SFX_ITEM,
    TEXT_BYTES,
    TEXT_FAR,
    TEXT_TERM,
)
from src.game_utils.pkpcrystal.charmap import REVERSE_CHARMAP, encode_name, NAME_LENGTH, MON_NAME_LENGTH
from src.game_utils.pkpcrystal.party_builder import (
    battle_struct_to_party,
    BATTLE_STRUCT_SIZE,
    PARTY_STRUCT_SIZE,
)


def _make_mock_battle_struct(species: int = 0x84, level: int = 5) -> bytes:
    buf = bytearray(35)
    buf[0] = species
    buf[1] = 0x00
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


def _make_mock_pyboy():
    pyboy = MagicMock()
    memory_store = {}

    def memory_getitem(key):
        if isinstance(key, tuple):
            if isinstance(key[1], slice):
                start = key[1].start
                stop = key[1].stop
                return [memory_store.get(i, 0) for i in range(start, stop)]
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


def _get_hook_callback(pyboy, hook_name):
    for call_ in pyboy.hook_register.call_args_list:
        args, _ = call_
        if args[0] is None and args[1] == hook_name:
            return args[2]
    return None


# ─── Cache ────────────────────────────────────────────────────────────

class TestBattleRequestCache:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _battle_requests.clear()

    def _queue(self, chat_id=111, user_id=222):
        queue_battle_request(chat_id, user_id, "test", "TestUser", 1, [0x80] * 11, [bytes(PARTY_STRUCT_SIZE)])

    def test_queue_creates_pending_entry(self):
        self._queue()
        entry = _battle_requests[111]
        assert entry["state"] == "pending"
        assert entry["user_id"] == 222
        assert entry["platform"] == "test"
        assert entry["user_name"] == "TestUser"
        assert entry["trainer_class"] == 1
        assert entry["trainer_name_bytes"] == [0x80] * 11
        assert len(entry["party_mons"]) == 1

    def test_resolve_returns_entry(self):
        self._queue()
        entry = _resolve_battle_request(111)
        assert entry is not None
        assert entry["state"] == "pending"

    def test_resolve_returns_none_for_missing(self):
        assert _resolve_battle_request(999) is None

    def test_remove_deletes_entry(self):
        self._queue()
        _remove_battle_request(111)
        assert _resolve_battle_request(111) is None

    def test_remove_nonexistent_does_not_raise(self):
        _remove_battle_request(999)

    def test_per_chat_isolation(self):
        self._queue(111, 222)
        self._queue(333, 444)
        _remove_battle_request(111)
        assert _resolve_battle_request(111) is None
        assert _resolve_battle_request(333)["user_id"] == 444


# ─── Party Builder ────────────────────────────────────────────────────

class TestBattleStructToParty:
    def test_output_is_48_bytes(self):
        raw = _make_mock_battle_struct()
        party = battle_struct_to_party(raw)
        assert len(party) == PARTY_STRUCT_SIZE

    def test_species_copied(self):
        raw = _make_mock_battle_struct(species=0x99)
        party = battle_struct_to_party(raw)
        assert party[0] == 0x99

    def test_item_copied(self):
        raw = _make_mock_battle_struct()
        raw = bytearray(raw)
        raw[1] = 0x42
        party = battle_struct_to_party(bytes(raw))
        assert party[1] == 0x42

    def test_moves_copied(self):
        raw = _make_mock_battle_struct()
        party = battle_struct_to_party(raw)
        assert party[2:6] == raw[2:6]

    def test_id_exp_evs_are_zero(self):
        raw = _make_mock_battle_struct()
        party = battle_struct_to_party(raw)
        assert party[6:17] == bytes(11)

    def test_dvs_copied(self):
        raw = _make_mock_battle_struct()
        party = battle_struct_to_party(raw)
        assert party[17:20] == raw[6:9]

    def test_nature_and_form_copied(self):
        raw = _make_mock_battle_struct()
        party = battle_struct_to_party(raw)
        assert party[20] == raw[9]
        assert party[21] == raw[10]

    def test_pp_copied(self):
        raw = _make_mock_battle_struct()
        party = battle_struct_to_party(raw)
        assert party[22:26] == raw[11:15]

    def test_level_copied(self):
        raw = _make_mock_battle_struct(level=42)
        party = battle_struct_to_party(raw)
        assert party[31] == 42

    def test_status_is_zeroed(self):
        raw = bytearray(_make_mock_battle_struct())
        raw[17] = 0x07
        raw[18] = 0x01
        party = battle_struct_to_party(bytes(raw))
        assert party[32] == 0
        assert party[33] == 0

    def test_hp_equals_maxhp(self):
        raw = _make_mock_battle_struct()
        party = battle_struct_to_party(raw)
        hp = (party[35] << 8) | party[34]
        maxhp = (party[37] << 8) | party[36]
        assert hp == maxhp
        assert hp > 0

    def test_hp_uses_battle_maxhp_not_hp(self):
        raw = bytearray(_make_mock_battle_struct())
        raw[19] = 0x01
        raw[20] = 0x00
        raw[21] = 0xE8
        raw[22] = 0x03
        party = battle_struct_to_party(bytes(raw))
        hp = (party[35] << 8) | party[34]
        assert hp == 1000

    def test_stats_copied(self):
        raw = _make_mock_battle_struct()
        party = battle_struct_to_party(raw)
        assert party[38:40] == raw[23:25]
        assert party[40:42] == raw[25:27]
        assert party[42:44] == raw[27:29]
        assert party[44:46] == raw[29:31]
        assert party[46:48] == raw[31:33]


# ─── Name Encoding ────────────────────────────────────────────────────

class TestEncodeName:
    def test_uppercase_maps_correctly(self):
        result = encode_name("ABC")
        assert result[:3] == [0x80, 0x81, 0x82]
        assert result[3] == 0x53

    def test_lowercase_maps_correctly(self):
        result = encode_name("abc")
        assert result[:3] == [0xA0, 0xA1, 0xA2]
        assert result[3] == 0x53

    def test_digits_map_correctly(self):
        result = encode_name("42")
        assert result[:2] == [0xE4, 0xE2]
        assert result[2] == 0x53

    def test_unsupported_char_maps_to_zero(self):
        result = encode_name("\u00f1llo")
        assert result[0] == 0x00

    def test_result_terminated_with_0x53(self):
        result = encode_name("Hi")
        assert result[2] == 0x53

    def test_rest_padded_with_0x53(self):
        result = encode_name("Hi")
        assert result[3:] == [0x53] * 8

    def test_result_is_truncated_to_name_length(self):
        long_name = "A" * 20
        result = encode_name(long_name)
        assert len(result) == NAME_LENGTH
        assert result[-1] == 0x53

    def test_special_chars_map_correctly(self):
        result = encode_name("(.)!?-")
        assert result[0] == REVERSE_CHARMAP["("]
        assert result[1] == REVERSE_CHARMAP["."]
        assert result[2] == REVERSE_CHARMAP[")"]
        assert result[3] == REVERSE_CHARMAP["!"]
        assert result[4] == REVERSE_CHARMAP["?"]
        assert result[5] == REVERSE_CHARMAP["-"]
        assert result[6] == 0x53

    def test_empty_name_all_0x53(self):
        result = encode_name("")
        assert result == [0x53] * NAME_LENGTH

    def test_ten_chars_leaves_one_0x53(self):
        result = encode_name("ABCDEFGHIJ")
        assert len(result) == NAME_LENGTH
        assert result[:10] == [0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89]
        assert result[10] == 0x53

    def test_eleven_chars_truncates_last(self):
        result = encode_name("ABCDEFGHIJK")
        assert len(result) == NAME_LENGTH
        assert result[:10] == [0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89]
        assert result[10] == 0x53


# ─── Hook A ───────────────────────────────────────────────────────────

class TestHookABasicBehavior:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _battle_requests.clear()

    def test_hook_a_skips_without_cache(self):
        pyboy, memory_store = _make_mock_pyboy()
        memory_store[0xC000] = 1
        begin_hooks(pyboy, chat_id=111)
        callback = _get_hook_callback(pyboy, "PlayerEvents")
        assert callback is not None
        callback(None)
        assert _resolve_battle_request(111) is None

    def test_hook_a_skips_wrong_state(self):
        pyboy, memory_store = _make_mock_pyboy()
        begin_hooks(pyboy, chat_id=111)
        queue_battle_request(111, 222, "test", "TestUser", 1, [0x80] * 11, [bytes(PARTY_STRUCT_SIZE)])
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
        queue_battle_request(111, 222, "test", "TestUser", 1, [0x80] * 11, [bytes(PARTY_STRUCT_SIZE)])
        memory_store[0xD001] = 1
        callback = _get_hook_callback(pyboy, "PlayerEvents")
        assert callback is not None
        callback(None)
        assert _battle_requests[111]["state"] == "pending"

    def test_hook_a_uses_trainer_class_from_cache(self):
        pyboy, memory_store = _make_mock_pyboy()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
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
        queue_battle_request(111, 222, "test", "TestUser", 42, [0x80] * 11, [bytes(PARTY_STRUCT_SIZE)])
        memory_store[0xD001] = 0
        memory_store[0xD002] = 0
        memory_store[0xD003] = 3
        callback = _get_hook_callback(pyboy, "PlayerEvents")
        assert callback is not None
        callback(None)
        assert memory_store[0xD010] == 42

    def test_hook_a_writes_script_data(self):
        pyboy, memory_store = _make_mock_pyboy()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
            "wFootprintQueue": (0, 0xC100),
            "hScriptBank": (0, 0xFFEB),
            "hScriptPos": (0, 0xFFEC),
            "wOtherTrainerClass": (0, 0xD010),
            "wScriptMode": (0, 0xD011),
            "wBattleScriptFlags": (0, 0xD012),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        begin_hooks(pyboy, chat_id=111)
        queue_battle_request(111, 222, "test", "TestUser", 1, [0x80] * 11, [bytes(PARTY_STRUCT_SIZE)])
        memory_store[0xD001] = 0
        memory_store[0xD002] = 0
        memory_store[0xD003] = 3
        callback = _get_hook_callback(pyboy, "PlayerEvents")
        assert callback is not None
        callback(None)
        assert _battle_requests[111]["state"] == "starting"

        script_addr = 0xC107
        assert memory_store[script_addr] == SCRIPT_STARTBATTLE
        assert memory_store[script_addr + 1] == SCRIPT_RELOADMAP
        assert memory_store[script_addr + 2] == SCRIPT_END
        assert memory_store[0xFFEB] == 0
        assert memory_store[0xFFEC] == (script_addr & 0xFF)
        assert memory_store[0xFFED] == ((script_addr >> 8) & 0xFF)
        assert memory_store[0xD002] == 1
        assert memory_store[0xD011] == 1
        assert memory_store[0xD012] == 0x81


# ─── Hook B ───────────────────────────────────────────────────────────

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
        queue_battle_request(111, 222, "test", "TestUser", 1, [0x80] * 11, [bytes(PARTY_STRUCT_SIZE)])
        callback = _get_hook_callback(pyboy, "ComputeTrainerReward")
        assert callback is not None
        callback(None)
        assert _battle_requests[111]["state"] == "pending"
        assert len(memory_store) == 0

    def test_hook_b_skips_with_empty_party(self):
        pyboy, memory_store = _make_mock_pyboy()
        begin_hooks(pyboy, chat_id=111)
        _battle_requests[111] = {"state": "starting", "party_mons": []}
        callback = _get_hook_callback(pyboy, "ComputeTrainerReward")
        assert callback is not None
        callback(None)
        assert len(memory_store) == 0

    def test_hook_b_writes_single_mon(self):
        pyboy, memory_store = _make_mock_pyboy()
        raw = _make_mock_battle_struct(species=42, level=7)
        party = battle_struct_to_party(raw)
        sym_addrs = {
            "wOTPartyMons": (1, 0xD000),
            "wOTPartyMonOTs": (1, 0xD100),
            "wOTPartyMonNicknames": (1, 0xD200),
            "wOTPartyCount": (1, 0xCFFF),
            "wCurPartySpecies": (1, 0xD300),
            "wCurPartyLevel": (1, 0xD301),
            "wCurForm": (1, 0xD302),
            "wMonType": (1, 0xD303),
            "wOtherTrainerType": (1, 0xD304),
            "wEnemyTrainerAIFlags": (1, 0xD400),
            "wBattleReward": (1, 0xD500),
            "wInBattleTowerBattle": (0, 0xCE94),
            "wOTPlayerName": (1, 0xD276),
            "PokemonNames": (0x0F, 0x8000),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        _make_mock_pyboy_svbk(pyboy, memory_store)
        with patch("src.game_hooks.pkpcrystal.get_pokemon_name", return_value="GOLDUCK"):
            begin_hooks(pyboy, chat_id=111)
            name_bytes = [0x86, 0xA8, 0xA0, 0xAD, 0x53, 0x53, 0x53, 0x53, 0x53, 0x53, 0x53]
            _battle_requests[111] = {"state": "starting", "party_mons": [party], "user_id": 222, "trainer_name_bytes": name_bytes}
            callback = _get_hook_callback(pyboy, "ComputeTrainerReward")
            assert callback is not None
            callback(None)
        assert _resolve_battle_request(111)["state"] == "in_battle"
        assert memory_store[0xCFFF] == 1
        for i in range(6):
            assert memory_store[0xD000 + i] == party[i], f"Mismatch at offset {i}"
        for i in range(33, PARTY_STRUCT_SIZE):
            assert memory_store[0xD000 + i] == party[i], f"Mismatch at offset {i}"
        assert memory_store[0xD000 + 16] == party[31]
        assert memory_store[0xD000 + 19] == party[34]
        assert memory_store[0xD000 + 20] == party[35]
        assert memory_store[0xD000 + 21] == party[36]
        assert memory_store[0xD000 + 22] == party[37]
        assert memory_store[0xD300] == 42
        assert memory_store[0xD301] == 7
        assert memory_store[0xCE94] == 1
        for i in range(11):
            assert memory_store[0xD276 + i] == name_bytes[i], f"OT name byte {i}"

    def test_hook_b_writes_multiple_mons(self):
        pyboy, memory_store = _make_mock_pyboy()
        party0 = battle_struct_to_party(_make_mock_battle_struct(species=0x99, level=5))
        party1 = battle_struct_to_party(_make_mock_battle_struct(species=0x88, level=10))
        sym_addrs = {
            "wOTPartyMons": (1, 0xD000),
            "wOTPartyMonOTs": (1, 0xD100),
            "wOTPartyMonNicknames": (1, 0xD200),
            "wOTPartyCount": (1, 0xCFFF),
            "wCurPartySpecies": (1, 0xD300),
            "wCurPartyLevel": (1, 0xD301),
            "wCurForm": (1, 0xD302),
            "wMonType": (1, 0xD303),
            "wOtherTrainerType": (1, 0xD304),
            "wEnemyTrainerAIFlags": (1, 0xD400),
            "wBattleReward": (1, 0xD500),
            "PokemonNames": (0x0F, 0x8000),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        _make_mock_pyboy_svbk(pyboy, memory_store)
        with patch("src.game_hooks.pkpcrystal.get_pokemon_name", return_value="UNOWN"):
            begin_hooks(pyboy, chat_id=111)
            _battle_requests[111] = {"state": "starting", "party_mons": [party0, party1], "user_id": 222}
            callback = _get_hook_callback(pyboy, "ComputeTrainerReward")
            assert callback is not None
            callback(None)
        assert memory_store[0xCFFF] == 2
        for i in range(6):
            assert memory_store[0xD000 + i] == party0[i], f"Mismatch at mon0 offset {i}"
        for i in range(33, PARTY_STRUCT_SIZE):
            assert memory_store[0xD000 + i] == party0[i], f"Mismatch at mon0 offset {i}"
        for i in range(PARTY_STRUCT_SIZE):
            assert memory_store[0xD030 + i] == party1[i], f"Mismatch at mon1 offset {i}"
        assert memory_store[0xD300] == 0x99
        assert memory_store[0xD301] == 5

    def test_hook_b_writes_terminator_ots(self):
        pyboy, memory_store = _make_mock_pyboy()
        party = battle_struct_to_party(_make_mock_battle_struct(species=1, level=5))
        sym_addrs = {
            "wOTPartyMons": (1, 0xD000),
            "wOTPartyMonOTs": (1, 0xD100),
            "wOTPartyMonNicknames": (1, 0xD200),
            "wOTPartyCount": (1, 0xCFFF),
            "wCurPartySpecies": (1, 0xD300),
            "wCurPartyLevel": (1, 0xD301),
            "wCurForm": (1, 0xD302),
            "wMonType": (1, 0xD303),
            "wOtherTrainerType": (1, 0xD304),
            "wEnemyTrainerAIFlags": (1, 0xD400),
            "wBattleReward": (1, 0xD500),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        _make_mock_pyboy_svbk(pyboy, memory_store)
        with patch("src.game_hooks.pkpcrystal.get_pokemon_name", return_value="BULBASAUR"):
            begin_hooks(pyboy, chat_id=111)
            _battle_requests[111] = {"state": "starting", "party_mons": [party], "user_id": 222}
            callback = _get_hook_callback(pyboy, "ComputeTrainerReward")
            assert callback is not None
            callback(None)
        for i in range(11):
            assert memory_store[0xD100 + i] == 0x53, f"OT name offset {i}"

    def test_hook_b_writes_species_nicknames(self):
        pyboy, memory_store = _make_mock_pyboy()
        party = battle_struct_to_party(_make_mock_battle_struct(species=25, level=5))
        sym_addrs = {
            "wOTPartyMons": (1, 0xD000),
            "wOTPartyMonOTs": (1, 0xD100),
            "wOTPartyMonNicknames": (1, 0xD200),
            "wOTPartyCount": (1, 0xCFFF),
            "wCurPartySpecies": (1, 0xD300),
            "wCurPartyLevel": (1, 0xD301),
            "wCurForm": (1, 0xD302),
            "wMonType": (1, 0xD303),
            "wOtherTrainerType": (1, 0xD304),
            "wEnemyTrainerAIFlags": (1, 0xD400),
            "wBattleReward": (1, 0xD500),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        _make_mock_pyboy_svbk(pyboy, memory_store)
        with patch("src.game_hooks.pkpcrystal.get_pokemon_name", return_value="PIKACHU"):
            begin_hooks(pyboy, chat_id=111)
            _battle_requests[111] = {"state": "starting", "party_mons": [party], "user_id": 222}
            callback = _get_hook_callback(pyboy, "ComputeTrainerReward")
            assert callback is not None
            callback(None)
        expected = [0x8F, 0x88, 0x8A, 0x80, 0x82, 0x87, 0x94, 0x53, 0x53, 0x53, 0x53]
        for i in range(MON_NAME_LENGTH):
            assert memory_store[0xD200 + i] == expected[i], f"Nickname byte {i}"


# ─── ReloadmapAfterBattle ───────────────────────────────────────────────

class TestReloadmapAfterBattle:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _battle_requests.clear()

    def _setup_reload(self, pyboy, memory_store):
        syms = {
            "wInBattleTowerBattle": (0, 0xCE94),
            "wBattleResult": (0, 0xD0F6),
            "wExpCandySAmount": (1, 0xDBC9),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: syms.get(sym, (0, 0xC000))
        _battle_requests[111] = {"state": "in_battle"}
        begin_hooks(pyboy, chat_id=111)
        return _get_hook_callback(pyboy, "Script_reloadmapafterbattle")

    def test_gives_candy_and_sets_reward_pending_on_win(self):
        pyboy, memory_store = _make_mock_pyboy()
        callback = self._setup_reload(pyboy, memory_store)
        memory_store[0xD0F6] = 0
        memory_store[0xDBC9] = 5
        memory_store[0xFF70] = 1
        callback(None)
        assert memory_store[0xDBC9] == 6
        assert _battle_requests[111]["state"] == "reward_pending"
        assert memory_store[0xCE94] == 0

    def test_does_not_give_candy_on_loss(self):
        pyboy, memory_store = _make_mock_pyboy()
        callback = self._setup_reload(pyboy, memory_store)
        memory_store[0xD0F6] = 1
        callback(None)
        assert _resolve_battle_request(111) is None

    def test_does_not_give_candy_on_draw(self):
        pyboy, memory_store = _make_mock_pyboy()
        callback = self._setup_reload(pyboy, memory_store)
        memory_store[0xD0F6] = 2
        callback(None)
        assert _resolve_battle_request(111) is None

    def test_skips_without_cache(self):
        pyboy, memory_store = _make_mock_pyboy()
        syms = {"wInBattleTowerBattle": (0, 0xCE94)}
        pyboy.symbol_lookup.side_effect = lambda sym: syms.get(sym, (0, 0xC000))
        begin_hooks(pyboy, chat_id=111)
        callback = _get_hook_callback(pyboy, "Script_reloadmapafterbattle")
        memory_store[0xCE94] = 1
        callback(None)
        assert memory_store[0xCE94] == 0

    def test_caps_candy_at_255(self):
        pyboy, memory_store = _make_mock_pyboy()
        callback = self._setup_reload(pyboy, memory_store)
        memory_store[0xD0F6] = 0
        memory_store[0xDBC9] = 255
        memory_store[0xFF70] = 1
        callback(None)
        assert memory_store[0xDBC9] == 255


# ─── Hook A reward_pending ──────────────────────────────────────────────

class TestHookARewardPending:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _battle_requests.clear()

    def test_injects_reward_text_on_reward_pending(self):
        pyboy, memory_store = _make_mock_pyboy()
        sym_addrs = {
            "wFootprintQueue": (0, 0xC100),
            "hScriptBank": (0, 0xFFEB),
            "hScriptPos": (0, 0xFFEC),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        begin_hooks(pyboy, chat_id=111)
        _battle_requests[111] = {"state": "reward_pending"}
        callback = _get_hook_callback(pyboy, "PlayerEvents")
        assert callback is not None
        callback(None)

        script_addr = 0xC107
        reward_script_len = 10
        text_addr = script_addr + reward_script_len
        assert memory_store[script_addr] == SCRIPT_OPENTEXT
        assert memory_store[script_addr + 1] == SCRIPT_FARWRITETEXT
        assert memory_store[script_addr + 2] == 0
        assert memory_store[script_addr + 3] == (text_addr & 0xFF)
        assert memory_store[script_addr + 4] == ((text_addr >> 8) & 0xFF)
        assert memory_store[script_addr + 5] == SCRIPT_PLAYSOUND
        assert memory_store[script_addr + 6] == SFX_ITEM
        assert memory_store[script_addr + 7] == SCRIPT_WAITSFX
        assert memory_store[script_addr + 8] == SCRIPT_CLOSETEXT
        assert memory_store[script_addr + 9] == SCRIPT_END

        for i, b in enumerate(TEXT_BYTES):
            assert memory_store[text_addr + i] == b, f"Text byte {i} mismatch"

        assert memory_store[0xFFEB] == 0
        assert memory_store[0xFFEC] == (script_addr & 0xFF)
        assert memory_store[0xFFED] == ((script_addr >> 8) & 0xFF)
        assert _resolve_battle_request(111) is None


def _make_mock_pyboy_svbk(pyboy, memory_store):
    memory_store[0xFF70] = 1
    original_setitem = pyboy.memory.__setitem__.side_effect
    def setitem_with_svbk(key, value):
        if isinstance(key, tuple) and key[0] == 1:
            memory_store[key[1]] = value
        elif not isinstance(key, tuple) and key != 0xFF70:
            memory_store[key] = value
        elif key == 0xFF70:
            memory_store[0xFF70] = value
        else:
            original_setitem(key, value)
    pyboy.memory.__setitem__.side_effect = setitem_with_svbk


# ─── Purchase Handler ─────────────────────────────────────────────────

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
        memory_store = {0xD001: 1}
        pyboy.memory.__getitem__.side_effect = (
            lambda k: memory_store.get(k[1] if isinstance(k, tuple) else k, 0)
        )
        controller = MagicMock()
        controller.pyboy = pyboy
        ctx = MagicMock()
        ctx.game_controller = controller
        ctx.chat_id = 111
        ctx.user_id = 222
        result = await redeem_battle_handler(ctx)
        assert result.success is False
        assert "in_battle" in result.error_message

    @pytest.mark.asyncio
    async def test_redeem_battle_rejects_no_mons(self):
        from src.game_shops.pkpcrystal import redeem_battle_handler
        pyboy = MagicMock()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store = {0xD001: 0, 0xD002: 0, 0xD003: 6}
        pyboy.memory.__getitem__.side_effect = (
            lambda k: memory_store.get(k[1] if isinstance(k, tuple) else k, 0)
        )
        controller = MagicMock()
        controller.pyboy = pyboy
        ctx = MagicMock()
        ctx.game_controller = controller
        ctx.chat_id = 111
        ctx.user_id = 222
        ctx.platform = "test"
        ctx.user_name = "TestUser"
        with patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", return_value=None):
            result = await redeem_battle_handler(ctx)
        assert result.success is False
        assert "no_party_mons" in result.error_message
        assert _resolve_battle_request(111) is None

    @pytest.mark.asyncio
    async def test_redeem_battle_uses_avatar_class(self):
        from src.game_shops.pkpcrystal import redeem_battle_handler
        pyboy = MagicMock()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store = {0xD001: 0, 0xD002: 0, 0xD003: 6}
        pyboy.memory.__getitem__.side_effect = (
            lambda k: memory_store.get(k[1] if isinstance(k, tuple) else k, 0)
        )
        controller = MagicMock()
        controller.pyboy = pyboy
        ctx = MagicMock()
        ctx.game_controller = controller
        ctx.chat_id = 111
        ctx.user_id = 222
        ctx.platform = "test"
        ctx.user_name = "TestUser"
        prefs = {
            "pkpcrystal_avatar_path": "assets/dynamic/pkpcrystal/trainers/42.png",
        }
        def mock_pref(platform, uid, key):
            return prefs.get(key)
        raw = _make_mock_battle_struct(species=25, level=5)
        prefs["pkpcrystal_trainer_card_mon_0"] = raw.hex()
        for i in range(41):
            memory_store[0xC000 + i] = 0x53
        with patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=mock_pref):
            result = await redeem_battle_handler(ctx)
        assert result.success is True
        entry = _resolve_battle_request(111)
        assert entry["trainer_class"] == 42

    @pytest.mark.asyncio
    async def test_redeem_battle_default_class_when_no_avatar(self):
        from src.game_shops.pkpcrystal import redeem_battle_handler
        pyboy = MagicMock()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store = {0xD001: 0, 0xD002: 0, 0xD003: 6}
        pyboy.memory.__getitem__.side_effect = (
            lambda k: memory_store.get(k[1] if isinstance(k, tuple) else k, 0)
        )
        controller = MagicMock()
        controller.pyboy = pyboy
        ctx = MagicMock()
        ctx.game_controller = controller
        ctx.chat_id = 111
        ctx.user_id = 222
        ctx.platform = "test"
        ctx.user_name = "TestUser"
        prefs = {}
        raw = _make_mock_battle_struct(species=25, level=5)
        prefs["pkpcrystal_trainer_card_mon_0"] = raw.hex()
        def mock_pref(platform, uid, key):
            return prefs.get(key)
        with patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=mock_pref):
            result = await redeem_battle_handler(ctx)
        assert result.success is True
        entry = _resolve_battle_request(111)
        assert entry["trainer_class"] == 1

    @pytest.mark.asyncio
    async def test_redeem_battle_skips_invalid_mon_slots(self):
        from src.game_shops.pkpcrystal import redeem_battle_handler
        pyboy = MagicMock()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store = {0xD001: 0, 0xD002: 0, 0xD003: 6}
        pyboy.memory.__getitem__.side_effect = (
            lambda k: memory_store.get(k[1] if isinstance(k, tuple) else k, 0)
        )
        controller = MagicMock()
        controller.pyboy = pyboy
        ctx = MagicMock()
        ctx.game_controller = controller
        ctx.chat_id = 111
        ctx.user_id = 222
        ctx.platform = "test"
        ctx.user_name = "TestUser"
        raw = _make_mock_battle_struct(species=25, level=5)
        prefs = {
            "pkpcrystal_trainer_card_mon_0": "nothex",
            "pkpcrystal_trainer_card_mon_1": raw.hex(),
            "pkpcrystal_trainer_card_mon_2": "00",
            "pkpcrystal_trainer_card_mon_3": "00" * BATTLE_STRUCT_SIZE,
        }
        def mock_pref(platform, uid, key):
            return prefs.get(key)
        with patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=mock_pref):
            result = await redeem_battle_handler(ctx)
        assert result.success is True
        entry = _resolve_battle_request(111)
        assert len(entry["party_mons"]) == 1
        assert entry["party_mons"][0][0] == 25

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
        memory_store = {0xD001: 0, 0xD002: 0, 0xD003: 6}
        pyboy.memory.__getitem__.side_effect = (
            lambda k: memory_store.get(k[1] if isinstance(k, tuple) else k, 0)
        )
        controller = MagicMock()
        controller.pyboy = pyboy
        ctx = MagicMock()
        ctx.game_controller = controller
        ctx.chat_id = 111
        ctx.user_id = 222
        ctx.platform = "test"
        ctx.user_name = "TestUser"
        raw = _make_mock_battle_struct(species=25, level=5)
        prefs = {"pkpcrystal_trainer_card_mon_0": raw.hex()}
        def mock_pref(platform, uid, key):
            return prefs.get(key)
        with patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=mock_pref):
            result = await redeem_battle_handler(ctx)
        assert result.success is True
        entry = _resolve_battle_request(111)
        assert entry is not None
        assert entry["state"] == "pending"
        assert entry["user_id"] == 222
        assert entry["platform"] == "test"
        assert entry["user_name"] == "TestUser"
        assert len(entry["party_mons"]) == 1
        assert entry["party_mons"][0][0] == 25
        assert entry["trainer_name_bytes"][0] == REVERSE_CHARMAP["T"]
        assert entry["trainer_name_bytes"][1] == REVERSE_CHARMAP["e"]


class TestReadPlayerPartyLevels:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _battle_requests.clear()

    def test_reads_party_levels(self):
        pyboy = MagicMock()
        sym_addrs = {
            "wPartyCount": (0, 0xD000),
            "wPartyMon1": (0, 0xD100),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store = {0xD000: 3}

        def memory_getitem(key):
            if isinstance(key, tuple):
                return memory_store.get(key[1], 0)
            return memory_store.get(key, 0)

        pyboy.memory.__getitem__.side_effect = memory_getitem
        memory_store[0xD100 + 0 * 48 + 31] = 5
        memory_store[0xD100 + 1 * 48 + 31] = 10
        memory_store[0xD100 + 2 * 48 + 31] = 15

        result = _read_player_party_levels(pyboy)
        assert result == [5, 10, 15]

    def test_returns_empty_list_when_no_party(self):
        pyboy = MagicMock()
        sym_addrs = {
            "wPartyCount": (0, 0xD000),
            "wPartyMon1": (0, 0xD100),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store = {0xD000: 0}

        def memory_getitem(key):
            if isinstance(key, tuple):
                return memory_store.get(key[1], 0)
            return memory_store.get(key, 0)

        pyboy.memory.__getitem__.side_effect = memory_getitem

        result = _read_player_party_levels(pyboy)
        assert result == []


class TestStatRebalancingIntegration:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _battle_requests.clear()

    def test_rebalancing_applies_before_script_injection(self):
        pyboy, memory_store = _make_mock_pyboy()
        sym_addrs = {
            "wBattleMode": (0, 0xD001),
            "wScriptRunning": (0, 0xD002),
            "wPartyCount": (0, 0xD003),
            "wFootprintQueue": (0, 0xC100),
            "hScriptBank": (0, 0xFFEB),
            "hScriptPos": (0, 0xFFEC),
            "wOtherTrainerClass": (0, 0xD010),
            "wScriptMode": (0, 0xD011),
            "wBattleScriptFlags": (0, 0xD012),
        }
        pyboy.symbol_lookup.side_effect = lambda sym: sym_addrs.get(sym, (0, 0xC000))
        memory_store[0xD001] = 0
        memory_store[0xD002] = 0
        memory_store[0xD003] = 3

        original_mon = bytes(range(48))
        party_mons = [original_mon]

        begin_hooks(pyboy, chat_id=111)
        queue_battle_request(111, 222, "test", "TestUser", 1, [0x80] * 11, party_mons)

        with (
            patch("src.game_hooks.pkpcrystal._read_player_party_levels", return_value=[5, 10, 15]),
            patch("src.game_hooks.pkpcrystal.compute_target_levels", return_value=[20]),
            patch("src.game_hooks.pkpcrystal.recalc_pkmn_stats", return_value=bytes(bytearray(original_mon))),
        ):
            callback = _get_hook_callback(pyboy, "PlayerEvents")
            assert callback is not None
            callback(None)

        assert _battle_requests[111]["state"] == "starting"
