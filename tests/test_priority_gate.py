"""Tests for priority_gate module."""

import asyncio
import pytest
import src.utils.priority_gate as pg


@pytest.fixture(autouse=True)
def reset_gate():
    """Reset global state before each test."""
    pg._active_count = 0
    pg._idle_event = None
    yield
    pg._active_count = 0
    pg._idle_event = None


@pytest.mark.asyncio
async def test_returns_immediately_when_not_busy():
    """wait_while_busy returns immediately when no one is busy."""
    # Should complete without blocking
    await asyncio.wait_for(pg.wait_while_busy(timeout=0.1), timeout=1.0)


@pytest.mark.asyncio
async def test_waits_while_busy_then_proceeds_on_idle():
    """wait_while_busy waits while busy and resumes after mark_idle."""
    pg.mark_busy()

    released = asyncio.Event()

    async def release_after_short_delay():
        await asyncio.sleep(0.05)
        pg.mark_idle()
        released.set()

    asyncio.create_task(release_after_short_delay())

    await asyncio.wait_for(pg.wait_while_busy(timeout=2.0), timeout=1.0)
    assert released.is_set()


@pytest.mark.asyncio
async def test_proceeds_after_timeout_when_still_busy():
    """wait_while_busy proceeds after timeout even if still busy (starvation protection)."""
    pg.mark_busy()

    # Should complete after timeout without hanging
    await asyncio.wait_for(pg.wait_while_busy(timeout=0.05), timeout=1.0)

    # Gate is still busy
    assert pg._active_count == 1


@pytest.mark.asyncio
async def test_multiple_busy_requires_all_idle():
    """Event is only set when all mark_busy callers have called mark_idle."""
    pg.mark_busy()
    pg.mark_busy()

    released = asyncio.Event()

    async def release_both():
        await asyncio.sleep(0.02)
        pg.mark_idle()
        # Still one busy — should still be waiting
        await asyncio.sleep(0.02)
        pg.mark_idle()
        released.set()

    asyncio.create_task(release_both())

    await asyncio.wait_for(pg.wait_while_busy(timeout=2.0), timeout=1.0)
    assert released.is_set()
    assert pg._active_count == 0


@pytest.mark.asyncio
async def test_mark_idle_does_not_go_below_zero():
    """mark_idle clamps _active_count at 0."""
    pg.mark_idle()
    assert pg._active_count == 0


@pytest.mark.asyncio
async def test_returns_immediately_after_all_idle():
    """wait_while_busy returns immediately once the gate is idle again."""
    pg.mark_busy()
    pg.mark_idle()

    # Gate is now idle; should return immediately
    await asyncio.wait_for(pg.wait_while_busy(timeout=0.1), timeout=1.0)
