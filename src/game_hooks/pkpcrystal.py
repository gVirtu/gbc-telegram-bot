"""Hooks for Polished Crystal (PKPCRYSTAL).

Provides game-specific hooks for:
- Blocking dangerous actions (releasing Pokemon, tossing items)
- Detecting input wait loops for early animation termination
"""

import logging
from collections import defaultdict
import random

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
        
    register_custom_hooks(pyboy)

    def register_battle_hooks(pyboy, chat_id):
        def hook_a_callback(ctx):
            req = _resolve_battle_request(chat_id)
            if req is None or req["state"] != "pending":
                return
            try:
                mode = pyboy.memory[pyboy.symbol_lookup("wBattleMode")]
                script = pyboy.memory[pyboy.symbol_lookup("wScriptRunning")]
                party = pyboy.memory[pyboy.symbol_lookup("wPartyCount")]
            except (ValueError, TypeError) as exc:
                logger.warning("PlayerEvents hook: symbol lookup failed: %s", exc)
                return
            if mode != 0 or script != 0 or party == 0:
                return
            try:
                player_level = pyboy.memory[pyboy.symbol_lookup("wPartyMon1Level")]
            except (ValueError, TypeError) as exc:
                logger.warning("PlayerEvents hook: could not read wPartyMon1Level: %s", exc)
                return
            req["level"] = player_level
            try:
                _bank, fq_addr = pyboy.symbol_lookup("wFootprintQueue")
                script_addr = fq_addr + 7
            except (ValueError, TypeError) as exc:
                logger.warning("PlayerEvents hook: could not find wFootprintQueue: %s", exc)
                return
            pyboy.memory[(0, script_addr)] = SCRIPT_STARTBATTLE
            pyboy.memory[(0, script_addr + 1)] = SCRIPT_RELOADMAP
            pyboy.memory[(0, script_addr + 2)] = SCRIPT_END
            far_addr = script_addr + 3
            try:
                _bank, win_text_addr = pyboy.symbol_lookup("YoungsterGordonBeatenText")
            except (ValueError, TypeError) as exc:
                logger.warning("PlayerEvents hook: could not find YoungsterGordonBeatenText: %s", exc)
                return
            pyboy.memory[(0, far_addr)] = TEXT_FAR
            pyboy.memory[(0, far_addr + 1)] = win_text_addr & 0xFF
            pyboy.memory[(0, far_addr + 2)] = (win_text_addr >> 8) & 0xFF
            pyboy.memory[(0, far_addr + 3)] = _bank
            pyboy.memory[(0, far_addr + 4)] = TEXT_TERM
            try:
                _bank, hb_addr = pyboy.symbol_lookup("hScriptBank")
                _bank, hp_addr = pyboy.symbol_lookup("hScriptPos")
            except (ValueError, TypeError) as exc:
                logger.warning("PlayerEvents hook: could not find HRAM symbols: %s", exc)
                return
            try:
                _bank, win_ptr_addr = pyboy.symbol_lookup("wWinTextPointer")
            except (ValueError, TypeError) as exc:
                logger.warning("PlayerEvents hook: could not find wWinTextPointer: %s", exc)
                return
            old_svbk = pyboy.memory[0xFF70]
            pyboy.memory[0xFF70] = 1
            far_low = far_addr & 0xFF
            far_high = (far_addr >> 8) & 0xFF
            pyboy.memory[(_bank, win_ptr_addr)] = far_low
            pyboy.memory[(_bank, win_ptr_addr + 1)] = far_high
            pyboy.memory[(_bank, win_ptr_addr + 2)] = far_low
            pyboy.memory[(_bank, win_ptr_addr + 3)] = far_high
            pyboy.memory[0xFF70] = old_svbk
            pyboy.memory[hb_addr] = 0
            pyboy.memory[hp_addr] = script_addr & 0xFF
            pyboy.memory[hp_addr + 1] = (script_addr >> 8) & 0xFF
            pyboy.memory[pyboy.symbol_lookup("wScriptRunning")] = 1
            pyboy.memory[pyboy.symbol_lookup("wScriptMode")] = 1
            pyboy.memory[pyboy.symbol_lookup("wOtherTrainerClass")] = 1
            pyboy.memory[pyboy.symbol_lookup("wOtherTrainerID")] = 1
            pyboy.memory[pyboy.symbol_lookup("wTrainerPal")] = 0
            pyboy.memory[pyboy.symbol_lookup("wBattleScriptFlags")] = 0x81
            req["state"] = "starting"
            logger.info("PlayerEvents: injected battle script for chat %s", chat_id)

        def hook_b_callback(ctx):
            req = _resolve_battle_request(chat_id)
            if req is None or req["state"] != "starting":
                return
            level = req.get("level", 10)
            dummy_mon = _build_dummy_party_mon(level)
            old_svbk = pyboy.memory[0xFF70]
            pyboy.memory[0xFF70] = 1
            try:
                pyboy.memory[pyboy.symbol_lookup("wOTPartyCount")] = 1
                _bank, ot_mon_addr = pyboy.symbol_lookup("wOTPartyMon1")
                for i, b in enumerate(dummy_mon):
                    pyboy.memory[(_bank, ot_mon_addr + i)] = b
                _bank, nick_addr = pyboy.symbol_lookup("wOTPartyMonNicknames")
                ditto_name = [0x83, 0x88, 0x93, 0x93, 0x8e]
                for i, c in enumerate(ditto_name):
                    pyboy.memory[(_bank, nick_addr + i)] = c
                pyboy.memory[(_bank, nick_addr + len(ditto_name))] = 0x53
                for i in range(len(ditto_name) + 1, 11):
                    pyboy.memory[(_bank, nick_addr + i)] = 0x53
                pyboy.memory[pyboy.symbol_lookup("wCurPartySpecies")] = DITTO
                pyboy.memory[pyboy.symbol_lookup("wCurPartyLevel")] = level
                pyboy.memory[pyboy.symbol_lookup("wCurForm")] = 0
                pyboy.memory[pyboy.symbol_lookup("wMonType")] = 1
                pyboy.memory[pyboy.symbol_lookup("wOtherTrainerType")] = 0
                _bank, ai_addr = pyboy.symbol_lookup("wEnemyTrainerAIFlags")
                pyboy.memory[(_bank, ai_addr)] = 0
                pyboy.memory[(_bank, ai_addr + 1)] = 0
                pyboy.memory[(_bank, ai_addr + 2)] = 0
                _bank, reward_addr = pyboy.symbol_lookup("wBattleReward")
                pyboy.memory[(_bank, reward_addr)] = 0
                pyboy.memory[(_bank, reward_addr + 1)] = 0
                pyboy.memory[(_bank, reward_addr + 2)] = 0
            except (ValueError, TypeError) as exc:
                logger.warning("Hook B: symbol lookup failed: %s", exc)
                pyboy.memory[0xFF70] = old_svbk
                return
            pyboy.memory[0xFF70] = old_svbk
            _remove_battle_request(chat_id)
            logger.info("Hook B: wrote custom team for chat %s", chat_id)

        try:
            pyboy.hook_register(None, "PlayerEvents", hook_a_callback, None)
            pyboy.hook_register(None, "ComputeTrainerReward", hook_b_callback, None)
            logger.info("Registered battle hooks for chat %s", chat_id)
        except (ValueError, TypeError) as exc:
            logger.warning("Could not register battle hooks: %s", exc)

    register_battle_hooks(pyboy, chat_id)

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
    
    for sym in ("PlayerEvents", "ComputeTrainerReward"):
        try:
            pyboy.hook_deregister(None, sym)
        except (ValueError, TypeError):
            pass
    

def register_custom_hooks(pyboy):
    register_check_phone_call_hook(pyboy)


def deregister_custom_hooks(pyboy):
    deregister_check_phone_call_hook(pyboy)


def register_check_phone_call_hook(pyboy):
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
