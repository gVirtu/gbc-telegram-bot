"""Hooks for Polished Crystal (PKPCRYSTAL).

Provides game-specific hooks for:
- Blocking dangerous actions (releasing Pokemon, tossing items)
- Detecting input wait loops for early animation termination
"""

import logging
from collections import defaultdict
import random

from src.game_utils.pkpcrystal.reader import symbol_read_u8, get_pokemon_name
from src.game_utils.pkpcrystal.charmap import encode_name, MON_NAME_LENGTH
from src.game_utils.pkpcrystal.writer import (
    symbol_write_u8,
    write_u8,
    write_u8_wram0,
    write_u16le,
    write_u16le_wram0,
    write_bytes,
    wramx_bank,
)
from src.game_utils.pkpcrystal.party_builder import PARTY_STRUCT_SIZE, B_SPECIES, P_LEVEL

_battle_requests: dict[int, dict] = {}

def queue_battle_request(chat_id: int, user_id: int, platform: str, user_name: str, trainer_class: int, trainer_name_bytes: list[int], party_mons: list[bytes]) -> None:
    _battle_requests[chat_id] = {
        "state": "pending",
        "user_id": user_id,
        "platform": platform,
        "user_name": user_name,
        "trainer_class": trainer_class,
        "trainer_name_bytes": trainer_name_bytes,
        "party_mons": party_mons,
    }

def _resolve_battle_request(chat_id: int) -> dict | None:
    return _battle_requests.get(chat_id)

def _remove_battle_request(chat_id: int) -> None:
    _battle_requests.pop(chat_id, None)


PARTYMON_STRUCT_LENGTH = 48
MON_LEVEL = 31
SCRIPT_STARTBATTLE = 0x5E
SCRIPT_RELOADMAP = 0x5F
SCRIPT_END = 0x8F
TEXT_FAR = 0x08
TEXT_TERM = 0x53
FOOTPRINT_QUEUE_SIZE = 7
OT_NAME_ENTRY_SIZE = 11


logger = logging.getLogger(__name__)


def begin_hooks(pyboy, chat_id) -> dict:
    """Register Polished Crystal hooks.

    Args:
        pyboy: PyBoy emulator instance

    Returns:
        Context dict with counters for dangerous actions and input wait calls
    """
    context = {
        "dangerousActions": {
            "TossMenu": 0,
            "BillsPC_Release": 0,
            "BillsPC_ReleaseAll": 0,
            "_total": 0
        },
        "inputWaitCalls": {
            "DoPlayerMovement.GetAction": 0,
            "JoyWaitAorB": 0,
            "WaitButton": 0,
            "WaitPressAorB_BlinkCursor": 0,
            "ButtonSound.input_wait_loop": 0,
            "Do2DMenuRTCJoypad_loop": 0,
            "SummaryScreenLoop": 0,
            "NamingScreenJoypadLoop": 0,
            "MenuJoypadLoop.loop": 0,
            "Toss_Sell_Loop.loop": 0,
            "MoveScreenLoop.loop": 0,
            "PokeGear.loop": 0,
            "ManageBoxes.loop": 0,
            "UnownPuzzle.loop": 0,
            "Pokedex_MainLoop.loop": 0,
            "_Pokedex_Area.joypad_loop": 0,
            "_Pokedex_Description.joypad_loop": 0,
            "_Pokedex_Description.newdesc_joypad": 0,
            "Pokedex_Bio.joypad_loop": 0,
            "_Pokedex_Stats.joypad_loop": 0,
            "_Pokedex_Mode.joypad_loop": 0,
            "_Pokedex_Search.joypad_loop": 0,
            "_Pokedex_Unown.joypad_loop": 0,
            "OptionsMenu.joypad_loop": 0,
            "_total": 0
        },
        "autoPressA": {
            "JoyWaitAorB": 0,
            "ButtonSound.input_wait_loop": 0,
            "WaitPressAorB_BlinkCursor": 0,
            "WaitPressAorB_BlinkCursor.loop": 0,
            "BattleIntroSlidingPics.loop2": 0,
            "_AnimateHPBar.loop": 0,
            "RunBattleAnimScript.playframe": 0,
            "HealMachineAnim.party_loop": 0,
            "HealMachineAnim.palette_loop": 0,
            "_total": 0
        }
    }
    
    weights = {
        "DoPlayerMovement.GetAction": 3,
        "SummaryScreenLoop": 2,
        "MenuJoypadLoop.loop": 10,
        "Pokedex_MainLoop.loop": 10,
        "_Pokedex_Area.joypad_loop": 10,
        "_Pokedex_Description.joypad_loop": 10,
        "_Pokedex_Description.newdesc_joypad": 10,
        "Pokedex_Bio.joypad_loop": 10,
        "_Pokedex_Stats.joypad_loop": 10,
        "_Pokedex_Mode.joypad_loop": 10,
        "_Pokedex_Search.joypad_loop": 10,
        "_Pokedex_Unown.joypad_loop": 10,
        "OptionsMenu.joypad_loop": 10,
    }
    
    # Aggregate all actions linked to what categories they are in
    hook_counters = defaultdict(list)
    
    for counter_category in context.keys():
        for action in context[counter_category].keys():
            if action == '_total':
                continue
            hook_counters[action].append(counter_category)

    def make_hook(categories: list, action: str):
        sub_dicts = [context[cat] for cat in categories]
        weight = weights.get(action, 1)
        def hook(ctx):
            for d in sub_dicts:
                d[action] += weight
                d["_total"] += weight
        return hook

    for action in hook_counters.keys():
        pyboy.hook_register(None, action, make_hook(hook_counters[action], action), context)
        
    register_custom_hooks(pyboy, chat_id)

    return context


