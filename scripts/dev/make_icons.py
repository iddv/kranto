"""Generate Kranto's favicon and app icons from the mark geometry.

Draws the mark (a white lowercase "k" on an indigo rounded square) with
Pillow's ImageDraw at 4x supersampling, then downscales. No SVG renderer
is needed. Writes favicon-16/32/48.png, icon-180/192/512.png and a
multi-size favicon.ico (16, 32, 48).

Usage:
    python scripts/dev/make_icons.py [target_dir]

target_dir defaults to src/kranto/page/ui/static/brand. Requires Pillow.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

INDIGO = (0x3D, 0x44, 0xD4, 255)
WHITE = (255, 255, 255, 255)
SS = 4  # supersampling factor

# Geometry on a 64x64 grid; keep in sync with mark.svg.
RADIUS = 14
STEM = (16, 12, 24, 52)  # x0, y0, x1, y1
ARM = [(22, 38), (36, 24), (46, 24), (22, 48)]
LEG = [(29, 41), (34, 36), (50, 52), (40, 52)]


def render(size: int) -> Image.Image:
    big = size * SS
    s = big / 64
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=RADIUS * s, fill=INDIGO)
    x0, y0, x1, y1 = STEM
    d.rectangle((x0 * s, y0 * s, x1 * s - 1, y1 * s - 1), fill=WHITE)
    for poly in (ARM, LEG):
        d.polygon([(x * s, y * s) for x, y in poly], fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "src/kranto/page/ui/static/brand")
    out.mkdir(parents=True, exist_ok=True)
    for n in (16, 32, 48):
        render(n).save(out / f"favicon-{n}.png", optimize=True)
    for n in (180, 192, 512):
        render(n).save(out / f"icon-{n}.png", optimize=True)
    render(256).save(out / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print(f"wrote icons to {out}")


if __name__ == "__main__":
    main()
