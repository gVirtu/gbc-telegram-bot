"""Optional cProfile instrumentation for hot-path CPU profiling.

Activated only when the PROFILE environment variable is set to a non-empty
value. All public functions are no-ops when profiling is disabled, so this
module can be imported unconditionally without any runtime cost.

Usage
-----
Set ``PROFILE=1`` before starting the bot. Optionally set ``PROFILE_DIR``
to control where ``.prof`` files are written (default: ``profiles/``).

    PROFILE=1 PROFILE_DIR=/tmp/profs poetry run python -m src.main

One ``.prof`` file is written per ``_process_batch`` call, named:

    {PROFILE_DIR}/batch_{chat_id}_{YYYYMMDD_HHMMSS_ffffff}.prof

Visualise with snakeviz::

    poetry run snakeviz profiles/batch_*.prof

In the icicle chart, width = cumulative CPU time. Key nodes to look for:
``render_input_sidebar``, ``composite_overlay``, ``render_status_bar``,
``save_frames_as_mp4_streaming``, PIL ``ImagingCore.resize``, ``np.vstack``.
"""

import cProfile
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_enabled = bool(os.environ.get("PROFILE"))
_profile_dir = Path(os.environ.get("PROFILE_DIR", "profiles"))


def start() -> cProfile.Profile | None:
    """Create and enable a cProfile.Profile. Returns None when disabled."""
    if not _enabled:
        return None
    profiler = cProfile.Profile()
    profiler.enable()
    return profiler


def stop(profiler: cProfile.Profile | None, label: str) -> None:
    """Disable profiler and write a .prof file. No-op when profiler is None."""
    if profiler is None:
        return
    profiler.disable()
    _profile_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = _profile_dir / f"{label}_{ts}.prof"
    profiler.dump_stats(str(path))
    logger.info("[PROFILE] Saved profile to %s", path)
