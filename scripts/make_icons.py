"""Make the app icon files from console/icons/tribunal.svg (run on a Mac, after changing the SVG).

    python3 scripts/make_icons.py

Writes next to the SVG:
    tribunal.icns      macOS app bundle (shortcut and Dock)            16 … 1024 px, the macOS icon grid
    tribunal.ico       Windows shortcut and window                    16 … 256 px, the plate filling more of the square
    tribunal-512.png   Linux application menu and the app window      512 px, like the .ico

Needs Google Chrome or Chromium to draw the SVG (headless, nothing is shown), and the macOS tools sips and iconutil.
The results are committed, so building or installing Tribunal never needs any of these.
"""
from __future__ import annotations

import base64
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "console" / "icons"
SVG = ICONS / "tribunal.svg"
TILE_VIEWBOX = 'viewBox="72 72 880 880"'          # Windows and Linux icons fill more of their square than macOS ones
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def chrome() -> str:
    for candidate in (os.environ.get("CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      "/Applications/Chromium.app/Contents/MacOS/Chromium", shutil.which("google-chrome"),
                      shutil.which("chromium")):
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("Google Chrome or Chromium is needed (or set CHROME to its program).")


def render(svg_text: str, out: Path, work: Path) -> None:
    """Draw the SVG at 1024 x 1024 on a transparent background."""
    data = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
    page = work / "icon.html"
    page.write_text('<!doctype html><html><body style="margin:0;background:transparent">'
                    f'<img src="data:image/svg+xml;base64,{data}" width="1024" height="1024" style="display:block">'
                    "</body></html>", encoding="utf-8")
    subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    "--default-background-color=00000000", "--window-size=1024,1024",
                    f"--user-data-dir={work / 'chrome'}", f"--screenshot={out}", page.as_uri()],
                   check=True, capture_output=True, timeout=120)


def scaled(src: Path, size: int, out: Path) -> Path:
    subprocess.run(["sips", "-z", str(size), str(size), str(src), "--out", str(out)], check=True, capture_output=True)
    return out


def write_ico(pngs: list, out: Path) -> None:
    """An .ico holding PNG images (Windows Vista and later read these at every size)."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries, blobs, offset = b"", b"", 6 + 16 * len(pngs)
    for size, path in pngs:
        blob = path.read_bytes()
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    out.write_bytes(header + entries + blobs)


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("Run this on a Mac: it uses sips and iconutil.")
    svg = SVG.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        mac_big, tile_big = work / "mac.png", work / "tile.png"
        render(svg, mac_big, work)
        render(svg.replace('viewBox="0 0 1024 1024"', TILE_VIEWBOX, 1), tile_big, work)

        iconset = work / "tribunal.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            scaled(mac_big, size, iconset / f"icon_{size}x{size}.png")
            scaled(mac_big, size * 2, iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ICONS / "tribunal.icns")], check=True)

        write_ico([(size, scaled(tile_big, size, work / f"ico-{size}.png")) for size in ICO_SIZES],
                  ICONS / "tribunal.ico")
        scaled(tile_big, 512, ICONS / "tribunal-512.png")
    for name in ("tribunal.icns", "tribunal.ico", "tribunal-512.png"):
        print(f"{name}: {(ICONS / name).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
