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
            "_total": 0
        }
    }
    
    # Aggregate all actions linked to what categories they are in
    hook_counters = defaultdict(list)
    
    for counter_category in context.keys():
        for action in context[counter_category].keys():
            if action.startswith("_"):
                continue
            hook_counters[action].append(counter_category)

    def increment_context_counter(ctx, path: list[str]):
        target = ctx
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] += 1
        target["_total"] += 1
        return None
    
    def increment_context_counters(ctx, categories: list, action: str):
        for category in categories:
            increment_context_counter(ctx, [category, action])

    def make_hook(categories: list, action: str):
        return lambda ctx: increment_context_counters(ctx, categories, action)

    for action in hook_counters.keys():
        pyboy.hook_register(None, action, make_hook(hook_counters[action], action), context)

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
        if action.startswith("_"):
            continue
        pyboy.hook_deregister(None, action)
