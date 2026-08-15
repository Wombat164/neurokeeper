# `correlate` -- correlate external items against vault notes

`scripts/vault-correlate.py` answers one question, deterministically and with its working shown:
**does this vault already have a note about this thing?**

The "thing" is any external item reduced to a small envelope, so the engine never needs to know what
produced it. A mail, a ticket, a meeting transcript and a PDF all correlate the same way.

Read-only. It never writes into the vault.

## Input

One object or a list, on stdin or via `--item-file`:

```json
{"id": "42",
 "title": "Re: Widget Programme timeline",
 "body": "first 4k characters are enough",
 "participants": ["ada.lovelace@example.org", "Grace Hopper <grace@example.org>"],
 "codes": ["PROJ-1"],
 "date": "2026-08-05"}
```

Only `title` is really required. Everything else sharpens the result.

## Output

```json
{"vault": "...", "index": {"notes": 1660, "parsed": 12, "cached": 1648},
 "items": [{"id": "42", "state": "anchored", "score": 75, "capped": false,
            "candidates": [{"note": "02 - Projects/widget-programme.md", "score": 75,
                            "evidence": ["code PROJ-1", "phrase 'widget programme'"]}]}]}
```

## States

| State | Meaning |
|---|---|
| `anchored` | >= 70 on one note. The vault already covers this. |
| `correlated` | 40-69. Right neighbourhood; the candidate list is the useful part. |
| `ambiguous` | Top two candidates are close **and** point at genuinely different subjects. |
| `topic-known` | A code matched, but no note reached 40. |
| `new` | Below 40, no code. The vault has not seen this. |

`ambiguous` is deliberately narrow. Two notes from the same dossier scoring alike is corroboration,
not ambiguity, so candidates count as different subjects only when they share no code and no tag,
neither links to the other, and they sit in different top-level folders. Without that test almost
everything in a real vault reads as ambiguous, which is the same as flagging nothing.

## Signals

| Signal | Points |
|---|---|
| Shared code (`contract`, `project`, `programme`, ...) | 40 |
| A note's title or alias appearing verbatim in the item | 35 |
| IDF-weighted token overlap against title + aliases | up to 25 |
| A participant resolving to a person the note names | 20 |
| A shared tag | 10 |

**The anchor floor.** No signal below 30 may produce an `anchored` verdict on its own. A pile of weak
token hits gets capped at 69 with `capped: true` and an evidence line saying so. Filename-substring
matching without this rule is exactly how a correlator starts confidently attaching items to the
wrong note.

**Why IDF.** A token appearing in 200 note titles carries almost no information; a rare one is nearly
decisive. Raw token counting treats them identically, which is the classic failure of this kind of
matcher. Document frequency is computed across the indexed titles and aliases, so the weighting
adapts to the vault rather than to a hand-written stopword list (there is a small stopword set too,
for words that are noise in any vault).

A single-note vault makes every IDF zero, which is correct (nothing discriminates) but would divide by
zero; the normaliser falls back to 1.0 and token overlap simply contributes nothing, leaving the
phrase, code and person signals to carry the result.

## It reads your frontmatter schema

The vault's schema-as-code is the declared source of truth for what keys mean, and it is the same file
`frontmatter-lint` validates against. The engine reads it so a vault that renames an axis does not keep
linting clean while silently correlating worse.

Resolution: `--schema`, else `$FRONTMATTER_SCHEMA`, else `<vault>/.claude/data/frontmatter-schema.yaml`.
`--no-schema` opts out. A missing or broken schema is a warning, never a failure.

What is taken from it, and what deliberately is not:

| Schema element | Used as | Why |
|---|---|---|
| `axes.<name>` with `open: true` | a topical signal, like a tag | free vocabulary; carries subject matter |
| `axes.<name>` with `values: [...]` | **ignored** | a classifier: `note_type: note` is true of nearly every note, so it discriminates nothing |
| `state` (status / maturity / horizon) | **ignored** | lifecycle, not subject matter |
| `correlate:` block (optional) | role key names | see below |

The schema has no vocabulary for *which key holds a dossier code* or *which key names people*, which
are the two roles correlation leans on hardest. Rather than keep a second private map, a vault can
declare them in the schema and keep one file authoritative:

```yaml
# in your frontmatter-schema.yaml
correlate:
  codes:   [contract, programme, dossier_ref]
  people:  [attendees, stakeholders, owner]
  aliases: [aliases]
```

Only the roles in `DEFAULT_FM_MAP` are accepted there; an unknown role name warns and is ignored.

**Precedence, weakest first:** engine defaults, then the schema, then `--config`'s
`vault.frontmatter_map`, then CLI flags.

## Vault-form agnosticism

The engine has no knowledge of specific folder names, frontmatter keys or codes. Notes are read
through a frontmatter **map**, so an Obsidian vault, a Logseq graph and a flat folder of plain
markdown all work. With no frontmatter at all, the title falls back to the filename stem and
correlation runs on phrase and token signals alone: it degrades, it does not fail.

```yaml
# passed via --config
vault:
  include: ["02 - Projects", "03 - Domains", "MOC"]
  frontmatter_map:
    title:   [title]
    aliases: [aliases, alias]        # Logseq uses `alias`
    tags:    [tags]
    codes:   [code, contract, project, programme, ref]
    people:  [attendees, stakeholders, owner, recipient]
```

Any field you omit keeps its default. `--include` on the command line overrides the config.

## Usage

```bash
# whole vault
echo '{"id":"1","title":"Re: Widget Programme"}' | neurokeeper correlate

# scoped, with index stats on stderr
neurokeeper correlate --include "02 - Projects" --include MOC --stats --item-file items.json

# force a full reparse
neurokeeper correlate --refresh
```

`VAULT_ROOT` selects the vault (or `--vault`). `VAULT_SCAN_EXCLUDE` applies as for every engine.

## Cache

The note index is cached at `--cache` (default `.vault-correlate-cache.json`), keyed on
`(relpath, mtime, size)` per note, so a re-run only reparses what changed. The cache is invalidated
wholesale when the frontmatter map or the cache version changes. `--stats` reports the parsed/cached
split; `--refresh` ignores it.

Only the frontmatter block is parsed at index time, not the whole note body, which is what keeps a
full-vault index cheap.

## Limits

- Correlation is scored from titles, aliases, codes, tags and named people. A note whose title
  says nothing about its subject matter will read as `new`. Treat `new` as "look at this", not as
  proof of absence.
- No thread memory: each item is scored independently. Correlating a reply chain consistently is a
  caller concern for now.
- No link-graph reinforcement between candidates yet, beyond the `unrelated()` test.
- No embeddings. Paraphrase recall (an item that describes a dossier without using any of its words)
  is out of reach for the deterministic tier by construction.
