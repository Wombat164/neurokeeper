"""Social-card source: the lockup with the tagline set beneath the wordmark.

The two weights carry DIFFERENT font-family names because the outliner maps family -> font file,
so one name cannot resolve to both Inter 700 and Inter 500. Widths are measured from the fonts'
own advance tables so the viewBox fits whichever line is longer, rather than being guessed.
"""
import re
import sys

from fontTools.ttLib import TTFont

MARK, OUT, INK, ACCENT, TILE_FILL, MUTED, F700, F500 = sys.argv[1:9]

TAG = "Knowledge, kept kempt."
TILE, GAP, SIZE, TRACK = 72, 22, 47, -1.4
TAG_SIZE, TAG_TRACK = 21.5, -0.15
BASELINE, TAG_BASELINE = 63.5, 104
BOX_H = 124


def advance(font, text, size, track):
    upm = font["head"].unitsPerEm
    cmap, hmtx = font.getBestCmap(), font["hmtx"]
    total = 0
    for ch in text:
        name = cmap.get(ord(ch))
        if name is None:
            sys.exit(f"no glyph for {ch!r}")
        total += hmtx[name][0]
    return total * size / upm + track * len(text)


d = " ".join(re.search(r'\sd="([^"]+)"', open(MARK, encoding="utf-8").read(), re.S).group(1).split())
f700, f500 = TTFont(F700), TTFont(F500)

x0 = TILE + GAP
w_neuro = advance(f700, "neuro", SIZE, TRACK)
w_word = advance(f700, "neurokeeper", SIZE, TRACK)
w_tag = advance(f500, TAG, TAG_SIZE, TAG_TRACK)
width = round(x0 + max(w_word, w_tag) + 4)

print(f"  wordmark {w_word:.1f}u, tagline {w_tag:.1f}u -> viewBox {width}x{BOX_H}")

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {BOX_H}" role="img" aria-label="neurokeeper: knowledge, kept kempt">
  <title>neurokeeper</title>
  <g transform="translate(0 {(TILE - TILE) / 2:g}) scale({TILE / 64:g})">
    <path fill="{TILE_FILL}" fill-rule="evenodd" d="{d}"/>
  </g>
  <text x="{x0}" y="{BASELINE}" font-family="inter" font-weight="700" font-size="{SIZE}" letter-spacing="{TRACK}" fill="{INK}">neuro</text>
  <text x="{x0 + w_neuro:.1f}" y="{BASELINE}" font-family="inter" font-weight="700" font-size="{SIZE}" letter-spacing="{TRACK}" fill="{ACCENT}">keeper</text>
  <text x="{x0}" y="{TAG_BASELINE}" font-family="intertag" font-weight="500" font-size="{TAG_SIZE}" letter-spacing="{TAG_TRACK}" fill="{MUTED}">{TAG}</text>
</svg>
'''
open(OUT, "w", encoding="utf-8").write(svg)
print(f"  wrote {OUT}")
