"""Tests for GBC graphics decoding utilities."""
from src.utils.gbc_graphics import decode_2bpp, gbc_color_to_rgba


class TestDecode2bpp:
    def test_all_index_3(self):
        # lo=0xFF, hi=0xFF for each row → all pixels = index 3
        data = bytes([0xFF, 0xFF] * 8)
        result = decode_2bpp(data, width=8, height=8)
        assert result[0] == [3] * 8
        assert result[7] == [3] * 8

    def test_all_index_0(self):
        data = bytes([0x00, 0x00] * 8)
        result = decode_2bpp(data, width=8, height=8)
        assert result[0] == [0] * 8

    def test_index_1_and_2(self):
        # index 1: lo=0xFF, hi=0x00 → hi_bit=0, lo_bit=1 → index=1
        # index 2: lo=0x00, hi=0xFF → hi_bit=1, lo_bit=0 → index=2
        tile_idx1 = bytes([0xFF, 0x00] * 8)
        tile_idx2 = bytes([0x00, 0xFF] * 8)
        result = decode_2bpp(tile_idx1 + tile_idx2, width=8, height=16)
        assert result[0] == [1] * 8   # top tile
        assert result[8] == [2] * 8   # bottom tile

    def test_alternating_row(self):
        # lo=0xAA (10101010), hi=0xAA → pixels [3,0,3,0,3,0,3,0]
        data = bytes([0xAA, 0xAA] + [0x00, 0x00] * 7)
        result = decode_2bpp(data, width=8, height=8)
        assert result[0] == [3, 0, 3, 0, 3, 0, 3, 0]

    def test_two_tiles_wide(self):
        tile0 = bytes([0xFF, 0xFF] * 8)  # all 3
        tile1 = bytes([0x00, 0x00] * 8)  # all 0
        result = decode_2bpp(tile0 + tile1, width=16, height=8)
        assert result[0] == [3] * 8 + [0] * 8

    def test_output_dimensions(self):
        # 16×32 = 8 tiles × 16 bytes = 128 bytes
        data = bytes(128)
        result = decode_2bpp(data, width=16, height=32)
        assert len(result) == 32
        assert len(result[0]) == 16


class TestGbcColorToRgba:
    def test_black(self):
        assert gbc_color_to_rgba(0x0000) == (0, 0, 0, 255)

    def test_white(self):
        assert gbc_color_to_rgba(0x7FFF) == (255, 255, 255, 255)

    def test_pure_red(self):
        # bits 0-4 = R: 0x001F → R=31=255, G=0, B=0
        assert gbc_color_to_rgba(0x001F) == (255, 0, 0, 255)

    def test_pure_green(self):
        # bits 5-9 = G: 0x03E0 → R=0, G=31=255, B=0
        assert gbc_color_to_rgba(0x03E0) == (0, 255, 0, 255)

    def test_pure_blue(self):
        # bits 10-14 = B: 0x7C00 → R=0, G=0, B=31=255
        assert gbc_color_to_rgba(0x7C00) == (0, 0, 255, 255)

    def test_alpha_always_255(self):
        assert gbc_color_to_rgba(0x1234)[3] == 255


from unittest.mock import MagicMock
from src.utils.gbc_graphics import read_mini_palette


class TestReadMiniPalette:
    def _make_pyboy(self, pal_index: int, gbc_colors: list[int]) -> MagicMock:
        pyboy = MagicMock()

        def sym(name):
            return {
                "OverworldMonIconColors": (1, 0x6000),
                "MonPalettePointers": (2, 0x7000),
            }[name]

        pyboy.symbol_lookup.side_effect = sym

        # Build a flat memory model
        mem = {}
        # palette index at OverworldMonIconColors + (152-1)*2 = 302 = 0x12E
        mem[(1, 0x612E)] = pal_index
        # GBC colors at MonPalettePointers + (pal_index-1)*8
        base = 0x7000 + (pal_index - 1) * 8
        for i, c in enumerate(gbc_colors):
            mem[(2, base + i * 2)]     = c & 0xFF
            mem[(2, base + i * 2 + 1)] = (c >> 8) & 0xFF

        pyboy.memory.__getitem__ = MagicMock(side_effect=lambda k: mem.get(k, 0))
        return pyboy

    def test_returns_four_tuples(self):
        pyboy = self._make_pyboy(2, [0x7FFF, 0x03E0, 0x001F])
        result = read_mini_palette(pyboy, pokemon_index=152)
        assert len(result) == 4

    def test_index_0_is_transparent(self):
        pyboy = self._make_pyboy(2, [0x7FFF, 0x7FFF, 0x7FFF])
        result = read_mini_palette(pyboy, pokemon_index=152)
        assert result[0] == (0, 0, 0, 0)

    def test_color_values_decoded(self):
        # color 1 = white (0x7FFF), color 2 = pure red (0x001F), color 3 = black (0x0000)
        pyboy = self._make_pyboy(2, [0x7FFF, 0x001F, 0x0000])
        result = read_mini_palette(pyboy, pokemon_index=152)
        assert result[1] == (255, 255, 255, 255)
        assert result[2] == (255, 0, 0, 255)
        assert result[3] == (0, 0, 0, 255)
