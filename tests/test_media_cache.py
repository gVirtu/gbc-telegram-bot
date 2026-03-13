"""Tests for src/utils/media_cache.py."""

import wave
from io import BytesIO
from unittest.mock import patch

import numpy as np
import pytest

from src.utils.media_cache import save_last_animation, load_last_animation


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