def end_hooks(pyboy, context: dict) -> None:
    """Deregister Polished Crystal hooks.

    Args:
        pyboy: PyBoy emulator instance
        context: Context dict from begin_hooks
    """

    actions = set()
    for counter_category in context.keys():
        for action in context[counter_category].keys():
            actions.add(action)
            
    for action in actions:
        if action == '_total':
            continue
        pyboy.hook_deregister(None, action)
        
    deregister_custom_hooks(pyboy)


def _register_battle_hooks(pyboy, chat_id):
    def player_events_callback(ctx):
        req = _resolve_battle_request(chat_id)
        if req is None or req["state"] != "pending":
            return
        try:
            mode = symbol_read_u8(pyboy, "wBattleMode")
            script = symbol_read_u8(pyboy, "wScriptRunning")
            party = symbol_read_u8(pyboy, "wPartyCount")
        except (ValueError, TypeError) as exc:
            logger.warning("PlayerEvents hook: symbol lookup failed: %s", exc)
            return
        if mode != 0 or script != 0 or party == 0:
            return
        try:
            _bank, fq_addr = pyboy.symbol_lookup("wFootprintQueue")
            script_addr = fq_addr + FOOTPRINT_QUEUE_SIZE
        except (ValueError, TypeError) as exc:
            logger.warning("PlayerEvents hook: could not find wFootprintQueue: %s", exc)
            return
        write_bytes(pyboy, 0, script_addr, bytes([SCRIPT_STARTBATTLE, SCRIPT_RELOADMAP, SCRIPT_END]))
        far_addr = script_addr + 3
        try:
            _bank, win_text_addr = pyboy.symbol_lookup("YoungsterGordonBeatenText")
        except (ValueError, TypeError) as exc:
            logger.warning("PlayerEvents hook: could not find YoungsterGordonBeatenText: %s", exc)
            return
        write_bytes(pyboy, 0, far_addr, bytes([
            TEXT_FAR,
            win_text_addr & 0xFF,
            (win_text_addr >> 8) & 0xFF,
            _bank,
            TEXT_TERM,
        ]))
        try:
            _bank, hb_addr = pyboy.symbol_lookup("hScriptBank")
            _, hp_addr = pyboy.symbol_lookup("hScriptPos")
        except (ValueError, TypeError) as exc:
            logger.warning("PlayerEvents hook: could not find HRAM symbols: %s", exc)
            return
        try:
            _bank, win_ptr_addr = pyboy.symbol_lookup("wWinTextPointer")
        except (ValueError, TypeError) as exc:
            logger.warning("PlayerEvents hook: could not find wWinTextPointer: %s", exc)
            return
        with wramx_bank(pyboy):
            write_bytes(pyboy, _bank, win_ptr_addr, bytes([
                far_addr & 0xFF,
                (far_addr >> 8) & 0xFF,
                far_addr & 0xFF,
                (far_addr >> 8) & 0xFF,
            ]))
        write_u8_wram0(pyboy, hb_addr, 0)
        write_u16le_wram0(pyboy, hp_addr, script_addr)
        symbol_write_u8(pyboy, "wScriptRunning", 1)
        symbol_write_u8(pyboy, "wScriptMode", 1)
        symbol_write_u8(pyboy, "wOtherTrainerClass", req.get("trainer_class", 1))
        symbol_write_u8(pyboy, "wOtherTrainerID", 0)
        symbol_write_u8(pyboy, "wTrainerPal", 0)
        symbol_write_u8(pyboy, "wBattleScriptFlags", 0x81)
        req["state"] = "starting"
        logger.info("PlayerEvents: injected battle script for chat %s", chat_id)

    def compute_trainer_reward_callback(ctx):
        req = _resolve_battle_request(chat_id)
        if req is None or req["state"] != "starting":
            return
        party_mons = req.get("party_mons", [])
        if not party_mons:
            return
        with wramx_bank(pyboy):
            try:
                _bank, ot_mons_base = pyboy.symbol_lookup("wOTPartyMons")
                _bank, ot_ots_base = pyboy.symbol_lookup("wOTPartyMonOTs")
                _bank, ot_nicks_base = pyboy.symbol_lookup("wOTPartyMonNicknames")
                count = len(party_mons)
                symbol_write_u8(pyboy, "wOTPartyCount", count)
                for i, mon in enumerate(party_mons):
                    mon_addr = ot_mons_base + i * PARTY_STRUCT_SIZE
                    write_bytes(pyboy, _bank, mon_addr, mon)
                    ot_addr = ot_ots_base + i * OT_NAME_ENTRY_SIZE
                    write_bytes(pyboy, _bank, ot_addr, bytes([0x53] * OT_NAME_ENTRY_SIZE))
                    nick_addr = ot_nicks_base + i * MON_NAME_LENGTH
                    species = mon[B_SPECIES]
                    species_name = get_pokemon_name(pyboy, species)
                    nickname_bytes = encode_name(species_name, max_len=MON_NAME_LENGTH)
                    write_bytes(pyboy, _bank, nick_addr, bytes(nickname_bytes))
                first_mon = party_mons[0]
                symbol_write_u8(pyboy, "wCurPartySpecies", first_mon[B_SPECIES])
                symbol_write_u8(pyboy, "wCurPartyLevel", first_mon[P_LEVEL])
                symbol_write_u8(pyboy, "wCurForm", 0)
                symbol_write_u8(pyboy, "wMonType", 1)
                symbol_write_u8(pyboy, "wOtherTrainerType", 0)
                _bank, ai_addr = pyboy.symbol_lookup("wEnemyTrainerAIFlags")
                write_bytes(pyboy, _bank, ai_addr, bytes([0, 0, 0]))
                _bank, reward_addr = pyboy.symbol_lookup("wBattleReward")
                write_bytes(pyboy, _bank, reward_addr, bytes([0, 0, 0]))
                symbol_write_u8(pyboy, "wInBattleTowerBattle", 1)
                name_bytes = req.get("trainer_name_bytes", [])
                if name_bytes:
                    _bank, ot_name_addr = pyboy.symbol_lookup("wOTPlayerName")
                    write_bytes(pyboy, _bank, ot_name_addr, bytes(name_bytes))
            except (ValueError, TypeError) as exc:
                logger.warning("ComputeTrainerReward hook: symbol lookup failed: %s", exc)
                return
        _remove_battle_request(chat_id)
        logger.info("ComputeTrainerReward: wrote custom team (%d mons) for chat %s", count, chat_id)

    def reloadmap_after_battle_callback(ctx):
        symbol_write_u8(pyboy, "wInBattleTowerBattle", 0)

    try:
        pyboy.hook_register(None, "PlayerEvents", player_events_callback, None)
        pyboy.hook_register(None, "ComputeTrainerReward", compute_trainer_reward_callback, None)
        pyboy.hook_register(None, "Script_reloadmapafterbattle", reloadmap_after_battle_callback, None)
        logger.info("Registered battle hooks for chat %s", chat_id)
    except (ValueError, TypeError) as exc:
        logger.warning("Could not register battle hooks: %s", exc)


