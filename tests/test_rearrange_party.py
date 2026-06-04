"""Tests for the rearrange_party shop handler."""

import pytest
from unittest.mock import MagicMock, patch

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


class TestRearrangePartyHandler:
    @pytest.mark.asyncio
    async def test_no_game_controller(self):
        from src.game_shops.pkpcrystal import rearrange_party_handler
        ctx = MagicMock()
        ctx.game_controller = None
        ctx.user_id = 1
        ctx.chat_id = 99
        result = await rearrange_party_handler(ctx)
        assert result.success is False
        assert "no_game_controller" in result.error_message

    @pytest.mark.asyncio
    async def test_no_party_mons(self):
        from src.game_shops.pkpcrystal import rearrange_party_handler
        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)
        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.session = session
        with patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", return_value=None):
            result = await rearrange_party_handler(ctx)
        assert result.success is False
        assert "no_party_mons" in result.error_message

    @pytest.mark.asyncio
    async def test_single_mon_returns_selection_step(self):
        from src.game_shops.pkpcrystal import rearrange_party_handler
        raw = _make_mock_battle_struct(species=0x19, level=25)  # Pikachu
        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.session = session

        def mock_pref(platform, uid, key):
            if key == "pkpcrystal_trainer_card_mon_0":
                return raw.hex()
            if key == "pkpcrystal_trainer_card_mon_0_species":
                return "25"
            return None

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=mock_pref),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Pikachu"),
        ):
            result = await rearrange_party_handler(ctx)

        assert isinstance(result, SelectionStep)
        assert len(result.options) == 6
        assert "rearrange_party_select_position" in result.prompt

    @pytest.mark.asyncio
    async def test_two_mons_first_step_has_all_six_options(self):
        from src.game_shops.pkpcrystal import rearrange_party_handler
        raw0 = _make_mock_battle_struct(species=0x19, level=25)
        raw2 = _make_mock_battle_struct(species=0x04, level=18)
        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.session = session

        def mock_pref(platform, uid, key):
            if key == "pkpcrystal_trainer_card_mon_0":
                return raw0.hex()
            if key == "pkpcrystal_trainer_card_mon_0_species":
                return "25"
            if key == "pkpcrystal_trainer_card_mon_2":
                return raw2.hex()
            if key == "pkpcrystal_trainer_card_mon_2_species":
                return "4"
            return None

        species_names = {25: "Pikachu", 4: "Charmander"}

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=mock_pref),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", side_effect=lambda p, s: species_names.get(s, f"Species{s}")),
        ):
            result = await rearrange_party_handler(ctx)

        assert isinstance(result, SelectionStep)
        assert len(result.options) == 6
        assert len(session.state["rearrange_mons"]) == 2
        assert session.state["rearrange_current_index"] == 0
        assert session.state["rearrange_assignments"] == {}
        assert session.state["rearrange_taken_slots"] == set()

    @pytest.mark.asyncio
    async def test_bogus_hex_skipped(self):
        from src.game_shops.pkpcrystal import rearrange_party_handler
        raw = _make_mock_battle_struct(species=0x19, level=25)
        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)

        ctx = MagicMock()
        ctx.game_controller = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.session = session

        def mock_pref(platform, uid, key):
            if key == "pkpcrystal_trainer_card_mon_0":
                return "notvalidhex"  # bogus, should skip
            if key == "pkpcrystal_trainer_card_mon_1":
                return raw.hex()
            if key == "pkpcrystal_trainer_card_mon_1_species":
                return "25"
            return None

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", side_effect=mock_pref),
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Pikachu"),
        ):
            result = await rearrange_party_handler(ctx)

        assert isinstance(result, SelectionStep)
        assert len(session.state["rearrange_mons"]) == 1
        assert session.state["rearrange_mons"][0][0] == 1


class TestOnSelectRearrangePosition:
    @pytest.mark.asyncio
    async def test_chains_to_next_step_when_more_mons_remain(self):
        from src.game_shops.pkpcrystal import _on_select_rearrange_position
        raw0 = _make_mock_battle_struct(species=0x19, level=25)
        raw1 = _make_mock_battle_struct(species=0x04, level=18)
        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)
        session.state = {
            "rearrange_mons": [
                (0, "Pikachu", raw0.hex(), "25"),
                (1, "Charmander", raw1.hex(), "4"),
            ],
            "rearrange_current_index": 0,
            "rearrange_assignments": {},
            "rearrange_taken_slots": set(),
        }

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.get_pokemon_name", return_value="Charmander"),
        ):
            result = await _on_select_rearrange_position("3", ctx)

        assert isinstance(result, SelectionStep)
        assert len(result.options) == 5
        assert 3 not in {int(opt.value) for opt in result.options}
        assert session.state["rearrange_current_index"] == 1
        assert session.state["rearrange_assignments"] == {0: 3}
        assert session.state["rearrange_taken_slots"] == {3}

    @pytest.mark.asyncio
    async def test_finalizes_when_all_mons_assigned(self):
        from src.game_shops.pkpcrystal import _on_select_rearrange_position
        raw0 = _make_mock_battle_struct(species=0x19, level=25)
        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)
        session.state = {
            "rearrange_mons": [
                (0, "Pikachu", raw0.hex(), "25"),
            ],
            "rearrange_current_index": 0,
            "rearrange_assignments": {},
            "rearrange_taken_slots": set(),
        }

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.session = session
        ctx.game_controller = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager.get_user_preference", return_value="25"),
            patch("src.game_shops.pkpcrystal._finalize_rearrange_party") as mock_finalize,
        ):
            mock_finalize.return_value = PurchaseComplete(success=True)
            result = await _on_select_rearrange_position("5", ctx)

        assert result.success is True
        mock_finalize.assert_called_once()
        assert session.state["rearrange_current_index"] == 1


