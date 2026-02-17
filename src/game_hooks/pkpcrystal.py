"""Hooks for Polished Crystal (PKPCRYSTAL).

Provides game-specific hooks for:
- Blocking dangerous actions (releasing Pokemon, tossing items)
- Detecting input wait loops for early animation termination
"""

import logging

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
            "_total": 0
        }
    }

    def increment_context_counter(ctx, path):
        target = ctx
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] += 1
        target["_total"] += 1
        return None

    def make_hook(category, action):
        return lambda ctx: increment_context_counter(ctx, [category, action])

    for action in context["dangerousActions"].keys():
        if action.startswith("_"):
            continue
        pyboy.hook_register(None, action, make_hook("dangerousActions", action), context)

    for action in context["inputWaitCalls"].keys():
        if action.startswith("_"):
            continue
        pyboy.hook_register(None, action, make_hook("inputWaitCalls", action), context)

    return context


def end_hooks(pyboy, context: dict) -> None:
    """Deregister Polished Crystal hooks.

    Args:
        pyboy: PyBoy emulator instance
        context: Context dict from begin_hooks
    """
    for action in context["dangerousActions"].keys():
        if action.startswith("_"):
            continue
        pyboy.hook_deregister(None, action)

    for action in context["inputWaitCalls"].keys():
        if action.startswith("_"):
            continue
        pyboy.hook_deregister(None, action)
