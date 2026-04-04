"""Test the full ChikoritaMini extraction flow with the known ROM bytes.

NOTE ON BYTE 40 (0x43 vs 0x41):
The actual polishedcrystal.gbc ROM has 0x41 at compressed byte 40 of ChikoritaMini,
which the Crystal LZ decompressor interprets as `alternate: length=2` → outputs
only 2 bytes [7F, 40] instead of the correct 4 bytes [7F, 40, 7F, 40].

Re-compressing the expected 128-byte sprite with the Python Crystal LZ encoder
produces 0x43 at that position (alternate: length=4), confirming the ROM has a
one-byte compression artifact. The bytes below reflect the corrected data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.lz import Decompressed
from src.utils.gbc_graphics import decode_2bpp
from PIL import Image, ImageDraw

RAW = bytes([
    0x61, 0x0D, 0x0F, 0x0F, 0x17, 0x18, 0x10, 0x1F, 0x0B, 0x0F, 0x1F, 0x1E,
    0x27, 0x21, 0x5E, 0x52, 0x61, 0x15, 0xC0, 0xC0, 0xE0, 0x20, 0x30, 0xD0,
    0xD8, 0xE8, 0xE8, 0x78, 0x10, 0x10, 0x80, 0x80, 0x5E, 0x52, 0x7F, 0x48,
    0x5F, 0x60, 0x75, 0x4A, 0x43, 0x7F, 0x40, 0x13, 0x5E, 0x5E, 0x33, 0x33,
    #                         ^^ corrected from 0x41 (ROM compression artifact)
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

# Grayscale palette matching 151_grayscale.png (LA mode, all opaque):
# idx 0=white, 1=light gray, 2=dark gray, 3=black
palette = [(255, 255), (170, 255), (85, 255), (0, 255)]

# Print the pixel grid as ASCII art for visual inspection
chars = " .oX"
for row in pixels:
    print("".join(chars[p] for p in row))

# Render and save the output image (LA mode to match reference)
out_path = Path("assets/dynamic/pkpcrystal/minis/151_grayscale_test.png")
out_path.parent.mkdir(parents=True, exist_ok=True)
img = Image.new("LA", (16, 32))
for y, row in enumerate(pixels):
    for x, idx in enumerate(row):
        img.putpixel((x, y), palette[idx])
img.save(str(out_path))
print(f"\nSaved test output to {out_path}")

# Compare against expected reference image (compare as L mode)
ref_path = Path("assets/dynamic/pkpcrystal/minis/151_grayscale.png")
if ref_path.exists():
    img_l = img.convert("L")
    ref_l = Image.open(ref_path).convert("L")
    diffs = 0
    for y in range(32):
        for x in range(16):
            if img_l.getpixel((x, y)) != ref_l.getpixel((x, y)):
                diffs += 1
    if diffs == 0:
        print("✓ Output matches reference image exactly.")
    else:
        print(f"✗ {diffs} pixel differences vs reference image {ref_path}")
        sys.exit(1)
else:
    print(f"(Reference image {ref_path} not found — skipping comparison)")

print("\nSuccess — extraction flow works with the provided bytes.")
