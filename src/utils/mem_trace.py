"""Optional tracemalloc instrumentation for memory leak investigation.

Activated only when the TRACEMALLOC environment variable is set to a non-empty
value.  All public functions are no-ops when tracing is disabled, so this
module can be imported unconditionally without any runtime cost.

Usage
-----
Set ``TRACEMALLOC=1`` before starting the bot, then call:

    mem_trace.start()          # once at startup
    mem_trace.snapshot("label")  # after each interesting event

Each snapshot logs:
  - [TRACE] top 20 live allocations by size (with source traceback)
  - [TRACE-DIFF] top 20 size *increases* since the previous snapshot
    (the diff is what reveals leaks)

Output goes to the standard logger at INFO level so it lands in the
normal log stream.  Grep for ``[TRACE]`` to extract the relevant lines.
"""

import logging
import os
import tracemalloc
from typing import Optional

logger = logging.getLogger(__name__)

_TRACEBACK_DEPTH = 25  # frames captured per allocation
_TOP_N = 20            # entries reported per snapshot / diff
_enabled = bool(os.environ.get("TRACEMALLOC"))
_prev_snapshot: Optional[tracemalloc.Snapshot] = None
_snapshot_count = 0


def start() -> None:
    """Start tracemalloc if TRACEMALLOC env var is set."""
    if not _enabled:
        return
    tracemalloc.start(_TRACEBACK_DEPTH)
    logger.info("[TRACE] tracemalloc started (depth=%d)", _TRACEBACK_DEPTH)


def snapshot(label: str = "") -> None:
    """Take a snapshot and log top allocations and diff from the previous one."""
    if not _enabled or not tracemalloc.is_tracing():
        return

    global _prev_snapshot, _snapshot_count
    _snapshot_count += 1
    tag = f"#{_snapshot_count} {label}".strip()

    current = tracemalloc.take_snapshot()

    # --- absolute top allocations ---
    top_stats = current.statistics("traceback")
    logger.info("[TRACE] === snapshot %s — top %d allocations ===", tag, _TOP_N)
    for stat in top_stats[:_TOP_N]:
        tb = "\n    ".join(str(line) for line in stat.traceback)
        logger.info(
            "[TRACE] %s\n    %s",
            _fmt_size(stat.size),
            tb,
        )

    # --- diff vs previous snapshot (the leak signal) ---
    if _prev_snapshot is not None:
        diff_stats = current.compare_to(_prev_snapshot, "traceback")
        growing = [d for d in diff_stats if d.size_diff > 0]
        logger.info(
            "[TRACE-DIFF] === diff from previous snapshot — top %d growers ===",
            _TOP_N,
        )
        for stat in growing[:_TOP_N]:
            tb = "\n    ".join(str(line) for line in stat.traceback)
            logger.info(
                "[TRACE-DIFF] +%s (count_diff=%+d)\n    %s",
                _fmt_size(stat.size_diff),
                stat.count_diff,
                tb,
            )
    else:
        logger.info("[TRACE-DIFF] (no previous snapshot — diff available from next call)")

    _prev_snapshot = current


def stop() -> None:
    """Stop tracemalloc and log a final snapshot."""
    if not _enabled or not tracemalloc.is_tracing():
        return
    snapshot("final")
    tracemalloc.stop()
    logger.info("[TRACE] tracemalloc stopped")


def _fmt_size(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n_bytes) < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024  # type: ignore[assignment]
    return f"{n_bytes:.1f} TB"
