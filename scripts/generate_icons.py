# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Render PulseDeck's original application icon in every size the installers need.

Outputs (in src/pulsedeck/assets/icons/):
  pulsedeck-<size>.png  for 16..1024
  pulsedeck.ico         Windows (multi-resolution)
  pulsedeck.icns        macOS
  pulsedeck.svg         vector source (Linux desktop entry)

The design - a rounded tile with a ring and a heartbeat-style pulse line - is
original artwork created for this project and released under the MIT License.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "pulsedeck" / "assets" / "icons"
BG_TOP = (28, 33, 43)
BG_BOTTOM = (10, 13, 18)
ACCENT = (58, 214, 160)
RING = (70, 82, 100)
PULSE = [(0.14, 0.52), (0.36, 0.52), (0.43, 0.30), (0.52, 0.74), (0.60, 0.40), (0.66, 0.52), (0.86, 0.52)]

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#1c212b"/><stop offset="1" stop-color="#0a0d12"/>
    </linearGradient>
  </defs>
  <rect x="16" y="16" width="480" height="480" rx="108" fill="url(#bg)"/>
  <circle cx="256" cy="266" r="150" fill="none" stroke="#465264" stroke-width="18"/>
  <polyline points="{points}" fill="none" stroke="#3ad6a0" stroke-width="30"
            stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def render(size: int) -> Image.Image:
    scale = 4  # supersample for smooth edges
    s = size * scale
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (s, s))
    draw_g = ImageDraw.Draw(gradient)
    for y in range(s):
        t = y / max(1, s - 1)
        color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)) + (255,)
        draw_g.line([(0, y), (s, y)], fill=color)
    mask = Image.new("L", (s, s), 0)
    margin = int(s * 0.03)
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, s - margin, s - margin], radius=int(s * 0.21), fill=255)
    image.paste(gradient, (0, 0), mask)
    draw = ImageDraw.Draw(image)
    if size >= 32:
        r = s * 0.293
        cx, cy = s / 2, s * 0.52
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RING + (255,), width=max(2, int(s * 0.035)))
    points = [(x * s, y * s) for x, y in PULSE]
    width = max(3, int(s * (0.075 if size < 32 else 0.058)))
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(glow).line(points, fill=ACCENT + (110,), width=width * 3, joint="curve")
    image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(s * 0.02)))
    draw = ImageDraw.Draw(image)
    draw.line(points, fill=ACCENT + (255,), width=width, joint="curve")
    for x, y in (points[0], points[-1]):
        draw.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=ACCENT + (255,))
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    images = {}
    for size in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        images[size] = render(size)
        images[size].save(OUT / f"pulsedeck-{size}.png", optimize=True)
    images[256].save(OUT / "pulsedeck.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    images[1024].save(OUT / "pulsedeck.icns")
    points = " ".join(f"{x * 512:.0f},{y * 512:.0f}" for x, y in PULSE)
    (OUT / "pulsedeck.svg").write_text(SVG.format(points=points), encoding="utf-8")
    print(f"Icons written to {OUT}")


if __name__ == "__main__":
    main()
