"""GBC graphics decoding utilities for ROM sprite extraction."""

from __future__ import annotations


def decode_1bpp(data: bytes, width: int, height: int) -> list[list[int]]:
    """Decode 1bpp GB tile data into a 2D grid of palette indices (0-1).

    GB 1bpp tiles are 8x8 pixels. Each row is 1 byte, with bit 7 as the
    leftmost pixel and bit 0 as the rightmost pixel. Tiles are arranged
    left-to-right, then top-to-bottom.
    """
    tiles_x = width // 8
    tiles_y = height // 8
    grid = [[0] * width for _ in range(height)]
    tile_idx = 0
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            base = tile_idx * 8
            for row in range(8):
                byte = data[base + row]
                for col in range(8):
                    bit = 7 - col
                    grid[ty * 8 + row][tx * 8 + col] = (byte >> bit) & 1
            tile_idx += 1
    return grid


def decode_2bpp(data: bytes, width: int, height: int) -> list[list[int]]:
    """Decode 2bpp GBC tile data into a 2D grid of palette indices (0–3).

    GBC tiles are 8×8 pixels. Each row is 2 bytes:
      lo: LSB of each pixel's palette index
      hi: MSB of each pixel's palette index
    pixel_index = ((hi >> (7-col)) & 1) << 1 | ((lo >> (7-col)) & 1)
    Tiles are arranged left-to-right, then top-to-bottom.
    """
    tiles_x = width // 8
    tiles_y = height // 8
    grid = [[0] * width for _ in range(height)]
    tile_idx = 0
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            base = tile_idx * 16
            for row in range(8):
                lo = data[base + row * 2]
                hi = data[base + row * 2 + 1]
                for col in range(8):
                    bit = 7 - col
                    idx = ((hi >> bit) & 1) << 1 | ((lo >> bit) & 1)
                    grid[ty * 8 + row][tx * 8 + col] = idx
            tile_idx += 1
    return grid


def gbc_color_to_rgba(color15: int) -> tuple[int, int, int, int]:
    """Convert a 15-bit GBC RGB555 value to an RGBA tuple (alpha=255).

    GBC format: 0bbbbbgggggrrrrr
      bits  0–4: red
      bits  5–9: green
      bits 10–14: blue
    Each 5-bit channel is scaled to 8-bit: (c * 255) // 31.
    """
    r = (color15 & 0x1F) * 255 // 31
    g = ((color15 >> 5) & 0x1F) * 255 // 31
    b = ((color15 >> 10) & 0x1F) * 255 // 31
    return (r, g, b, 255)


def read_mini_palette(pyboy, pokemon_index: int) -> list[tuple[int, int, int, int]]:
    """Read a Pokemon's 4-color GBC palette from ROM.

    Follows Polished Crystal's logic for a plain,
    non-shiny species entry. For plain-form species, the palette table
    index collapses to the base species slot in PokemonPalettes.

    Args:
        pyboy: PyBoy instance with symbols loaded.
        pokemon_index: National Dex number (1-based, e.g. 152 for Chikorita).

    Returns:
        4 RGBA tuples. Index 0 is always transparent (alpha=0).

    """
    pp_bank, pp_addr = pyboy.symbol_lookup("PokemonPalettes")
    pal_base = pp_addr + (pokemon_index) * 8

    colors: list[tuple[int, int, int, int]] = [(255, 255, 255, 255)]  # index 0 = white, index 1 = black
    for i in range(0, 2):
        lo = pyboy.memory[pp_bank, pal_base + (i * 2)]
        hi = pyboy.memory[pp_bank, pal_base + (i * 2) + 1]
        colors.append(gbc_color_to_rgba(lo | (hi << 8)))
    colors.append((0, 0, 0, 255))

    return colors


def read_badge_palette(pyboy, bank: int, addr: int, badge_index: int) -> list[tuple[int, int, int, int]]:
    pal_base = addr + (badge_index) * 8

    colors: list[tuple[int, int, int, int]] = [(255, 255, 255, 255)]  # index 0 = white, index 1 = black
    for i in range(0, 2):
        lo = pyboy.memory[bank, pal_base + (i * 2)]
        hi = pyboy.memory[bank, pal_base + (i * 2) + 1]
        colors.append(gbc_color_to_rgba(lo | (hi << 8)))
    colors.append((0, 0, 0, 255))

    return colors
    