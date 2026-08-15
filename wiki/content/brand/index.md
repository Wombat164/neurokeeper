---
title: Brand
description: The neurokeeper logo, colours, and usage, with downloadable assets.
tags:
  - brand
---

> **Knowledge, kept kempt.**
>
> *Kempt* is the word that survives inside *unkempt*: neatly kept, trim. It is the literal
> description of what deterministic hygiene engines do to a knowledge base, and it happens to
> alliterate. Use the line with the comma; the pause is what keeps it a statement rather than a
> slogan.

The neurokeeper mark is **a graph that traces a check**: three nodes joined by two edges, knocked
out of a solid tile, whose path forms a checkmark. It carries both halves of what the tool is, a
knowledge graph and the deterministic verification run over it. The name splits the same way,
`neuro` and `keeper`, and the wordmark follows that split.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Wombat164/neurokeeper/main/assets/brand/neurokeeper-lockup-dark.svg">
    <img src="https://raw.githubusercontent.com/Wombat164/neurokeeper/main/assets/brand/neurokeeper-lockup.svg" alt="neurokeeper" width="380">
  </picture>
</p>

The knockout is a true hole, so the check adopts whatever surface sits behind the mark: white on
light pages, dark on dark ones. That is why there is no separate dark mark. Only the wordmark
colours swap between surfaces; the tile stays emerald, so the mark remains one recognisable object.

## Colours

| Role | Light | Dark |
|---|---|---|
| Accent (tile, and "keeper") | `#10B981` | `#34D399` |
| Ink ("neuro") | `#334155` | `#E2E8F0` |
| Social card radial | `#065F46` centre | `#022C22` edge |

## Usage

**Do**

- Keep clear space around the mark equal to the tile's corner radius.
- Embed the assets as image references. Inline SVG markup gets its accessibility attributes
  stripped by sanitizers; a file reference stays intact.
- Let the mark scale down to a favicon. At 24px the nodes merge into the strokes and it degrades to
  a check silhouette, which is still on message.

**Don't**

- Re-colour or rotate the tile, or fake the knockout by filling the check in the page background
  colour. The hole is real, and that is what makes the mark work on any ground.
- Re-typeset the wordmark without re-outlining it. The shipped lockups are paths, and paths do not
  reflow.
- Add shadows, bevels, or gradients to the mark.

## Downloads

All assets live in the repository under [`assets/brand/`](https://github.com/Wombat164/neurokeeper/tree/main/assets/brand),
alongside [`BRAND.md`](https://github.com/Wombat164/neurokeeper/blob/main/assets/brand/BRAND.md),
which records the master geometry, the palette, and how to regenerate everything.

- [Mark](https://github.com/Wombat164/neurokeeper/blob/main/assets/brand/neurokeeper-mark.svg) (SVG, surface-adaptive)
- [Lockup, light](https://github.com/Wombat164/neurokeeper/blob/main/assets/brand/neurokeeper-lockup.svg) (SVG)
- [Lockup, dark](https://github.com/Wombat164/neurokeeper/blob/main/assets/brand/neurokeeper-lockup-dark.svg) (SVG)
- [Social card](https://github.com/Wombat164/neurokeeper/blob/main/assets/brand/neurokeeper-social.png) (PNG, 1280x640)
