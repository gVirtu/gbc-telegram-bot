"""Hooks for Polished Crystal (PKPCRYSTAL).

Provides game-specific hooks for:
- Blocking dangerous actions (releasing Pokemon, tossing items)
- Detecting input wait loops for early animation termination
"""

import logging
from collections import defaultdict
import random

from src.game_utils.pkpcrystal.reader import symbol_read_u8
from src.game_utils.pkpcrystal.writer import (
    symbol_write_u8,
    write_u8,
    write_u8_wram0,
    write_u16le,
    write_u16le_wram0,
    write_bytes,
    wramx_bank,
)

_battle_requests: dict[int, dict] = {}

def queue_battle_request(chat_id: int, user_id: int) -> None:
    _battle_requests[chat_id] = {"state": "pending", "user_id": user_id}

def _resolve_battle_request(chat_id: int) -> dict | None:
    return _battle_requests.get(chat_id)

def _remove_battle_request(chat_id: int) -> None:
    _battle_requests.pop(chat_id, None)


DITTO = 0x84
PARTYMON_STRUCT_LENGTH = 48
MON_LEVEL = 31
TRANSFORM_MOVE_ID = 0x90
SCRIPT_STARTBATTLE = 0x5E
SCRIPT_RELOADMAP = 0x5F
SCRIPT_END = 0x8F
TEXT_FAR = 0x08
TEXT_TERM = 0x53
FOOTPRINT_QUEUE_SIZE = 7


def _build_dummy_party_mon(level: int) -> bytes:
    buf = bytearray(48)
    buf[0] = DITTO
    buf[2] = TRANSFORM_MOVE_ID
    buf[17] = 0xFF
    buf[18] = 0xFF
    buf[19] = 0xFF
    buf[MON_LEVEL] = level
    hp = (2 * 48 + 15 + 0) * level // 100 + level + 10
    buf[34] = (hp >> 8) & 0xFF
    buf[35] = hp & 0xFF
    buf[36] = (hp >> 8) & 0xFF
    buf[37] = hp & 0xFF
    return bytes(buf)


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
            player_level = symbol_read_u8(pyboy, "wPartyMon1Level")
        except (ValueError, TypeError) as exc:
            logger.warning("PlayerEvents hook: could not read wPartyMon1Level: %s", exc)
            return
        req["level"] = player_level
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
        symbol_write_u8(pyboy, "wOtherTrainerClass", 1)
        symbol_write_u8(pyboy, "wOtherTrainerID", 1)
        symbol_write_u8(pyboy, "wTrainerPal", 0)
        symbol_write_u8(pyboy, "wBattleScriptFlags", 0x81)
        req["state"] = "starting"
        logger.info("PlayerEvents: injected battle script for chat %s", chat_id)

    def compute_trainer_reward_callback(ctx):
        req = _resolve_battle_request(chat_id)
        if req is None or req["state"] != "starting":
            return
        level = req.get("level", 10)
        dummy_mon = _build_dummy_party_mon(level)
        with wramx_bank(pyboy):
            try:
                symbol_write_u8(pyboy, "wOTPartyCount", 1)
                _bank, ot_mon_addr = pyboy.symbol_lookup("wOTPartyMon1")
                write_bytes(pyboy, _bank, ot_mon_addr, dummy_mon)
                _bank, nick_addr = pyboy.symbol_lookup("wOTPartyMonNicknames")
                ditto_name = [0x83, 0x88, 0x93, 0x93, 0x8e]
                name_data = ditto_name + [0x53] + [0x53] * (10 - len(ditto_name))
                write_bytes(pyboy, _bank, nick_addr, bytes(name_data))
                symbol_write_u8(pyboy, "wCurPartySpecies", DITTO)
                symbol_write_u8(pyboy, "wCurPartyLevel", level)
                symbol_write_u8(pyboy, "wCurForm", 0)
                symbol_write_u8(pyboy, "wMonType", 1)
                symbol_write_u8(pyboy, "wOtherTrainerType", 0)
                _bank, ai_addr = pyboy.symbol_lookup("wEnemyTrainerAIFlags")
                write_bytes(pyboy, _bank, ai_addr, bytes([0, 0, 0]))
                _bank, reward_addr = pyboy.symbol_lookup("wBattleReward")
                write_bytes(pyboy, _bank, reward_addr, bytes([0, 0, 0]))
            except (ValueError, TypeError) as exc:
                logger.warning("ComputeTrainerReward hook: symbol lookup failed: %s", exc)
                return
        _remove_battle_request(chat_id)
        logger.info("ComputeTrainerReward: wrote custom team for chat %s", chat_id)

    try:
        pyboy.hook_register(None, "PlayerEvents", player_events_callback, None)
        pyboy.hook_register(None, "ComputeTrainerReward", compute_trainer_reward_callback, None)
        logger.info("Registered battle hooks for chat %s", chat_id)
    except (ValueError, TypeError) as exc:
        logger.warning("Could not register battle hooks: %s", exc)


def register_custom_hooks(pyboy, chat_id):
    _register_check_phone_call_hook(pyboy)
    _register_battle_hooks(pyboy, chat_id)


def deregister_custom_hooks(pyboy):
    deregister_check_phone_call_hook(pyboy)
    for sym in ("PlayerEvents", "ComputeTrainerReward"):
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
