"""Timelapse encoding queue and worker for daily recap videos.

This module provides background encoding of gameplay frames into daily
timelapse MP4 files.  Jobs are persisted in the ``timelapse_jobs`` SQLite
table so they survive crashes and restarts.  Raw numpy frames are stored on
disk under ``data/frames/{chat_id}/{folder}/`` and read lazily by the worker,
keeping peak memory to a minimum.
"""

import asyncio
import fcntl
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from src.config import settings
from src.db.manager import DatabaseManager
from src.models.game_state import TimelapseJobRow
from src.utils.frame_utils import build_timelapse_transform, save_frames_as_mp4_streaming
from src.utils.priority_gate import wait_while_busy
from src.utils.recap_utils import auto_send_split_recap_part

logger = logging.getLogger(__name__)


class TimelapseEncoder:
    """Handles encoding frames into daily timelapse videos."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    # ------------------------------------------------------------------ paths

    def _get_video_path(self, chat_id: int, date: str) -> Path:
        recap_dir = settings.data_dir / "recaps" / str(chat_id)
        recap_dir.mkdir(parents=True, exist_ok=True)
        return recap_dir / f"recap_{date}.mp4"

    def _get_rt_video_path(self, chat_id: int, date: str) -> Path:
        recap_dir = settings.data_dir / "recaps" / str(chat_id)
        recap_dir.mkdir(parents=True, exist_ok=True)
        return recap_dir / f"recap_{date}_rt.mp4"

    # ------------------------------------------------------------------ metadata

    async def _get_current_part_number(self, chat_id: int, date: str, is_rt: bool) -> int:
        parts = await self.db_manager.get_recap_parts(chat_id, date, is_rt)
        if not parts:
            return 1
        return max(p.part_number for p in parts)

    async def _update_recap_metadata(
        self,
        chat_id: int,
        date: str,
        video_path: Path,
        frame_count: int,
        fps: int = 15,
        is_rt: bool = False,
        current_part_number: int = 1,
    ) -> None:
        try:
            file_size = video_path.stat().st_size
            duration_sec = frame_count / max(fps, 1)
            await self.db_manager.upsert_recap_metadata(
                chat_id=chat_id,
                date=date,
                added_frame_count=frame_count,
                added_duration_sec=duration_sec,
                file_size_bytes=file_size,
                part_number=current_part_number,
                is_rt=is_rt,
            )
        except Exception as e:
            logger.error(f"Failed to update recap metadata: {e}")

    async def _check_and_split_if_needed(
        self,
        chat_id: int,
        date: str,
        video_path: Path,
        is_rt: bool,
        current_part_number: int,
    ) -> None:
        """Rename current part file and create a new DB row if size threshold is exceeded.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format
            video_path: Path to the current (suffixless) video file
            is_rt: Whether this is a realtime recap
            current_part_number: The current part number
        """
        if not video_path.exists():
            return
        if video_path.stat().st_size <= settings.recap_part_file_size_threshold:
            return
        suffix = "_rt" if is_rt else ""
        part_path = video_path.parent / f"recap_{date}_part{current_part_number}{suffix}.mp4"
        os.rename(video_path, part_path)
        await self.db_manager.split_recap_part(chat_id, date, current_part_number, is_rt)
        logger.info(f"Split recap for chat {chat_id}, date {date} into part {current_part_number}")
        asyncio.create_task(
            auto_send_split_recap_part(chat_id, date, current_part_number, is_rt)
        )

    # ------------------------------------------------------------------ encoding helpers

    async def _create_new_timelapse_streaming(
        self,
        video_path: Path,
        frame_gen,
        transform,
        fps: int,
        audio_chunks=None,
    ) -> None:
        tmp_path = video_path.with_suffix(".tmp.mp4")
        try:
            await save_frames_as_mp4_streaming(
                frame_gen,
                transform,
                str(tmp_path),
                fps=fps,
                crf=28,
                preset="medium",
                audio_chunks=audio_chunks,
                low_priority=True,
            )
            os.replace(tmp_path, video_path)
            logger.info(f"Created new timelapse: {video_path}")
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    async def _append_frames_streaming(
        self,
        video_path: Path,
        frame_gen,
        transform,
        fps: int,
        audio_chunks=None,
    ) -> None:
        ts = datetime.now().timestamp()
        segment_path = video_path.parent / f"segment_{ts}.mp4"
        concat_list_path = video_path.parent / f"concat_{ts}.txt"
        output_path = video_path.with_suffix(".tmp.mp4")

        try:
            await save_frames_as_mp4_streaming(
                frame_gen,
                transform,
                str(segment_path),
                fps=fps,
                crf=28,
                preset="medium",
                audio_chunks=audio_chunks,
                low_priority=True,
            )

            with open(concat_list_path, "w") as f:
                f.write(f"file '{video_path.absolute()}'\n")
                f.write(f"file '{segment_path.absolute()}'\n")

            cmd = [
                "ffmpeg", "-f", "concat", "-safe", "0",
                "-i", str(concat_list_path),
                "-c", "copy",
                str(output_path),
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=lambda: os.nice(19),
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                raise RuntimeError(f"FFmpeg concat failed: {stderr.decode()}")

            os.replace(output_path, video_path)
            logger.info(f"Appended frames to {video_path}")

        finally:
            for p in [segment_path, concat_list_path, output_path]:
                if Path(p).exists():
                    Path(p).unlink()

    # ------------------------------------------------------------------ main encode

    async def _do_encode_and_append(self, job: TimelapseJobRow) -> None:
        """Encode frames from disk and append to the daily timelapse file.

        Args:
            job: The timelapse job row with folder_path and compositing_context.
        """
        chat_id = int(job.chat_id)
        ctx = job.compositing_context
        frame_skip = ctx.get("frame_skip", 1)
        frame_count = job.frame_count
        fps = job.fps

        dt = datetime.fromisoformat(job.timestamp)
        date = dt.strftime("%Y%m%d")

        folder = Path(job.folder_path)

        # Load audio if present
        audio_chunks = None
        audio_path = folder / "audio.npz"
        if audio_path.exists():
            try:
                npz = np.load(str(audio_path))
                audio_chunks = [npz[k] for k in sorted(npz.files, key=lambda k: int(k.split('_')[1]))]
            except Exception as e:
                logger.warning(f"Failed to load audio for job {job.id}: {e}")

        is_rt = bool(audio_chunks)
        video_path = self._get_rt_video_path(chat_id, date) if is_rt else self._get_video_path(chat_id, date)

        # Build per-frame transform from stored compositing context
        transform = build_timelapse_transform(ctx)

        # Frame generator: reads lazily from disk, applying frame_skip
        def make_frame_gen():
            for i in range(0, frame_count, max(frame_skip, 1)):
                frame_path = folder / f"frame_{i:06d}.npy"
                try:
                    yield np.load(str(frame_path))
                except Exception as e:
                    logger.warning(f"Failed to load frame {frame_path}: {e}")

        actual_frame_count = len(range(0, frame_count, max(frame_skip, 1)))

        lock_path = video_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        with open(lock_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

                if video_path.exists():
                    await self._append_frames_streaming(
                        video_path, make_frame_gen(), transform, fps, audio_chunks
                    )
                else:
                    await self._create_new_timelapse_streaming(
                        video_path, make_frame_gen(), transform, fps, audio_chunks
                    )

                current_part = await self._get_current_part_number(chat_id, date, is_rt)
                await self._update_recap_metadata(
                    chat_id, date, video_path, actual_frame_count, fps, is_rt, current_part
                )
                await self._check_and_split_if_needed(chat_id, date, video_path, is_rt, current_part)
            except Exception as e:
                logger.error(f"Failed to encode timelapse for chat {chat_id}, date {date}: {e}")
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

        if lock_path.exists():
            lock_path.unlink()

    async def _encode_with_retry(self, job: TimelapseJobRow) -> None:
        """Encode a timelapse job with retry/backoff logic.

        Args:
            job: The timelapse job to encode.
        """
        backoff_delays = settings.timelapse_backoff_delays
        max_attempts = len(backoff_delays)

        for attempt in range(max_attempts + 1):
            try:
                await self._do_encode_and_append(job)
                return  # success
            except Exception as e:
                logger.error(f"Timelapse encode attempt {attempt + 1}/{max_attempts} for job {job.id}: {e}")
                if attempt < max_attempts - 1:
                    delay = backoff_delays[attempt]
                    logger.info(f"Retrying job {job.id} in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"All encode attempts failed for job {job.id} "
                        f"(chat {job.chat_id}). Frames at: {job.folder_path}"
                    )
                    raise


class TimelapseEncodingQueue:
    """DB-driven per-chat timelapse encoding queue.

    Instead of an in-memory asyncio.Queue, pending jobs are persisted in the
    ``timelapse_jobs`` table.  A lightweight worker task is created per chat
    whenever new work arrives; it drains all pending jobs and exits.  Only one
    worker runs per chat at a time (tracked by ``_active``).
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.encoder = TimelapseEncoder(db_manager)
        self._active: set = set()  # chat_id strings with a running worker task
        self._prune_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ public API

    def trigger_worker(self, chat_id) -> None:
        """Schedule a worker for ``chat_id`` if one is not already running.

        Safe to call from any async context; creates an asyncio task internally.

        Args:
            chat_id: Chat ID (int or str).
        """
        cid = str(chat_id)
        if cid in self._active:
            return
        asyncio.create_task(self._run_worker(cid))

    async def _run_prune_loop(self) -> None:
        """Prune done jobs once immediately, then every 24 hours."""
        from src.utils.state_manager import state_manager
        while True:
            try:
                state_manager.prune_done_jobs(settings.timelapse_done_job_retention_days)
            except Exception:
                logger.exception("Error during timelapse job pruning")
            await asyncio.sleep(86400)

    async def startup_recovery(self) -> None:
        """Reset stuck jobs and resume workers for all chats with pending work.

        Must be called once during application startup after DB initialisation.
        """
        from src.utils.state_manager import state_manager
        state_manager.reset_stuck_jobs()
        state_manager.cleanup_orphaned_folders()
        for chat_id in state_manager.get_chats_with_pending_jobs():
            self.trigger_worker(chat_id)
        self._prune_task = asyncio.create_task(self._run_prune_loop())
        logger.info("TimelapseEncodingQueue startup recovery complete")

    async def shutdown(self) -> None:
        """Wait (up to 30 s) for active workers to finish, then return."""
        logger.info("Shutting down timelapse encoding queue...")
        if self._prune_task and not self._prune_task.done():
            self._prune_task.cancel()
            try:
                await self._prune_task
            except asyncio.CancelledError:
                pass
        deadline = asyncio.get_event_loop().time() + 30.0
        while self._active and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
        if self._active:
            logger.warning(f"Shutdown timeout; active workers: {self._active}")
        logger.info("Timelapse encoding queue shutdown complete")

    # ------------------------------------------------------------------ worker

    async def _run_worker(self, chat_id: str) -> None:
        """Drain all pending jobs for ``chat_id`` sequentially.

        Args:
            chat_id: Chat ID string.
        """
        self._active.add(chat_id)
        logger.info(f"Timelapse worker started for chat {chat_id}")
        try:
            from src.utils.state_manager import state_manager
            while True:
                job = state_manager.fetch_next_pending_job(chat_id)
                if job is None:
                    break

                state_manager.update_job_status(job.id, 'processing')
                try:
                    # Wait for input processing to finish before encoding
                    await wait_while_busy(timeout=settings.timelapse_idle_wait_timeout)
                    await self.encoder._encode_with_retry(job)
                    state_manager.update_job_status(job.id, 'done')
                    # Clean up frame folder after successful encode
                    folder = Path(job.folder_path)
                    if folder.exists():
                        shutil.rmtree(folder)
                        logger.debug(f"Deleted frame folder: {folder}")
                except Exception as e:
                    logger.error(f"Failed to encode timelapse job {job.id} for chat {chat_id}: {e}")
                    state_manager.update_job_status(job.id, 'failed')
        finally:
            self._active.discard(chat_id)
            logger.info(f"Timelapse worker finished for chat {chat_id}")


# Global instance (initialised in webhook.py lifespan)
timelapse_queue: Optional[TimelapseEncodingQueue] = None
