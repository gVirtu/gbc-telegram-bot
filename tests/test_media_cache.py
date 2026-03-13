"""Tests for src/utils/media_cache.py."""

import wave
from io import BytesIO
from unittest.mock import patch

import numpy as np
import pytest

from src.utils.media_cache import save_last_animation, load_last_animation, save_last_audio


class TestSaveLastAnimation:
    def test_save_creates_directory(self, tmp_path):
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_animation(42, BytesIO(b"data"))
            assert (tmp_path / "media" / "42").is_dir()

    def test_save_and_load_mp4(self, tmp_path):
        content = b"fake_mp4_content"
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_animation(1, BytesIO(content), media_type="animation")
            result = load_last_animation(1, media_type="animation")
        assert result is not None
        assert result.read() == content

    def test_save_and_load_avif(self, tmp_path):
        content = b"fake_avif_content"
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_animation(2, BytesIO(content), media_type="avif")
            result = load_last_animation(2, media_type="avif")
        assert result is not None
        assert result.read() == content

    def test_load_missing_returns_none(self, tmp_path):
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            result = load_last_animation(999, media_type="animation")
        assert result is None

    def test_save_overwrites_existing(self, tmp_path):
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_animation(3, BytesIO(b"first"), media_type="animation")
            save_last_animation(3, BytesIO(b"second"), media_type="animation")
            result = load_last_animation(3, media_type="animation")
        assert result is not None
        assert result.read() == b"second"


class TestSaveLastAudio:
    """Tests for save_last_audio()."""

    def _make_chunks(self, n_chunks: int = 3, samples_per_chunk: int = 10) -> list:
        """Helper to create a list of int8 stereo audio chunks."""
        return [
            np.full((samples_per_chunk, 2), i, dtype=np.int8)
            for i in range(n_chunks)
        ]

    def test_empty_chunks_no_file(self, tmp_path):
        """Empty audio_chunks list → no WAV file is written."""
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_audio(1, [])
        assert not (tmp_path / "media" / "1" / "last_audio.wav").exists()

    def test_wav_file_created(self, tmp_path):
        """save_last_audio() creates last_audio.wav in the correct directory."""
        chunks = self._make_chunks()
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_audio(42, chunks)
        assert (tmp_path / "media" / "42" / "last_audio.wav").exists()

    def test_wav_channels(self, tmp_path):
        """Written WAV has 2 channels (stereo)."""
        chunks = self._make_chunks()
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_audio(5, chunks)
        with wave.open(str(tmp_path / "media" / "5" / "last_audio.wav")) as wf:
            assert wf.getnchannels() == 2

    def test_wav_sample_width(self, tmp_path):
        """Written WAV has 16-bit samples (sampwidth=2)."""
        chunks = self._make_chunks()
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_audio(6, chunks)
        with wave.open(str(tmp_path / "media" / "6" / "last_audio.wav")) as wf:
            assert wf.getsampwidth() == 2

    def test_wav_frame_rate(self, tmp_path):
        """Written WAV uses 48 000 Hz sample rate by default."""
        chunks = self._make_chunks()
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_audio(7, chunks)
        with wave.open(str(tmp_path / "media" / "7" / "last_audio.wav")) as wf:
            assert wf.getframerate() == 48000

    def test_wav_frame_count(self, tmp_path):
        """Total WAV frames equals sum of samples across all chunks."""
        n_chunks, samples_per_chunk = 3, 10
        chunks = self._make_chunks(n_chunks, samples_per_chunk)
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_audio(8, chunks)
        with wave.open(str(tmp_path / "media" / "8" / "last_audio.wav")) as wf:
            assert wf.getnframes() == n_chunks * samples_per_chunk

    def test_wav_creates_directory(self, tmp_path):
        """save_last_audio() creates the media cache directory if it doesn't exist."""
        chunks = self._make_chunks()
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_audio(99, chunks)
        assert (tmp_path / "media" / "99").is_dir()

    def test_wav_overwrites_existing(self, tmp_path):
        """Calling save_last_audio() twice overwrites the previous file."""
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_audio(10, self._make_chunks(2, 5))
            save_last_audio(10, self._make_chunks(4, 5))
        with wave.open(str(tmp_path / "media" / "10" / "last_audio.wav")) as wf:
            assert wf.getnframes() == 4 * 5

    def test_custom_sample_rate(self, tmp_path):
        """save_last_audio() respects a custom sample_rate argument."""
        chunks = self._make_chunks()
        with patch("src.utils.media_cache.settings") as mock_settings:
            mock_settings.data_dir = tmp_path
            save_last_audio(11, chunks, sample_rate=44100)
        with wave.open(str(tmp_path / "media" / "11" / "last_audio.wav")) as wf:
            assert wf.getframerate() == 44100
