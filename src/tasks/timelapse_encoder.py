"""Timelapse encoding queue and worker for daily recap videos.

This module provides background encoding of gameplay frames into daily
timelapse MP4 files. Encoding happens asynchronously to avoid blocking
the main bot flow.
"""

import asyncio
import fcntl
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from src.config import settings
from src.db.manager import DatabaseManager
from src.utils.frame_utils import (
    save_frames_as_mp4_optimized,
    save_frames_as_mp4_with_audio,
)

logger = logging.getLogger(__name__)


@dataclass
class TimelapseJob:
    """A timelapse encoding job."""

    chat_id: int
    frames: List[np.ndarray]
    timestamp: str  # ISO8601 timestamp
    audio_chunks: Optional[List[np.ndarray]] = None
    fps: int = 10



class TimelapseEncoder:
    """Handles encoding frames into daily timelapse videos."""

    def __init__(self, db_manager: DatabaseManager):
        """Initialize the encoder.

        Args:
            db_manager: Database manager for metadata updates
        """
        self.db_manager = db_manager

    def _get_video_path(self, chat_id: int, date: str) -> Path:
        """Get the path to a daily timelapse video.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format

        Returns:
            Path to the timelapse video file
        """
        recap_dir = settings.data_dir / "recaps" / str(chat_id)
        recap_dir.mkdir(parents=True, exist_ok=True)
        return recap_dir / f"recap_{date}.mp4"

    def _get_rt_video_path(self, chat_id: int, date: str) -> Path:
        """Get the path to a daily realtime timelapse video.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format

        Returns:
            Path to the realtime timelapse video file
        """
        recap_dir = settings.data_dir / "recaps" / str(chat_id)
        recap_dir.mkdir(parents=True, exist_ok=True)
        return recap_dir / f"recap_{date}_rt.mp4"

    def _get_failed_frames_path(self, chat_id: int, timestamp: str) -> Path:
        """Get the path to save failed frames.

        Args:
            chat_id: The Telegram chat ID
            timestamp: ISO8601 timestamp

        Returns:
            Path to directory for failed frames
        """
        failed_dir = settings.data_dir / "recaps" / str(chat_id) / "failed" / timestamp
        failed_dir.mkdir(parents=True, exist_ok=True)
        return failed_dir

    async def _save_failed_frames(
        self, chat_id: int, timestamp: str, frames: List[np.ndarray], error: Exception
    ) -> None:
        """Save frames that failed to encode for later recovery.

        Args:
            chat_id: The Telegram chat ID
            timestamp: ISO8601 timestamp
            frames: Frames that failed to encode
            error: The error that occurred
        """
        try:
            failed_dir = self._get_failed_frames_path(chat_id, timestamp)

            # Save each frame as numpy array
            for i, frame in enumerate(frames):
                frame_path = failed_dir / f"frame_{i:05d}.npy"
                np.save(frame_path, frame)

            # Save error info
            error_path = failed_dir / "error.txt"
            with open(error_path, "w") as f:
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Error: {str(error)}\n")
                f.write(f"Frame count: {len(frames)}\n")

            logger.info(f"Saved {len(frames)} failed frames to {failed_dir}")

        except Exception as e:
            logger.error(f"Failed to save failed frames: {e}")

    async def _update_recap_metadata(self, chat_id: int, date: str, video_path: Path, frame_count: int) -> None:
        """Update database with recap metadata.

        Args:
            chat_id: The Telegram chat ID
            date: Date in YYYYMMDD format
            video_path: Path to the video file
        """
        try:
            file_size = video_path.stat().st_size

            # Estimate duration from file size and typical bitrate
            # With 10 FPS and our encoding settings, estimate
            duration_sec = frame_count / 10

            await self.db_manager.upsert_recap_metadata(
                chat_id=chat_id,
                date=date,
                added_frame_count=frame_count,
                added_duration_sec=duration_sec,
                file_size_bytes=file_size,
            )

        except Exception as e:
            logger.error(f"Failed to update recap metadata: {e}")

    async def _create_new_timelapse(
        self,
        video_path: Path,
        frames: List[np.ndarray],
        fps: int = 10,
    ) -> None:
        """Create a new daily timelapse video.

        Args:
            video_path: Path to save the video
            frames: Frames to encode
            fps: Frames per second
        """
        # Create temporary file
        tmp_path = video_path.with_suffix(".tmp.mp4")

        try:
            # Encode frames to temporary file
            await save_frames_as_mp4_optimized(frames, str(tmp_path), fps=fps)

            # Atomically replace with final file
            os.replace(tmp_path, video_path)

            logger.info(f"Created new timelapse: {video_path}")

        except Exception as e:
            # Clean up temporary file on error
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    async def _create_new_realtime_timelapse(
        self,
        video_path: Path,
        frames: List[np.ndarray],
        audio_chunks: List[np.ndarray],
        fps: int,
    ) -> None:
        """Create a new realtime timelapse video with audio.

        Args:
            video_path: Path to save the video
            frames: Frames to encode
            audio_chunks: Audio chunks to include
            fps: Frames per second
        """
        tmp_path = video_path.with_suffix(".tmp.mp4")

        try:
            await save_frames_as_mp4_with_audio(frames, audio_chunks, str(tmp_path), fps=fps)
            os.replace(tmp_path, video_path)
            logger.info(f"Created new realtime timelapse: {video_path}")

        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    async def _append_frames(
        self,
        video_path: Path,
        frames: List[np.ndarray],
        fps: int = 10,
    ) -> None:
        """Append frames to an existing timelapse video.

        Args:
            video_path: Path to existing video
            frames: Frames to append
            fps: Frames per second
        """
        # Create temporary segment file
        segment_path = video_path.parent / f"segment_{datetime.now().timestamp()}.mp4"
        concat_list_path = video_path.parent / f"concat_{datetime.now().timestamp()}.txt"
        output_path = video_path.with_suffix(".tmp.mp4")

        try:
            # Encode new frames to segment
            await save_frames_as_mp4_optimized(frames, str(segment_path), fps=fps)

            # Create concat demuxer list
            with open(concat_list_path, "w") as f:
                f.write(f"file '{video_path.absolute()}'\n")
                f.write(f"file '{segment_path.absolute()}'\n")

            # Concatenate videos using FFmpeg
            cmd = [
                "ffmpeg",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list_path),
                "-c",
                "copy",
                str(output_path),
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"FFmpeg concat failed: {stderr.decode()}")

            # Atomically replace original with concatenated video
            os.replace(output_path, video_path)

            logger.info(f"Appended {len(frames)} frames to {video_path}")

        finally:
            # Clean up temporary files
            for path in [segment_path, concat_list_path, output_path]:
                if path.exists():
                    path.unlink()

    async def _append_realtime_frames(
        self,
        video_path: Path,
        frames: List[np.ndarray],
        audio_chunks: List[np.ndarray],
        fps: int,
    ) -> None:
        """Append frames with audio to an existing realtime timelapse video.

        Args:
            video_path: Path to existing video
            frames: Frames to append
            audio_chunks: Audio chunks to include
            fps: Frames per second
        """
        segment_path = video_path.parent / f"segment_rt_{datetime.now().timestamp()}.mp4"
        concat_list_path = video_path.parent / f"concat_rt_{datetime.now().timestamp()}.txt"
        output_path = video_path.with_suffix(".tmp.mp4")

        try:
            await save_frames_as_mp4_with_audio(frames, audio_chunks, str(segment_path), fps=fps)

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
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"FFmpeg concat failed: {stderr.decode()}")

            os.replace(output_path, video_path)
            logger.info(f"Appended {len(frames)} frames to realtime timelapse {video_path}")

        finally:
            for path in [segment_path, concat_list_path, output_path]:
                if path.exists():
                    path.unlink()

    async def _do_encode_and_append(self, job: "TimelapseJob") -> None:
        """Encode frames and append to daily timelapse.

        Args:
            job: The timelapse job to encode
        """
        chat_id = job.chat_id

        frames = job.frames

        timestamp = job.timestamp
        audio_chunks = job.audio_chunks
        fps = job.fps

        # Get date from timestamp (server local timezone)
        dt = datetime.fromisoformat(timestamp)
        date = dt.strftime("%Y%m%d")

        if audio_chunks:
            video_path = self._get_rt_video_path(chat_id, date)
        else:
            video_path = self._get_video_path(chat_id, date)

        # Acquire file lock to prevent concurrent access
        lock_path = video_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        with open(lock_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

                if video_path.exists():
                    if audio_chunks:
                        await self._append_realtime_frames(video_path, frames, audio_chunks, fps)
                    else:
                        await self._append_frames(video_path, frames, fps)
                else:
                    if audio_chunks:
                        await self._create_new_realtime_timelapse(video_path, frames, audio_chunks, fps)
                    else:
                        await self._create_new_timelapse(video_path, frames, fps)

                await self._update_recap_metadata(chat_id, date, video_path, len(frames))

            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

        if lock_path.exists():
            lock_path.unlink()

    async def _encode_with_retry(self, job: "TimelapseJob") -> None:
        """Encode frames with retry logic.

        Args:
            job: The timelapse job to encode
        """
        backoff_delays = settings.timelapse_backoff_delays
        max_attempts = len(backoff_delays)

        for attempt in range(max_attempts + 1):
            try:
                await self._do_encode_and_append(job)
                return  # Success!

            except Exception as e:
                logger.error(f"Encoding attempt {attempt + 1}/{max_attempts} failed: {e}")

                if attempt < max_attempts - 1:
                    # Retry after backoff delay
                    delay = backoff_delays[attempt]
                    logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    # All attempts failed, save frames for recovery
                    logger.error(f"All encoding attempts failed for chat {job.chat_id}")
                    await self._save_failed_frames(job.chat_id, job.timestamp, job.frames, e)
                    raise

    async def encode_job(self, job: TimelapseJob) -> None:
        """Encode a timelapse job.

        Args:
            job: The timelapse job to encode
        """
        await self._encode_with_retry(job)


class TimelapseEncodingQueue:
    """Manages per-chat encoding queues and workers."""

    def __init__(self, db_manager: DatabaseManager):
        """Initialize the encoding queue.

        Args:
            db_manager: Database manager for metadata updates
        """
        self.db_manager = db_manager
        self.encoder = TimelapseEncoder(db_manager)
        self._queues: Dict[int, asyncio.Queue] = {}
        self._workers: Dict[int, asyncio.Task] = {}

    async def enqueue(
        self,
        chat_id: int,
        frames: List[np.ndarray],
        timestamp: str,
        audio_chunks: Optional[List[np.ndarray]] = None,
        fps: int = 10,
    ) -> None:
        """Enqueue frames for encoding.

        Args:
            chat_id: The Telegram chat ID
            frames: Frames to encode
            timestamp: ISO8601 timestamp
            audio_chunks: Optional audio chunks
            fps: Frames per second
        """
        # Create queue and worker for chat if not exists
        if chat_id not in self._queues:
            self._queues[chat_id] = asyncio.Queue()
            self._workers[chat_id] = asyncio.create_task(self._worker(chat_id))

        # Add job to queue
        job = TimelapseJob(
            chat_id=chat_id,
            frames=frames,
            timestamp=timestamp,
            audio_chunks=audio_chunks,
            fps=fps,
        )
        await self._queues[chat_id].put(job)

        logger.debug(f"Enqueued timelapse job for chat {chat_id}, queue size: {self._queues[chat_id].qsize()}")

    async def _worker(self, chat_id: int) -> None:
        """Sequential worker for a chat's encoding queue.

        Args:
            chat_id: The Telegram chat ID
        """
        logger.info(f"Started timelapse worker for chat {chat_id}")

        queue = self._queues[chat_id]

        try:
            while True:
                # Get next job from queue
                job = await queue.get()

                try:
                    # Encode the job
                    await self.encoder.encode_job(job)
                except Exception as e:
                    logger.error(f"Failed to encode timelapse job for chat {chat_id}: {e}")
                finally:
                    # Mark job as done
                    queue.task_done()

        except asyncio.CancelledError:
            logger.info(f"Timelapse worker for chat {chat_id} cancelled")
            raise

    async def shutdown(self) -> None:
        """Gracefully shutdown all workers."""
        logger.info("Shutting down timelapse encoding queue...")

        # Wait for all queues to be empty (with timeout to avoid hanging)
        try:
            await asyncio.wait_for(
                asyncio.gather(*[queue.join() for queue in self._queues.values()]),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for timelapse queues to empty, forcing shutdown")

        # Cancel all workers
        for chat_id, worker in self._workers.items():
            worker.cancel()

        # Wait for all workers to finish
        await asyncio.gather(*self._workers.values(), return_exceptions=True)

        logger.info("Timelapse encoding queue shutdown complete")


# Global instance (initialized in webhook.py)
timelapse_queue: Optional[TimelapseEncodingQueue] = None
