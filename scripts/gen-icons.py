#!/usr/bin/env python3
"""
Generate placeholder Tauri icons using only Python stdlib.

Run once before `cargo tauri build`:
    python scripts/gen-icons.py

For a real release, replace with proper icons then re-run.
"""

import struct
import zlib
import pathlib

ICONS_DIR = pathlib.Path(__file__).parent.parent / "desktop" / "src-tauri" / "icons"

# OpenMarker brand color (blue)
COLOR = (74, 158, 255)


def make_png(width: int, height: int, color: tuple = COLOR) -> bytes:
    """Create a minimal solid-color PNG using only stdlib."""
    r, g, b = color
    # Each scanline: filter byte 0 (None) followed by RGB pixels
    raw = b"".join(b"\x00" + bytes([r, g, b] * width) for _ in range(height))
    compressed = zlib.compress(raw, level=9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return (
            struct.pack(">I", len(data))
            + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def make_ico(png_32: bytes) -> bytes:
    """Wrap a 32x32 PNG into a minimal ICO file (modern PNG-in-ICO format)."""
    header = struct.pack("<HHH", 0, 1, 1)
    img_offset = 6 + 16  # header + one directory entry
    entry = struct.pack("<BBBBHHII", 32, 32, 0, 0, 1, 32, len(png_32), img_offset)
    return header + entry + png_32


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    png_32 = make_png(32, 32)
    png_128 = make_png(128, 128)
    ico = make_ico(png_32)

    (ICONS_DIR / "32x32.png").write_bytes(png_32)
    (ICONS_DIR / "128x128.png").write_bytes(png_128)
    (ICONS_DIR / "icon.ico").write_bytes(ico)

    print(f"Icons written to {ICONS_DIR}")
    for f in sorted(ICONS_DIR.iterdir()):
        if f.suffix in (".png", ".ico"):
            print(f"  {f.name}  ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
