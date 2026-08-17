---
title: Extend with your own engine
description: Ship a domain-specific engine from your own repository, first-class under the neurokeeper CLI, without forking the core.
tags:
  - how-to
---

> [!note] This recipe is for engines that do NOT belong in this repo
> The [[how-to/index|"Add a new engine" recipe]] covers adding a portable, domain-agnostic engine
> to the core. This page covers the other case, which is most cases: an engine that understands
> *your* ticket format, *your* approvals workflow, *your* document pipeline. The
> [substrate boundary ADR](https://github.com/Wombat164/neurokeeper/blob/main/docs/adr-0004-substrate-boundary.md)
> refuses that content upstream on purpose: the tiers, the vocabularies, the folder names belong to
> your collection, not to the tool. This seam exists so the refusal does not force you to fork.

Without a seam, a contributor with a genuinely useful, genuinely domain-specific engine has three
bad options: fork the repo (and inherit a merge burden forever), vendor a copy of the helpers (and
watch the copies drift until two tools disagree about the same note), or open a PR that will be
declined on scope grounds. The seam replaces all three: your engine lives in *your* repository,
imports the core's helpers as a normal dependency, and runs as `neurokeeper <your-engine>` beside
the built-ins.

---

## The seam: an engine search path

Set `NEUROKEEPER_ENGINE_PATH` to one or more directories (separated by `:` on POSIX, `;` on
Windows, i.e. your platform's `PATH` separator). Each directory holds single-file Python engines,
exactly the shape the built-ins use:

```bash
export NEUROKEEPER_ENGINE_PATH="$HOME/work/our-vault-tools/engines"
neurokeeper --list                    # built-ins, then external engines with their source dir
neurokeeper acme-owner-audit --json   # dispatches to $HOME/work/our-vault-tools/engines/acme-owner-audit.py
```

Resolution rules, all of which fail loudly rather than quietly:

- **The file stem is the engine name.** `acme-owner-audit.py` registers as `acme-owner-audit`.
  Kebab-case, like the built-ins.
- **Only files with a metadata header register.** A `.py` file without an `@capability` header at
  the top is not an engine, so a helper module sitting in the same directory does not become a
  phantom command. Files beginning with `_` are never engines either. `--list` does not enumerate
  what it ignored, which would bury the one file you care about under every helper beside it;
  instead, if you run an engine by a name that matches a header-less file, the error says so
  directly rather than only telling you the name is unknown.
- **A name collision with a built-in is a hard error**, not a silent preference in either
  direction. The dispatcher refuses to run and tells you to rename. Prefix your engines with your
  org or project name (`acme-owner-audit`, not `owner-audit`) and you will never collide: the core
  owns the bare namespace.
- **A path entry that does not exist is an error on any dispatch**, not a warning that scrolls
  past. A configured search path pointing at nothing is the classic silent failure this project's
  [principles](https://github.com/Wombat164/neurokeeper/blob/main/docs/principles.md) exist to
  refuse (P1: unreachable is not empty; P2: named is not the same as configured). If you set the
  variable, every entry must resolve.
- **An unknown engine name exits 2** and prints both the built-in list and every external
  directory that was searched, so "misconfigured path" and "typo in the name" are distinguishable
  from the message alone.

### What was rejected, and why

Three alternatives were considered and dropped. Recording them here so the next enthusiastic
session does not re-derive one as a good idea.

- **Python entry points** (a `neurokeeper.engines` group). The natural choice for a published
  plugin ecosystem, and the wrong one here. It requires the third party to package their engines
  and pip-install them, but the driving case is a private tree of scripts in a private repo that
  will never be a distributable package. Entry points also make discovery invisible: what runs
  depends on what happens to be installed in the active environment, and debugging "why is this
  engine (not) found" means introspecting installed distributions. The env var can coexist with an
  entry-point group later if a real packaged-plugin ecosystem emerges; nothing in this design
  blocks that.
- **A manifest file** (a registry of name-to-path entries in a config file). A second surface to
  keep in sync with the filesystem, and a stale manifest entry pointing at a moved file is
  precisely the silent-drift failure mode of P9. The directory *is* the manifest; there is nothing
  to fall out of sync.
- **A convention directory** (a blessed `~/.neurokeeper/engines/` scanned automatically). Implicit
  magic with no off switch, and it forces your engines out of your own repository into a
  tool-owned location, which breaks the whole point: your engines version alongside your config
  and your tests, in your tree. The env var subsumes it anyway: point it at any directory you
  like, including one inside your vault repo.

The env var wins on the project's own criterion: the fewest moving parts that still fail loudly
when misconfigured. It matches how everything else here is configured (`VAULT_ROOT`,
`FRONTMATTER_SCHEMA`, `CLAUDE_MEMORY_DIR` are all env vars), and it is one line to set, one line
to unset, and fully visible in `env | grep NEUROKEEPER`.

---

## The contract your engine must meet

An external engine is a first-class citizen exactly when it honours the same contract the
built-ins do. MUST items are load-bearing (the dispatcher, `doctor`, or the reader's trust depends
on them); SHOULD items make the engine pleasant rather than merely correct.

**MUST:**

- **The `@capability` metadata header** at the top of the file (see the worked example below and
  the [[reference/index|reference]]). It is what makes the engine discoverable, and it is where
  the engine declares its effect (`read-only` / `mutating`) and whether it participates in
  `doctor`.
- **The exit-code contract**: `0` = the engine reached its subject (clean, or advisory findings
  only), `1` = a real gate failed, `2` = required config not set, `3` = config set but the target
  is unreachable. The 2/3 distinction is not pedantry: "you did not configure it" and "you
  configured it and it points at nothing" are different states, and folding them together is how
  a mistyped path rolls up green. See the
  [doctor exit-semantics ADR](https://github.com/Wombat164/neurokeeper/blob/main/docs/adr-0002-doctor-exit-semantics.md).
- **`--json`**: a machine-readable report on stdout when asked. This is the seam that lets
  `doctor`, CI, and any LLM harness consume your engine without parsing prose.
- **Report by default; mutate only on `--apply`.** If your engine writes anything, the bare
  invocation must be a dry run. This is the safety model every recipe on this site assumes, and an
  external engine that violates it poisons trust in the whole command surface.
- **Kebab-case name with an org or project prefix**, so you stay out of the core's namespace.

**SHOULD:**

- **`--check`**: a gating mode for CI (exit 1 on findings) distinct from the default reporting
  mode. Required if you want the engine to *gate* the `doctor` roll-up.
- **Honour `VAULT_ROOT` and `VAULT_SCAN_EXCLUDE`** rather than inventing a second way to point at
  the collection. Use the helper walk and you get this for free.
- **Stay deterministic and offline.** No network fetch inside the engine: same input, same
  verdict, no third party's availability in the loop. An engine that fetches is fine as *your*
  tool, but it cannot join `doctor` (see below), for the reasons the substrate-boundary ADR gives.
- **Force UTF-8 output** (`force_utf8_stdout()` from the helpers) so `--json` survives a Windows
  console redirect.
- **If mutating**: route writes through `safe_write()` (symlink and path-traversal confinement)
  and honour `VAULT_FORBIDDEN_ZONES` via `in_forbidden_zone()`.
- **Emit the Findings IR** (`Finding` tuples) if you want SARIF or future output formats for free.

---

## The stable helper surface

Divergent copies of the same parser are how two tools come to disagree about one note. So the core
exposes one importable, stable module, `neurokeeper.lib`, and external engines import from it
instead of re-implementing:

```python
from neurokeeper.lib import (
    md_files,            # the markdown walk: yields (abspath, reldir), honours VAULT_ROOT + VAULT_SCAN_EXCLUDE
    split_frontmatter,   # (frontmatter_text, rest) or (None, text)
    parse_frontmatter,   # dict | None | {"__parse_error__": True}; carries the 64KB alias-bomb guard
    render_frontmatter,  # the WRITER: deterministic, insertion-ordered YAML frontmatter
    yaml_scalar,         # quote a single value only when leaving it bare would change its meaning
    find_links,          # wikilink / markdown-link extraction via the active backend; yields Link(target, anchor, alias, embed)
    kebabify,            # the code/acronym-preserving slug engine
    within_vault,        # is this path confined to the vault?
    safe_write,          # ATOMIC write guard: refuses symlinks and out-of-vault targets, optional zones
    in_forbidden_zone,   # honours VAULT_FORBIDDEN_ZONES
    force_utf8_stdout,   # cross-platform UTF-8 stdout/stderr
    Finding, to_sarif,   # the Findings IR + its SARIF renderer
    VAULT,               # the resolved collection root
)
```

That list is the stability promise: names and signatures in `neurokeeper.lib` change only with a
version bump and a changelog entry, because external engines are now consumers of them.

**What is NOT stable, stated plainly:** anything underscore-prefixed. `scripts/_vault_lib.py`,
`scripts/_backend.py`, `scripts/_findings.py`, `scripts/_substrate.py` and their siblings are
internal modules; the built-in engines import them through repo-local paths, and their contents
move without notice. The same goes for the internals of any built-in engine, and for JSON output
keys of other engines beyond what the reference documents. If you find yourself importing an
underscore module directly, you have left the supported surface: either the thing you need is
already re-exported by `neurokeeper.lib`, or it is a candidate to propose for export (a one-line
PR, and one the core will accept, because exporting an existing generic helper passes the
core-vs-plugin test below).

---

## Worked example: an owner-roster engine

A complete external engine: flag notes whose declared `owner` is not in a roster file. Generic in
mechanism, domain-specific in vocabulary (your roster, your `owner` field), which is exactly why it
belongs in your repo and not in the core.

`engines/acme-owner-audit.py` in your repository:

```python
#!/usr/bin/env python3
# @capability:  acme-owner-audit
# @compute:     deterministic
# @effect:      read-only
# @engine:      engines/acme-owner-audit.py
# @doctor:      gate
# @status:      active
"""Flag notes whose declared owner is not in the team roster.

Config: OWNER_ROSTER = path to a text file, one owner per line.
Exit: 0 scanned the vault; 1 --check and unknown owners found;
      2 OWNER_ROSTER not set; 3 OWNER_ROSTER set but unreadable.
"""
import json, os, sys
from neurokeeper.lib import md_files, parse_frontmatter, force_utf8_stdout

def main():
    force_utf8_stdout()
    as_json, check = "--json" in sys.argv, "--check" in sys.argv
    roster_path = os.environ.get("OWNER_ROSTER")
    if not roster_path:
        print("acme-owner-audit: OWNER_ROSTER not set (path to roster file)", file=sys.stderr)
        sys.exit(2)
    try:
        with open(roster_path, encoding="utf-8") as fh:
            roster = {line.strip() for line in fh if line.strip()}
    except OSError as e:
        print(f"acme-owner-audit: cannot read roster: {e}", file=sys.stderr)
        sys.exit(3)
    findings = []
    for path, reldir in md_files():
        with open(path, encoding="utf-8") as fh:
            fm = parse_frontmatter(fh.read())
        owner = (fm or {}).get("owner")
        if owner and str(owner) not in roster:
            findings.append({"path": path, "owner": str(owner)})
    if as_json:
        print(json.dumps({"engine": "acme-owner-audit",
                          "count": len(findings), "unknown_owners": findings}, indent=2))
    else:
        for f in findings:
            print(f"unknown owner '{f['owner']}': {f['path']}")
        print(f"acme-owner-audit: {len(findings)} note(s) with an owner not in the roster")
    sys.exit(1 if (check and findings) else 0)

if __name__ == "__main__":
    main()
```

Its config, `roster.txt` in your repository (one owner per line):

```
ada.lovelace
grace.hopper
alan.turing
```

And its invocation:

```bash
export VAULT_ROOT="/path/to/your/notes"
export NEUROKEEPER_ENGINE_PATH="/path/to/your-repo/engines"
export OWNER_ROSTER="/path/to/your-repo/roster.txt"

neurokeeper acme-owner-audit            # human report, exit 0
neurokeeper acme-owner-audit --json     # machine-readable
neurokeeper acme-owner-audit --check    # CI gate: exit 1 if any owner is off-roster
```

Note what the engine did *not* have to write: the vault walk, the exclusion rules, the frontmatter
parser with its hostile-input cap, the UTF-8 plumbing. Those are the helpers whose private copies
drift; here there is exactly one implementation, the core's.

---

## Joining the `doctor` roll-up

`doctor` is one command and one honest exit code over the read-only checks. An external engine can
join it, and the price of admission is being trustworthy inside an aggregate:

- **Declare it** in the header: `@doctor: gate` (findings can fail the roll-up) or
  `@doctor: advisory` (numbers contribute to the report, never to the exit code). No `@doctor`
  line means `doctor` ignores the engine.
- **Honour the tri-state.** `doctor` maps your exit codes onto ok / fail / skipped: exit 2
  ("not configured") becomes `skipped`, which is reported and never counted as a pass; exit 3
  ("configured and unreachable") becomes an *error that fails the roll-up*, because an operator
  who set the config turned the check on, and a check pointing at nothing must not roll up green.
- **Support `--check --json`.** Every participant is invoked with exactly those two flags,
  gating or advisory. `--json` is why flags are passed at all: an engine that returned only an exit
  code would be a pass/fail lamp in a report otherwise made of numbers, so print a JSON object with
  a `counts` key and it appears in the summary beside the built-ins.
- **Be read-only in that invocation and offline always.** `doctor` is a CI gate; a member that
  mutates, or that can fail because a remote service hiccupped, makes the whole gate untrustworthy
  and gets the whole gate bypassed.

An engine that meets the exit contract above meets almost all of this for free.

Two sharp edges, both of which report loudly rather than quietly:

- **An unrecognised flag is an error, not a skip.** `argparse` exits 2 when it rejects `--check`,
  and exit 2 already means "not configured". Left alone, an engine that never implemented the flags
  would appear in the report as a tidy skip while its entire subject went unchecked and the roll-up
  stayed green, so `doctor` distinguishes the two and reports the flag rejection as an error.
- **`advisory` plus exit 1 is a contract breach**, reported as an error rather than downgraded to
  `ok`. Otherwise an engine's only way of saying something is wrong would be swallowed by the
  participation level it declared for itself.

Each engine in the report carries an `origin` of `built-in` or `external`, because an operator
reading a health summary is entitled to know whose engine produced which finding.

---

## Where your engine's config lives

In *your* repository (versioned beside the engine, like `roster.txt` above) or in the consumer's
environment, pointed at by an env var that *your engine* owns (`OWNER_ROSTER` above). Exit 2 when
it is unset, exit 3 when it is set and unreadable, and say in one line how to set it.

It must **not** be added to this repo's `config.example/`. That directory documents the core's
engines, and an example config for your engine necessarily carries your organisation's shape (your
field names, your vocabulary, your roster format), which is exactly the content the substrate
boundary refuses upstream. It would also rot: nothing in this repo runs your engine, so nothing
here would ever notice the example drifting from reality, and an example that a person copies and
that silently does the wrong thing is a documented failure mode (principle P4). Ship the example
next to the engine, where its tests live.

---

## Should this be a plugin, or a PR to the core?

The test, in one sentence: **something belongs in the core if it is true of ANY sizeable
collection; it belongs in a plugin if it encodes one organisation's shape, format, or
vocabulary.**

Applied:

| Candidate | Verdict | Why |
|---|---|---|
| "Frontmatter can be malformed" | core | true of every collection; the parser and its guard are generic |
| "The `owner` field must match our roster" | plugin | the field convention and the roster are yours |
| "Wikilinks can point at deleted files" | core | every vault has links; `ref-audit` exists |
| "Our tickets embed an ID shaped like `TCK-1234`" | plugin | one org's identifier grammar |
| "A configured path that resolves to nothing must fail loudly" | core | a property of checking itself, not of any collection |
| "Notes in `reviews/` need an `approved-by` before `status: final`" | plugin | one org's workflow encoded in folders and fields |

Two refinements that cover most borderline cases:

- **Split the mechanism from the vocabulary.** A mechanism can be core while its vocabulary never
  is. "Validate frontmatter against a declared schema" is core (and exists:
  `frontmatter-lint`); the schema itself is yours. If your plugin engine is mostly a generic
  mechanism wrapped around a local vocabulary, the right PR upstream is the mechanism with the
  vocabulary as config, and the wrong PR is the pair.
- **A helper your engine had to re-implement is a core bug.** If you found yourself rewriting the
  markdown walk, the frontmatter parse, or link extraction because `neurokeeper.lib` does not
  export it, propose the export. Generic helpers pass the test by construction; that PR is
  welcome where the domain-specific engine around it is not.

## What must never be pushed upstream

From an external engine, regardless of how useful it is:

- your organisation's vocabularies, field conventions, folder tiers, and naming grammars;
- registers of people, teams, codes, or systems (the roster stays home);
- parsers for one organisation's document, ticket, or approval formats;
- example configs that would carry any of the above into `config.example/`;
- anything whose test fixtures would have to contain your real-world identifiers to be honest.

None of this is a judgement about quality. The engines this seam was designed for are substantial
and genuinely useful; they are also correctly unmergeable, because they answer questions that are
only questions inside one organisation. The seam exists so that "correctly unmergeable" and
"first-class citizen" can be true at the same time.