class TestFinalizeRearrangeParty:
    @pytest.mark.asyncio
    async def test_batch_writes_and_deducts(self):
        from src.game_shops.pkpcrystal import _finalize_rearrange_party
        raw0 = _make_mock_battle_struct(species=0x19, level=25)
        raw2 = _make_mock_battle_struct(species=0x04, level=18)
        raw4 = _make_mock_battle_struct(species=0x96, level=30)

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)
        session.state = {
            "rearrange_mons": [
                (0, "Pikachu", raw0.hex(), "25"),
                (2, "Charmander", raw2.hex(), "4"),
                (4, "Jolteon", raw4.hex(), "150"),
            ],
            "rearrange_current_index": 3,
            "rearrange_assignments": {0: 3, 2: 0, 4: 5},
            "rearrange_taken_slots": {0, 3, 5},
        }

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.session = session
        ctx.game_controller = MagicMock()
        ctx.item = MagicMock()
        ctx.user_name = "TestUser"

        mock_conn = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager") as mock_sm,
            patch("src.game_shops.pkpcrystal.shop_manager.purchase", return_value=MagicMock(success=True)),
        ):
            mock_sm.connection = mock_conn

            result = await _finalize_rearrange_party(ctx)

        assert result.success is True
        assert "rearrange_party_complete" in result.success_message

        delete_calls = mock_sm.delete_user_preference.call_args_list
        assert len(delete_calls) == 12

        deleted_keys = {c[0][2] for c in delete_calls}
        for slot in range(6):
            assert f"pkpcrystal_trainer_card_mon_{slot}" in deleted_keys
            assert f"pkpcrystal_trainer_card_mon_{slot}_species" in deleted_keys

        write_calls = mock_sm.set_user_preference.call_args_list
        assert len(write_calls) == 6

        write_by_key = {c[0][2]: c[0][3] for c in write_calls}
        assert write_by_key["pkpcrystal_trainer_card_mon_3"] == raw0.hex()
        assert write_by_key["pkpcrystal_trainer_card_mon_3_species"] == "25"
        assert write_by_key["pkpcrystal_trainer_card_mon_0"] == raw2.hex()
        assert write_by_key["pkpcrystal_trainer_card_mon_0_species"] == "4"
        assert write_by_key["pkpcrystal_trainer_card_mon_5"] == raw4.hex()
        assert write_by_key["pkpcrystal_trainer_card_mon_5_species"] == "150"

        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_on_write_failure(self):
        from src.game_shops.pkpcrystal import _finalize_rearrange_party
        raw0 = _make_mock_battle_struct(species=0x19, level=25)

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)
        session.state = {
            "rearrange_mons": [
                (0, "Pikachu", raw0.hex(), "25"),
            ],
            "rearrange_current_index": 1,
            "rearrange_assignments": {0: 2},
            "rearrange_taken_slots": {2},
        }

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.session = session
        ctx.game_controller = MagicMock()
        ctx.item = MagicMock()
        ctx.user_name = "TestUser"

        mock_conn = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager") as mock_sm,
            patch("src.game_shops.pkpcrystal.shop_manager.purchase", return_value=MagicMock(success=True)),
        ):
            mock_sm.connection = mock_conn
            mock_sm.set_user_preference.side_effect = RuntimeError("DB write failed")

            with pytest.raises(RuntimeError, match="DB write failed"):
                await _finalize_rearrange_party(ctx)

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_honors_non_consecutive_assignments(self):
        from src.game_shops.pkpcrystal import _finalize_rearrange_party
        raw0 = _make_mock_battle_struct(species=0x19, level=25)
        raw2 = _make_mock_battle_struct(species=0x04, level=18)

        session = FlowSession(item=MagicMock(), cat_id="pkpc_battles", cat_page=0, chat_id=99)
        session.state = {
            "rearrange_mons": [
                (0, "Pikachu", raw0.hex(), "25"),
                (2, "Charmander", raw2.hex(), "4"),
            ],
            "rearrange_current_index": 2,
            "rearrange_assignments": {0: 4, 2: 1},
            "rearrange_taken_slots": {1, 4},
        }

        ctx = MagicMock()
        ctx.platform = "test"
        ctx.user_id = 1
        ctx.chat_id = 99
        ctx.session = session
        ctx.game_controller = MagicMock()
        ctx.item = MagicMock()
        ctx.user_name = "TestUser"

        mock_conn = MagicMock()

        with (
            patch("src.game_shops.pkpcrystal.state_manager") as mock_sm,
            patch("src.game_shops.pkpcrystal.shop_manager.purchase", return_value=MagicMock(success=True)),
        ):
            mock_sm.connection = mock_conn

            result = await _finalize_rearrange_party(ctx)

        assert result.success is True

        delete_calls = mock_sm.delete_user_preference.call_args_list
        assert len(delete_calls) == 12

        write_calls = mock_sm.set_user_preference.call_args_list
        assert len(write_calls) == 4

        write_by_key = {c[0][2]: c[0][3] for c in write_calls}

        assert write_by_key["pkpcrystal_trainer_card_mon_4"] == raw0.hex()
        assert write_by_key["pkpcrystal_trainer_card_mon_1"] == raw2.hex()
