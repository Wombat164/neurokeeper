"""Compose the lockup from the MASTER mark geometry, so the two can never drift apart.

Two-tone split at neuro|keeper, the same morpheme device the sibling projects use (render|fact),
where the second half carries the accent.

The halves are two separate <text> elements rather than one with a <tspan>: the outliner walks
<text> nodes and does not descend into tspans, so a tspan is outlined as literal markup. That
means the second half needs an explicit x, so its offset is MEASURED from the font's own advance
widths rather than guessed.
"""
import re
import sys

from fontTools.ttLib import TTFont

MARK, OUT, INK, ACCENT, FONT = sys.argv[1:6]
# Tile colour is independent of the wordmark accent: on the dark variant the wordmark lightens for
# contrast while the tile stays constant, so the mark is one recognisable object on either surface.
TILE_FILL = sys.argv[6] if len(sys.argv) > 6 else ACCENT

TILE = 72
GAP = 22
SIZE = 47
TRACK = -1.4          # letter-spacing, matched in the SVG below
BOX_H = 96
BASELINE = 63.5


def advance(font, text, size, track):
    """Width of `text` in user units, including per-character tracking."""
    upm = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    total = 0
    for ch in text:
        name = cmap.get(ord(ch))
        if name is None:
            sys.exit(f"font has no glyph for {ch!r}")
        total += hmtx[name][0]
    return total * size / upm + track * len(text)


d = re.search(r'\sd="([^"]+)"', open(MARK, encoding="utf-8").read(), re.S).group(1)
d = " ".join(d.split())

f = TTFont(FONT)
x0 = TILE + GAP
w_first = advance(f, "neuro", SIZE, TRACK)
w_all = advance(f, "neurokeeper", SIZE, TRACK)
width = round(x0 + w_all + 4)

y = (BOX_H - TILE) / 2
scale = TILE / 64

print(f"  measured: 'neuro' = {w_first:.1f}u, full = {w_all:.1f}u, viewBox width {width}")

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {BOX_H}" role="img" aria-label="neurokeeper">
  <title>neurokeeper</title>
  <g transform="translate(0 {y:g}) scale({scale:g})">
    <path fill="{TILE_FILL}" fill-rule="evenodd" d="{d}"/>
  </g>
  <text x="{x0}" y="{BASELINE}" font-family="inter" font-weight="700" font-size="{SIZE}" letter-spacing="{TRACK}" fill="{INK}">neuro</text>
  <text x="{x0 + w_first:.1f}" y="{BASELINE}" font-family="inter" font-weight="700" font-size="{SIZE}" letter-spacing="{TRACK}" fill="{ACCENT}">keeper</text>
</svg>
'''
open(OUT, "w", encoding="utf-8").write(svg)
print(f"  wrote {OUT}")
