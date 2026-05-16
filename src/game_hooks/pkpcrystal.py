"""Hooks for Polished Crystal (PKPCRYSTAL).

Provides game-specific hooks for:
- Blocking dangerous actions (releasing Pokemon, tossing items)
- Detecting input wait loops for early animation termination
"""

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def begin_hooks(pyboy) -> dict:
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
