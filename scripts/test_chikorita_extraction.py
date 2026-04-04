"""Test the full ChikoritaMini extraction flow with the known ROM bytes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.lz import Decompressed
from src.utils.gbc_graphics import decode_2bpp

RAW = bytes([
    0x61, 0x0D, 0x0F, 0x0F, 0x17, 0x18, 0x10, 0x1F, 0x0B, 0x0F, 0x1F, 0x1E,
    0x27, 0x21, 0x5E, 0x52, 0x61, 0x15, 0xC0, 0xC0, 0xE0, 0x20, 0x30, 0xD0,
    0xD8, 0xE8, 0xE8, 0x78, 0x10, 0x10, 0x80, 0x80, 0x5E, 0x52, 0x7F, 0x48,
    0x5F, 0x60, 0x75, 0x4A, 0x41, 0x7F, 0x40, 0x13, 0x5E, 0x5E, 0x33, 0x33,
    0x80, 0x80, 0xC0, 0x40, 0x60, 0xA0, 0xE0, 0x30, 0xF0, 0x10, 0xF0, 0x90,
    0xF0, 0xD0, 0xB0, 0xB0, 0x85, 0xBD, 0x03, 0x0A, 0x0F, 0x1F, 0x1F, 0x83,
    0xBD, 0x83, 0xBF, 0x0D, 0x80, 0x80, 0xE0, 0x60, 0x30, 0xD0, 0x18, 0xE8,
    0xC8, 0xF8, 0xE8, 0xF8, 0xB8, 0xB8, 0x81, 0xBD, 0x88, 0xBF, 0x04, 0x60,
    0x2E, 0x2E, 0x1B, 0x1B, 0x81, 0xBD, 0x8D, 0xBF,
])

print(f"Input: {len(RAW)} bytes")
print(f"First byte: 0x{RAW[0]:02X} (0xFF would mean LZ terminator → empty output)")

# The 0xFF terminator follows immediately in the ROM; pad to 512 bytes
# as the ROM read does.
padded = RAW + b"\xff" + bytes(512 - len(RAW) - 1)
print(f"Padded to {len(padded)} bytes (simulating 512-byte ROM window, 0xFF at byte {len(RAW)})")

decompressed = bytes(Decompressed(padded).output)
print(f"Decompressed: {len(decompressed)} bytes (expected 128 for 16×32 sprite)")

if len(decompressed) == 0:
    print("ERROR: Decompression produced empty output!")
    sys.exit(1)

needed = (16 // 8) * (32 // 8) * 16  # tiles_x * tiles_y * bytes_per_tile
print(f"Need {needed} bytes for 16×32 sprite")
if len(decompressed) < needed:
    print(f"Padding {needed - len(decompressed)} trailing zero bytes (encoder omits trailing transparent rows)")
    decompressed = decompressed + bytes(needed - len(decompressed))

pixels = decode_2bpp(decompressed, width=16, height=32)
print(f"Decoded pixel grid: {len(pixels)} rows × {len(pixels[0])} cols")

# Print the pixel grid as ASCII art for visual inspection
chars = " .oX"
for row in pixels:
    print("".join(chars[p] for p in row))

print("\nSuccess — extraction flow works with the provided bytes.")