def register_custom_hooks(pyboy, chat_id):
    _register_check_phone_call_hook(pyboy)
    _register_battle_hooks(pyboy, chat_id)


def deregister_custom_hooks(pyboy):
    deregister_check_phone_call_hook(pyboy)
    for sym in ("PlayerEvents", "ComputeTrainerReward", "Script_reloadmapafterbattle"):
        try:
            pyboy.hook_deregister(None, sym)
        except (ValueError, TypeError):
            pass


def _register_check_phone_call_hook(pyboy):
    """Hook CheckPhoneCall to skip random unsolicited Pokegear calls.

    CheckPhoneCall (phone.asm:39, bank $24) is the sole entry point for
    random Pokegear calls. It runs during overworld step processing
    (CheckTimeEvents -> PlayerEvents). Scripted/story calls (Elm egg,
    Bill, Lyra badges, Mom worried, etc.) use the completely separate
    CheckSpecialPhoneCall function, called from CountStep instead.

    The hook fires at the CheckPhoneCall entry and redirects PC to the
    .no_call label, which does xor a; ret (return nc = no call).

    The farcall mechanism (rst FarCall) manages the stack + bank switch,
    so a clean ret from .no_call returns to PlayerEvents via the farcall
    return stub and CheckTimeEvents's ret c fallthrough.

    Does NOT affect:
    - CheckSpecialPhoneCall (scripted/story calls)
    - MomTriesToBuySomething (automated Mom shopping)
    - MakePhoneCallFromPokegear (player-initiated calls from Pokegear UI)
    """
    try:
        _bank, check_addr = pyboy.symbol_lookup("CheckPhoneCall")
        _bank, no_call_addr = pyboy.symbol_lookup("CheckPhoneCall.no_call")
        skip_chance = 0.9

        def skip_check_phone_call(_ctx):
            if random.random() < skip_chance:
                pyboy.register_file.PC = no_call_addr

        pyboy.hook_register(None, "CheckPhoneCall", skip_check_phone_call, None)
    except (ValueError, TypeError) as exc:
        logger.warning("Could not hook into CheckPhoneCall: %s", exc)
        

def deregister_check_phone_call_hook(pyboy):
    try:
        pyboy.hook_deregister(None, "CheckPhoneCall")
    except (ValueError, TypeError):
        pass
