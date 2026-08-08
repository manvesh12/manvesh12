#!/usr/bin/env python3
"""Generate a self-typing ASCII portrait from Manvesh's public GitHub avatar.

This is a one-off authoring tool, not part of the nightly workflow. It needs
Pillow (`pip install pillow`) and writes no runtime dependency into the README.
"""

from __future__ import annotations

import argparse
import json
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
RAMP = " .`:-=+*cs#%@"
COLS = 74
FONT_SIZE = 12.4
CHAR_WIDTH = 7.44
LINE_HEIGHT = 14.6
ROW_DELAY = .075
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"


def load_avatar() -> Image.Image:
    request = Request("https://avatars.githubusercontent.com/manvesh12?size=920",
                      headers={"User-Agent": "manvesh12-profile-portrait"})
    with urlopen(request, timeout=30) as response:
        return Image.open(BytesIO(response.read())).convert("RGB")


def prepare(image: Image.Image) -> Image.Image:
    width, height = image.size
    # The current avatar is a waist-up outdoor portrait. This relative crop keeps
    # the turban, face, and jaw while discarding the visually noisy background.
    crop = (int(width * .34), int(height * .34),
            int(width * .66), int(height * .71))
    image = image.crop(crop)
    width, height = image.size

    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    points = [(width * .24, height * .07), (width * .39, height * .01),
              (width * .62, height * .02), (width * .79, height * .12),
              (width * .86, height * .34), (width * .79, height * .68),
              (width * .65, height * .94), (width * .37, height * .94),
              (width * .21, height * .68), (width * .14, height * .34)]
    draw.polygon(points, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(1, width // 90)))

    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.10)
    # Keep mid-tones open enough for eyes, moustache, and jaw edges to survive
    # the character ramp; the turban remains the portrait's darkest mass.
    gray = gray.point(lambda value: int(255 * (value / 255) ** .90))
    white = Image.new("L", image.size, 255)
    return Image.composite(gray, white, mask)


def ascii_lines(image: Image.Image) -> list[str]:
    width, height = image.size
    rows = max(1, int(COLS * (height / width) * .48))
    image = image.resize((COLS, rows), Image.Resampling.LANCZOS)
    pixels = list(image.getdata())
    lines = []
    for row in range(rows):
        line = "".join(
            RAMP[min(len(RAMP) - 1,
                     int((1 - pixels[row * COLS + column] / 255) * len(RAMP)))]
            for column in range(COLS)
        ).rstrip()
        lines.append(line)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def build_svg(lines: list[str]) -> str:
    pad = 14
    width = int(COLS * CHAR_WIDTH + pad * 2)
    height = int(len(lines) * LINE_HEIGHT + pad * 2)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{MONO}">',
        '<style>.ink{fill:#59636e}.cursor{fill:#7a263a}'
        '@media(prefers-color-scheme:dark){.ink{fill:#c9d1d9}.cursor{fill:#ff9eb1}}'
        '</style>',
    ]
    for index, line in enumerate(lines):
        y = pad + index * LINE_HEIGHT
        begin = index * ROW_DELAY
        finish = (index + 1) * ROW_DELAY
        row_width = max(len(line), 1) * CHAR_WIDTH
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(
            f'<clipPath id="row-{index}"><rect x="{pad}" y="{y:.1f}" '
            f'height="{LINE_HEIGHT}" width="0"><animate attributeName="width" '
            f'from="0" to="{row_width:.1f}" begin="{begin:.3f}s" dur="{ROW_DELAY}s" '
            f'fill="freeze"/></rect></clipPath>'
            f'<g clip-path="url(#row-{index})"><text xml:space="preserve" x="{pad}" '
            f'y="{y + 11:.1f}" class="ink" font-size="{FONT_SIZE}" '
            f'textLength="{row_width:.1f}" lengthAdjust="spacingAndGlyphs">{safe}</text></g>'
            f'<rect y="{y + 1:.1f}" width="5" height="11.5" class="cursor" opacity="0">'
            f'<animate attributeName="x" from="{pad}" to="{pad + row_width:.1f}" '
            f'begin="{begin:.3f}s" dur="{ROW_DELAY}s" fill="freeze"/>'
            f'<set attributeName="opacity" to=".78" begin="{begin:.3f}s"/>'
            f'<set attributeName="opacity" to="0" begin="{finish:.3f}s"/></rect>'
        )
    parts.append("</svg>")
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-json", action="store_true")
    args = parser.parse_args()
    svg = build_svg(ascii_lines(prepare(load_avatar())))
    if args.emit_json:
        print(json.dumps({"assets/ascii.svg": svg}, ensure_ascii=False))
    else:
        target = ROOT / "assets" / "ascii.svg"
        target.write_text(svg, encoding="utf-8", newline="\n")
        print(f"wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
