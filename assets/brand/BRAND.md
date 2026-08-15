# neurokeeper brand

## The mark: the graph that traces a check

Three nodes joined by two edges, knocked out of a solid tile, whose path forms a checkmark. It
encodes both halves of what the tool is: a knowledge graph, and the deterministic verification run
over it. The name splits the same way, `neuro` + `keeper`, and the wordmark follows that split.

Replaced (2026-08-15) a generic brain outline carrying a stock Material `autorenew` glyph. Rendered
rather than read, that mark said "cloud sync", which is close to the opposite of a local-first
deterministic tool, and the icon was recognisably off the shelf.

- `neurokeeper-mark.svg` is the MASTER. The lockups embed its geometry as a transformed copy; if
  the mark changes, regenerate them (they do not sync themselves).
- The knockout is a TRUE hole (`fill-rule="evenodd"`), so the check adopts the surface behind the
  mark: white on light pages, dark on dark pages. That adaptivity is intended and is why there is
  no separate dark mark.
- The hole is ONE unioned outline, not stacked circles and bars. Overlapping subpaths cancel under
  both fill rules, so stacked shapes re-fill notches inside every node. `src/gen_mark.py` unions
  the geometry before emitting the path.
- Always embed these as `<img>` references, never inline SVG markup: sanitizers strip accessibility
  attributes from inline SVG, while an image reference keeps the file intact.

## Tagline

**Knowledge, kept kempt.**

`kempt` is the word that survives inside `unkempt`: neatly kept, trim. It is the literal description
of what deterministic hygiene engines do to a knowledge base, so the third alliteration is exact
rather than decorative, which is what stops the line reading as a slogan.

Always with the comma. The pause makes it a statement; without it the three stresses run together
and it becomes a chant. Sentence case, full stop, never title case and never an exclamation mark.

It leads the package and marketplace descriptions but does not replace them: nobody searches a
registry for "kempt", so the functional text stays behind it.

## Palette

| Token | Value | Use |
|---|---|---|
| accent | `#10B981` | the tile, and "keeper" in the light wordmark |
| ink | `#334155` | "neuro" in the light wordmark |
| accent-dark | `#34D399` | "keeper" on dark surfaces |
| ink-dark | `#E2E8F0` | "neuro" on dark surfaces |
| social-inner | `#065F46` | social card radial, centre |
| social-outer | `#022C22` | social card radial, edge |

The tile keeps `accent` on both surfaces. Only the wordmark colours swap, so the mark stays one
recognisable object rather than two.

## Wordmark

Inter Bold (700), lowercase, tracking `-1.4`, two-tone split at `neuro|keeper`.

Shipped lockups have the text OUTLINED to paths, so they render identically everywhere including
GitHub, which loads no fonts for an SVG served as an image. The live-text masters in `src/` exist
for re-typesetting; paths do not reflow, so any text change means re-outlining.

The two halves are separate `<text>` elements rather than one element with a `<tspan>`, because the
outliner walks `<text>` nodes and does not descend into tspans. `src/gen_lockup.py` therefore
MEASURES the advance width of "neuro" from the font's own metrics to place the second half, instead
of hard-coding an offset that would silently drift if the size or tracking changed.

## Regenerating

```
uv run --with shapely   python src/gen_mark.py   neurokeeper-mark.svg
uv run --with fonttools python src/gen_lockup.py neurokeeper-mark.svg src/lockup-src.svg \
        "#334155" "#10B981" <Inter-700.ttf>
uv run --with fonttools python <brand-cycle>/scripts/outline_text.py \
        --svg src/lockup-src.svg --out neurokeeper-lockup.svg --font "inter=<Inter-700.ttf>"
```

Dark variant: same, with ink `#E2E8F0`, accent `#34D399`, and tile `#10B981` passed explicitly.

## Files

- `neurokeeper-mark.svg`: master mark, favicon-safe (verified legible at 24px, where it degrades to
  a check silhouette rather than to a generic blob)
- `neurokeeper-lockup.svg`: mark + wordmark, light surfaces
- `neurokeeper-lockup-dark.svg`: dark-surface variant, wordmark colours swapped, tile unchanged
- `neurokeeper-social.png`: 1280x640 GitHub social preview, dark lockup plus the tagline on an
  emerald radial. GitHub has no API for setting this; upload it under repo Settings, General,
  Social preview.
- `src/`: live-text masters and the generators for the mark, the lockups, and the social lockup.
  Note that the social source names the two weights as SEPARATE font families: the outliner maps a
  family to one file, so a single family name cannot resolve to both Inter 700 and Inter 500.
