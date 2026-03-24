"""Priority gate for timelapse encoding.

Allows timelapse workers to wait while input processing is active,
ensuring animation encoding (latency-sensitive) is not starved by
background timelapse encoding.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_active_count: int = 0
_idle_event: asyncio.Event | None = None


def _event() -> asyncio.Event:
    global _idle_event
    if _idle_event is None:
        _idle_event = asyncio.Event()
        _idle_event.set()
    return _idle_event


def mark_busy() -> None:
    """Increment active input processing count and mark as busy."""
    global _active_count
    _active_count += 1
    _event().clear()


def mark_idle() -> None:
    """Decrement active input processing count; set event when count hits 0."""
    global _active_count
    _active_count = max(0, _active_count - 1)
    if _active_count == 0:
        _event().set()


async def wait_while_busy(timeout: float) -> None:
    """Wait until input processing is idle, or proceed after timeout (starvation protection).

    Args:
        timeout: Maximum seconds to wait before proceeding anyway.
    """
    if _active_count == 0:
        return
    logger.debug(f"Timelapse worker waiting for input idle (timeout={timeout}s)")
    try:
        await asyncio.wait_for(_event().wait(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"Timelapse worker timed out waiting for input idle after {timeout}s, proceeding anyway")
