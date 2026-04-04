"""Tests for pkpcrystal.init() and _extract_mini_sprite()."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image


def test_init_skips_when_png_exists(tmp_path):
    existing = tmp_path / "151.png"
    existing.touch()

    with patch("src.game_status_bars.pkpcrystal.Path", return_value=existing):
        with patch("src.game_status_bars.pkpcrystal._extract_mini_sprite") as mock_extract:
            from src.game_status_bars import pkpcrystal
            pkpcrystal.init(MagicMock())
            mock_extract.assert_not_called()


def test_init_calls_extract_when_missing(tmp_path):
    missing = tmp_path / "151.png"
    assert not missing.exists()

    with patch("src.game_status_bars.pkpcrystal.Path", return_value=missing):
        with patch("src.game_status_bars.pkpcrystal._extract_mini_sprite") as mock_extract:
            from src.game_status_bars import pkpcrystal
            pyboy = MagicMock()
            pkpcrystal.init(pyboy)
            mock_extract.assert_called_once_with(
                pyboy, "ChikoritaMini", pokemon_index=152, out_path=missing
            )


def test_extract_mini_sprite_saves_rgba_png(tmp_path):
    out_path = tmp_path / "151.png"

    pyboy = MagicMock()
    pyboy.symbol_lookup.return_value = (5, 0x4000)
    pyboy.memory.__getitem__ = MagicMock(return_value=bytes(512))

    with patch("src.game_status_bars.pkpcrystal.Decompressed") as MockLZ, \
         patch("src.game_status_bars.pkpcrystal.decode_2bpp") as mock_decode, \
         patch("src.game_status_bars.pkpcrystal.read_mini_palette") as mock_pal:

        MockLZ.return_value.output = [0] * 128
        mock_decode.return_value = [[0] * 16 for _ in range(32)]
        mock_pal.return_value = [
            (0, 0, 0, 0), (255, 255, 255, 255),
            (100, 180, 80, 255), (40, 100, 40, 255),
        ]

        from src.game_status_bars.pkpcrystal import _extract_mini_sprite
        _extract_mini_sprite(pyboy, "ChikoritaMini", pokemon_index=152, out_path=out_path)

        mock_decode.assert_called_once_with(bytes([0] * 128), width=16, height=32)
        mock_pal.assert_called_once_with(pyboy, 152)

    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (16, 32)
    assert img.mode == "RGBA"
