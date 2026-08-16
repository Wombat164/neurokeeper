---
title: Reference
description: Engine catalog, the metadata-header spec, and environment configuration.
tags:
  - reference
---

> [!note] This is reference (information-oriented)
> Dry, look-it-up technical description. It describes *what is*; it does not teach (see
> [Tutorials](../tutorials/)) or walk you through a task (see [How-to guides](../how-to/)).

## Conventions used in the catalog

- **CLI name** - the dispatcher subcommand: `neurokeeper <name> [args]`.
- **compute x effect** - the [[explanation/index|capability typology]]: *compute* is
  `deterministic` / `llm` / `hybrid`; *effect* is `read-only` / `mutating`.
- **Universal contract** - every engine supports `--json` (machine-readable output) and meaningful
  exit codes, and is **report-by-default**. Mutating engines write only with `--apply`, and bulk vault
  writes refuse to run while a notes app is open unless given `--force`.

---

## Engine catalog

### `taxonomy-inventory`
- **compute x effect:** deterministic x read-only
- **What it does:** produces an inventory of a notes vault's filename conventions, tags, and frontmatter
  fields. The grounding read-only pass before any reconciliation.
- **Contract:** `--json`.
- **Env:** `VAULT_ROOT`, `VAULT_SCAN_EXCLUDE`.

### `correlate`
- **compute x effect:** deterministic x read-only
- **What it does:** answers *does this vault already have a note about this thing?* for any external
  item - a mail, a ticket, a meeting transcript, a PDF - reduced to a small envelope
  (`title`, `body`, `participants`, `codes`, `date`) fed in as JSON. Scores every plausible note from
  shared codes (40), a title or alias appearing verbatim in the item (35), IDF-weighted token overlap
  (up to 25), a participant resolving to a person the note names (20), and shared tags (10), then
  returns the top candidates with their evidence.
- **States:** `anchored` (>=70) | `correlated` (40-69) | `weak` (40+ but no single signal >=30) | `ambiguous` | `topic-known` | `new`.
- **The anchor floor:** no signal below 30 may anchor on its own. A pile of weak token hits is capped
  at 69 and says so in its evidence - unbounded substring matching is how a correlator starts
  confidently attaching items to the wrong note.
- **Why IDF:** a token in 200 note titles carries almost no information, a rare one is nearly
  decisive; raw token counting treats them the same. Document frequency is measured against the vault
  being indexed, so the weighting adapts rather than relying on a fixed stopword list.
- **Reads your schema:** the same frontmatter schema-as-code that `frontmatter-lint` validates against
  (`--schema`, else `$FRONTMATTER_SCHEMA`, else `<vault>/.claude/data/frontmatter-schema.yaml`;
  `--no-schema` opts out). Axes declared `open: true` hold free topical vocabulary and fold into the
  tag signal; axes with an enumerated `values` list are classifiers (`note_type: note` is true of
  almost every note) and are deliberately ignored, as is `state` (lifecycle, not subject matter). The
  schema has no vocabulary for *which key holds a dossier code* or *which key names people* - the two
  roles correlation leans on hardest - so a vault may declare them in an optional `correlate:` block
  and keep one file authoritative. Precedence: engine defaults < schema < `--config` < CLI flags.
- **Vault-form agnostic:** notes are read through a frontmatter *map* (`--config`), so Obsidian,
  Logseq (`alias`) and a flat folder of plain markdown all work. With no frontmatter, the title falls
  back to the filename stem and correlation runs on phrase + token signals: it degrades, it does not
  fail.
- **Contract:** JSON on stdin (or `--item-file`), JSON on stdout. `--top` sets how many candidates
  each item returns (default 3); `--include` limits the scan to given relative dirs (repeatable,
  overrides the config); `--config` supplies the `vault:` section (include + frontmatter map);
  `--vault` selects the vault root; `--register` supplies a YAML carrying `identifier_patterns` --
  record-number shapes (orders, tickets, stock numbers) matched in BOTH the item's text and each
  note's text, so neither side has to declare anything in frontmatter. `--list-records` dumps that
  index instead of correlating (`--pattern` limits it to one), which is the supported way to answer
  "where does this number appear": it reads the same index the matching uses, so a search and a
  match cannot disagree.
  The index is cached per note on `(relpath, mtime, size)` **plus the pattern set** at
  `--cache`; `--stats` shows the parsed/cached split and `--refresh` ignores the cache.
- **Env:** `VAULT_ROOT`, `VAULT_SCAN_EXCLUDE`. **Details:** `docs/engine-vault-correlate.md`.

### `ref-audit`
- **Enforcement scoping (since 2026-08-16):** `--since <ref>`, `--baseline <file>` and `--staged`
  are one family. `--staged` scopes findings to the git INDEX: what this commit would introduce.
  Applying a new rule to a mature collection otherwise produces hundreds of day-one findings, a
  reader stops at the third stale one, and the check gets switched off.
- **Out-of-scope findings are COUNTED, never discarded.** The report carries
  `pre_existing_out_of_scope` and the human output names it, because a scoped run that prints
  nothing reads as a clean collection and ambushes whoever runs unscoped later. `doctor` accepts
  and forwards `--staged` too.
- **compute x effect:** deterministic x read-only
- **What it does:** audits reference integrity across the vault - unresolved links, orphans (no inbound),
  dead-ends (no outbound), broken `.canvas` and `.base` file references, orphan media (attachments
  referenced by nothing), and exact name/stem collisions (a duplicated note basename makes a bare
  `[[stem]]` link ambiguous). The read-only counterpart to `name-reconcile`. Unresolved wikilinks are
  **informational by default** (they are often intentional forward-links to not-yet-created notes);
  broken `.canvas`/`.base` refs are always real defects.
- **Since 2026-07-04:** also resolves `[[note#heading]]` / `[[note#^block]]` anchors (broken anchors
  reported informationally: the file resolves but the heading/block does not exist) and reports the
  **isolated** set (notes that are both orphan AND dead-end, i.e. fully disconnected).
- **Contract:** `--json`, `--check` (exit 1 on broken canvas/base refs), `--strict` (also fail on
  unresolved links), and `--since <git-ref>` (report only findings for notes changed since the ref;
  the scan stays graph-global, only the surfaced findings and the `--check` gate are narrowed, so it
  is ideal for a pre-commit / CI diff run). A bad ref or non-git tree exits 2 rather than silently
  scanning the wrong scope.
- **Baseline (adopt on a dirty vault):** `--write-baseline <file>` records the current findings as
  accepted (then exits 0); `--baseline <file>` reports only NET-NEW findings and gates `--check` on
  them, so a 5-year vault can turn the tool on from day one and only fail on debt it *adds*. Findings
  are fingerprinted by semantic identity (a broken link keys on its missing target, not the source
  path), so a note rename does not resurrect the baseline. The human output nags with how many
  baselined findings are now resolved, so the baseline shrinks instead of ossifying.
- **SARIF / Findings IR:** `--sarif` emits findings as SARIF 2.1.0 for GitHub code-scanning, rendered
  from the canonical **Findings IR** (`scripts/_findings.py`: `(engine, rule, severity, path, line,
  message, fingerprint)`) that every engine can share, so new formats (JUnit, a Bases view) become thin
  renderers rather than per-engine serializers. It composes with `--since` / `--baseline` (the SARIF
  reflects the scoped set) and reuses the baseline fingerprints as SARIF `partialFingerprints`.
- **Env:** `VAULT_ROOT`, `VAULT_REFAUDIT_EXCLUDE`.

### `doctor`
- **compute x effect:** deterministic x read-only
- **What it does:** aggregate health - runs every *applicable* read-only engine (taxonomy-inventory,
  ref-audit, and - when their config is present - frontmatter-lint, memory-consolidate), prints one
  consolidated report, and rolls up an **honest** exit code. Each engine is reported as `ok` / `fail` /
  `skipped`; an engine whose required config is absent is **skipped, never silently counted as a pass**.
  The exit asserts *"an engine errored or a real gate failed"* - NOT *"the vault is healthy"*: advisory
  engines (taxonomy-inventory, frontmatter-lint) contribute numbers but cannot fail the roll-up. The CI
  entrypoint for the pre-commit / GitHub-Action adapters. See [ADR-0002](https://github.com/Wombat164/neurokeeper/blob/main/docs/adr-0002-doctor-exit-semantics.md).
- **Contract:** `--json`, `--check` (exit 1 iff a gating engine failed or any engine errored),
  `--strict` and `--since <git-ref>` (both forwarded to ref-audit; `--since` narrows the reported
  findings and the gate to notes changed since the ref).
- **Run-receipt (since 2026-07-04):** every run emits a `receipt` (`tool`, `version`, `root`,
  `files_scanned`, `engines_run`, `duration_ms`) as a `--json` field and as the header line of the human
  report. A run that scanned 0 files or the wrong root is then visible at a glance instead of passing as a
  silent green, the failure class the byte-cap and walk-exclude drifts fell into.
- **Env:** the union of the engines it runs (`VAULT_ROOT`; `FRONTMATTER_SCHEMA` / `CLAUDE_MEMORY_DIR`
  decide applicability of those two).

### `frontmatter-lint`
- **compute x effect:** deterministic x read-only
- **What it does:** validates notes against your schema-as-code - flags off-vocabulary values, missing
  recommended axes, redundant date fields, and unknown fields. Advisory (reports; does not block).
- **Contract:** `--json`, `--terse`, `--check`, `--schema <path>`, `--vault <path>`.
- **Env:** `VAULT_ROOT`, `FRONTMATTER_SCHEMA`, `VAULT_SCAN_EXCLUDE`.

### `frontmatter-fix`
- **compute x effect:** deterministic x **mutating**
- **What it does:** applies the schema's reconciliation maps (e.g. normalising status / maturity /
  horizon values) by **surgical line-edits** on the frontmatter block, preserving formatting and field
  order (no YAML reparse).
- **Contract:** `--apply`, `--force`, `--json` (report-only without `--apply`), `--dates` (opt-in
  `date` -> `created` field dedup, kept opt-in because it ripples into Dataview queries and templates
  that still read `date`), `--dates-rename` (for notes carrying `date:` and NO `created:`, rename the
  key in place instead of dropping it - dropping would destroy the only creation date the note has, so
  this is a separate opt-in because it WRITES a canonical field rather than removing a redundant one;
  honours `VAULT_DATE_RENAME_EXCLUDE` on top of `VAULT_FORBIDDEN_ZONES`), and `--audit-log <file>` (on
  `--apply`, append a tamper-evident record of the batch to a hash-chained log; the record carries the
  per-category counts, so a rename is distinguishable from a drop in the trail).
- **Audit:** git, plus an optional hash-chained log via `--audit-log` (the reusable audit substrate
  `scripts/_audit.py`, which any apply-engine can write to; each entry chains the prior one's hash, so a
  silent after-the-fact edit is detectable). **Forbidden-zones:** attended by default; optional
  `VAULT_FORBIDDEN_ZONES` skip.
- **Env:** `VAULT_ROOT`, `FRONTMATTER_SCHEMA`, `VAULT_FORBIDDEN_ZONES`.

### `set-note-type`
- **compute x effect:** deterministic x **mutating**
- **What it does:** additively sets a `note_type` frontmatter field derived from a folder-to-type map.
  Additive and idempotent - inserts one line, never rewrites content, skips notes that already have it.
- **Contract:** `--apply` (report-only otherwise).
- **Audit:** git. **Forbidden-zones:** scoped (folder allowlist); optional `VAULT_FORBIDDEN_ZONES` skip.
- **Env:** `VAULT_ROOT`, `VAULT_FORBIDDEN_ZONES`.

### `tag-reconcile`
- **compute x effect:** deterministic x **mutating**
- **What it does:** detects morphological tag-merge groups (case / plural / hyphen / underscore / slash
  variants of one root) and proposes a single canonical, kebab-case spelling. True synonyms are out of
  scope (supply a curated map). Preferred apply path is a notes-app tag-rename tool; `--apply` is a
  guarded fallback.
- **Contract:** `--json`, `--apply`, `--force` (report-only without `--apply`).
- **Audit:** git. **Forbidden-zones:** attended by default; optional `VAULT_FORBIDDEN_ZONES` skip.
- **Env:** `VAULT_ROOT`, `VAULT_FORBIDDEN_ZONES`.

### `name-reconcile`
- **compute x effect:** deterministic x **mutating**
- **What it does:** detects non-kebab filenames and proposes a kebab-case slug. **Link-aware** apply:
  it first rewrites every wikilink that referenced the old basename across the whole vault, *then*
  renames the file, so links never break. Protected/legal/write-once folders are excluded from rename
  but still scanned as link sources.
- **Contract:** `--json`, `--apply`, `--force`, plus a `dedash` mode (light: only normalise dash
  separators, keep case) vs the default `kebab` mode (full lowercase-hyphen slug). Scope with
  `--under <folder>` to pilot the rename on one subtree, and `--no-exclusions` to override the
  `VAULT_NORENAME_ZONES` guard (rename even protected folders - deliberate, rarely wanted).
- **Audit:** git. **Forbidden-zones:** rename-protected via `VAULT_NORENAME_ZONES`; optional
  `VAULT_FORBIDDEN_ZONES` skip (never writes those files).
- **Env:** `VAULT_ROOT`, `VAULT_NORENAME_ZONES`, `VAULT_FORBIDDEN_ZONES`.

- **Identifier inheritance (since 2026-08-16):** when `IDENTIFIER_REGISTER` is set,
  `correlate` follows `parent` edges so an item naming a specific identifier still reaches
  notes written at its parent's level, which is how people actually write. Inherited
  evidence is scored below a direct hit and decays with each step, because a parent is about
  the child AND about that child's siblings; equal weighting would let a parent-level note
  outrank the note actually about the thing. A register that is named and unusable exits 2
  rather than scoring on without it.
### Substrate awareness (all engines)
- **What it is:** knowledge collections live disproportionately on synced mounts (Drive, Dropbox,
  OneDrive). On those substrates `size`, `mtime` and existence-immediately-after-a-write are not
  facts: placeholders report allocation-rounded sizes, files hydrate on access, and mtime belongs to
  the sync client rather than to whoever wrote the note.
- **`doctor`'s run-receipt names it** once per run, under `substrate`. The receipt already proved
  WHICH root was scanned and how many files; this is the other half, whether the filesystem's
  answers about those files can be trusted at all.
- **`correlate`'s index cache keys on content where metadata is untrusted.** On an ordinary disk the
  key stays the cheap `(mtime, size)` pair. On a synced mount an edited note can keep both values,
  so the cache would serve a stale card forever with plausible output and no error; the key becomes
  a content hash instead. `CACHE_VERSION` was bumped, because entries keyed the old way are not
  comparable.
- **The rule for new engines:** measure the bytes you ENCODED, never a size read back from a file
  you just wrote. `_substrate.write_verified()` exists for that.

### `register-lint`
- **compute x effect:** deterministic x read-only.
- **What it does:** asks whether a collection uses its own identifiers correctly. Structural
  validation asks whether a field is KNOWN; it cannot ask whether a value is THE RIGHT KIND OF
  THING, because both fields are known and both values are strings.
- **Four classes:** `wrong-category` (a value the register calls an agreement, declared under the
  request field), `alias` (a non-canonical spelling, invisible to exact matching), `compound` (two
  identifiers packed into one value), `unknown` (an identifier the register has never heard of).
- **Report-only, deliberately.** Applying a new register to a mature collection produces hundreds of
  findings on day one, a reader stops at the third stale one, and the check gets switched off.
  Enforcement is the author-time guard's job, scoped to the lines a change touches.
- **Provenance is the limit on enforcement** (ADR-0005), not decoration. `decided` entries may be
  enforced and auto-fixed. `harvested` entries may be enforced but never auto-fixed, and the message
  hedges, because a mismatch may mean the REGISTER is wrong rather than the document. `inferred`
  entries are never enforced at all: a name a tool invented must not become canonical by being the
  only spelling that passes a check.
- **Config:** `IDENTIFIER_REGISTER` points at the register. Start from
  `config.example/identifier-register.example.yaml`. Tiers are the collection's own; this tool ships
  no fixed vocabulary, per ADR-0004.
- **Flags:** `--root <path>` lints another collection, `--check` for the gate, `--json` for a
  machine consumer.
- **Exit codes:** `0` conformant, `1` findings, `2` no register configured, `3` register named and
  unusable. An entry with no `source` is refused rather than assumed decided.

### `custody-audit`
- **compute x effect:** deterministic x read-only.
- **What it does:** asks whether the substrate is actually KEPT. Every other engine validates
  content and passes whether or not that content has ever been committed, pushed or backed up.
- **Four questions, and nothing more:** is each declared artifact tracked, or deliberately ignored
  with a stated disposition (untracked-and-unignored is the silent gap); where the disposition is
  ignored-with-an-example, is there a CURRENT and COMMITTED encrypted counterpart; is `HEAD` on a
  declared remote; and is this the canonical working copy.
- **Why the counterpart question matters most:** "sensitive file gitignored, sanitised example
  committed beside it" is correct practice that nothing enforces, and the example next to the gap
  is exactly what makes a missing counterpart invisible. A counterpart older than the file it backs
  up, or present but uncommitted, is reported too: neither is a backup.
- **Receipts, never process introspection:** scheduled work declares a receipt file and this engine
  checks its freshness. It never inspects systemd, cron or Task Scheduler: three platforms, three
  failure modes, no determinism. It also avoids the trap of a job reporting failed every night while
  the half that mattered succeeded, since a permanently red signal is indistinguishable from a real
  one.
- **Config:** `CUSTODY_MANIFEST` points at JSON with `artifacts[]` (each with `path` and a
  `disposition` of `tracked`, `ignored-ephemeral` or `ignored-encrypted`), plus optional `remotes`,
  `canonical_root` and `receipts[]`. An ABSENT `remotes` means assume `origin`; an explicitly EMPTY
  one means no remote is declared and the question is not asked.
- **Flags:** `--root <path>` audits another collection, `--check` for the gate, `--json` for a
  machine consumer.
- **Exit codes:** `0` kept, `1` findings, `2` no manifest configured, `3` manifest named and
  unreadable.

### `denylist-audit`
- **compute x effect:** deterministic x read-only.
- **What it does:** audits the term list a scanning gate enforces, which nothing else does. A gate
  is only as good as its list, and lists of that kind are grown reactively, one leak at a time.
- **Two failures it catches, both ending in a green verdict:**
  - **A partially-listed family certifies its own siblings.** Holding two members of an identifier
    family and not the other three does not merely miss three terms: the member that IS caught is
    what makes the clean verdict on the others credible. Given a register, this is fully
    deterministic, because the register already knows which identifiers are siblings.
  - **A narrowed entry can be silently dead.** Fixing a real false positive once produced a pattern
    containing a literal backspace character, which matched nothing at all. A term silently disabled
    is worse than one that over-fires, because over-firing is visible.
- **Findings:** `dead-pattern` (does not compile, or does not match its own declared example),
  `no-example` (a regex entry whose liveness cannot be established), `family-partial`,
  `variant-unlisted` (a spelling that occurs in the corpus and no entry matches).
- **Declaring an example** is what makes liveness checkable: `regex:(?i)ACME  # example: ACME`.
  A plain literal needs none, since it always matches itself.
- **Variants are only reported when present in the corpus.** Generating variants is easy and
  generating useful ones is not, so occurrence is the filter.
- **Flags:** `--denylist <file>` (or `EGRESS_DENYLIST`), `--register <file>` to enable the family
  check, `--corpus <root>` to enable variant detection, `--check`, `--json`.
- **Exit codes:** `0` clean, `1` findings, `2` no denylist given, `3` denylist named and unreadable.

### `path-audit`
- **compute x effect:** deterministic x read-only.
- **What it does:** finds what still points at a location this project has left. Closes principle P9.
- **Why:** every long-lived collection eventually moves, and every absolute path embedded in
  worktrees, editable installs, links and hook configuration keeps naming the old place. Nothing
  announces it. Renaming this repository silently broke both of its own worktrees, and the failure
  surfaced only when someone next touched one of them.
- **The extra turn beyond an ordinary stale path:** a rollback copy usually still exists at the old
  location, so a tool rooted there does not merely succeed, it succeeds against real, stale content.
- **Findings:** `worktree-broken` (pointer names a gitdir that does not resolve),
  `worktree-stale` (registered, directory gone), `editable-install` (a `.pth` naming a path that is
  gone), `broken-link` (a symlink or junction whose target is missing; on Windows a dangling
  junction reports as absent rather than erroring, so a walk through it silently finds nothing),
  `hookspath-missing` (so no hook runs at all).
- **Every finding carries its repair command.** A check that names a fault without its remedy gets
  silenced as surely as one that fires too often.
- **Flags:** `--root <path>`, `--check`, `--json`.
- **Exit codes:** `0` clean, `1` findings, `2` not a git repository.

### `hooks-audit`
- **compute x effect:** deterministic x read-only.
- **What it does:** finds gates that look installed and do not run.
- **Why:** a control that lives in `.git/` does not exist for anyone who clones. `.git/hooks` is
  machine-local by design, so a gate placed there is a gate exactly one person has, and nothing
  reports its absence elsewhere because the ruleset sits in the tree looking convincing.
- **The quiet case:** once `core.hooksPath` is set, git stops reading `.git/hooks` ENTIRELY. Any
  hook still there is executable, plausible and dead. This engine found exactly that in its own
  repository: a staged-changes secret scan, shadowed by a `hooksPath` set later, not running on any
  commit since.
- **Findings:** `untracked-gate` (exists on this machine only), `shadowed` (cannot run because
  hooksPath points elsewhere, and reports whether a live equivalent exists), `not-wired` (the repo
  ships hooks and git was never told), `hookspath-missing` (points at a directory that is not
  there, so nothing runs at all).
- **Flags:** `--root <path>` audits another repository, `--check` for the gate, `--json` for a
  machine consumer.
- **Exit codes:** `0` every gate present here is one a clone would also get, `1` findings, `2` not a
  git repository. Exit 2 is not success: nothing was audited.
- **Note on executability:** a hook is identified by NAME, not by the POSIX execute bit. Git runs
  hooks on Windows regardless of that bit, so testing it there reports a working gate as missing.

### `selftest`
- **compute x effect:** deterministic x read-only.
- **What it does:** runs every engine against a KNOWN-BAD fixture and fails unless the engine finds
  every defect planted in it. A negative control for the detectors themselves.
- **Why:** checks rot. A refactor stops a pattern matching, an upgrade changes a default, a scan
  quietly narrows, and every run afterwards reports fewer findings, which looks like improvement. A
  detector that has never been observed to fire is indistinguishable from one that cannot. Unit
  tests catch this in the maintainer's CI; `selftest` travels to the install site, where the config,
  the platform and the collection are all different.
- **Both halves are required:** a fixture asserts `must_detect` AND `must_not_detect`. A detector
  that reports everything also finds the planted defect, so the clean notes in each fixture are
  load-bearing rather than padding.
- **Fixture shape:** `selftest/<engine>/vault/` plus `expected.json` naming the engine, its args,
  the env it needs, and the two assertion lists. Each assertion carries a `why` in plain words, so a
  failure says what stopped being detected rather than printing a diff.
- **Exit codes:** `0` every detector alive, `1` a detector missed a planted defect or fired on a
  clean one, `2` no fixture matched. Exit 2 is deliberately not success: nothing was proven, which
  is not the same as everything passing.
- **Flags:** `--engine <name>` runs a single fixture rather than all of them, `--json` emits
  per-check results for a machine consumer.
- **Prior art:** the EICAR test file for antivirus, mutation testing for test suites, restore
  verification for backups. All the same move: prove the detector detects.

### `vendor-audit`
- **compute x effect:** deterministic x read-only (`--adopt` writes only the manifest).
- **What it does:** notices when an UPSTREAM file has moved underneath a copy you keep vendored on
  purpose. The de-dup pattern shims most engines so an upstream fix arrives automatically, but some
  files cannot be shimmed for good reasons: they are called from outside your tree, by a gate in
  another repository, on machines where this project is not cloned, and a shim exits when the engine
  is absent. Those stay resident copies, and "kept in sync by hand" is not a control. One such copy
  drifted to 311 lines against upstream's 416, missing a flag and four functions, unnoticed, because
  a stale analyzer reports cheerfully.
- **What it does NOT do:** it never reports that the two files DIFFER. They always differ, by
  design. It reports only that upstream CHANGED since the copy was last reconciled. A check that
  fires constantly is one nobody reads, which is how the original drift survived.
- **Why it does not auto-sync:** pulling upstream over a resident copy discards local config;
  pushing the other way leaks consumer specifics into a portable core. Neither is safe to automate.
  The machine notices, a human reconciles, `--adopt` records the new baseline.
- **Config:** `VENDOR_MANIFEST` points at a JSON file with an `entries[]` list, each carrying
  `local`, `upstream`, `upstream_sha256`, `reconciled`, and a required `why_resident`: a vendored
  copy with no stated reason cannot be told apart from an accident. Relative paths resolve against
  the manifest's own directory, so it is portable between checkouts.
- **Exit codes:** `0` reconciled, `1` upstream moved, `2` no manifest configured (a skip), `3`
  manifest named and unreadable (an error). Upstream being ABSENT is not drift: on a machine without
  the source there is nothing to compare, which is the very situation the resident copy exists for.
- **Vendoring shape that makes this cheap:** consumer preamble, a marker line, then the upstream
  file byte for byte. Re-vendoring becomes a concatenation and the diff to review is genuinely the
  upstream diff rather than a merge.

### `memory-consolidate`
- **Candidate signal quality (since 2026-08-16):** `--candidates` requires at least one CONTENT
  signal (currently filename-stem overlap). A shared `originSessionId` is a TIEBREAKER that raises
  the rank of a pair which already overlaps, never sufficient on its own: two notes share a session
  because they share a clock, not a subject. Measured on a 317-file store, admitting co-session
  alone gave 1846 pairs of which 1806 were topically unrelated; requiring content gives 40, and
  co-session still corroborates 19 of them. The suppressed count and the rule are reported in the
  payload under `suppressed`, because a silent cap reads as 'nothing more to find'.
- **Exit codes (since 2026-08-16):** `0` the store was reached, including a store that exists and is
  empty (a new collection is legitimate); `2` no store is configured, which stays a `doctor` skip;
  `3` a store WAS configured and could not be read, which `doctor` reports as an error and fails the
  roll-up. The 2/3 split exists because a mistyped or moved store used to be indistinguishable from
  an unused feature: it exited 0, and the SessionStart hook that reads `--terse` stays silent on a
  zero exit, so the session looked permanently healthy. See ADR-0002's amendment.
- **compute x effect:** the engine is deterministic x read-only; the full **memory-audit** capability is
  hybrid x mutating (engine + judgment + gate + audit via an adapter).
- **What it does:** the deterministic analyzer behind the memory-audit - computes a multi-metric health
  score, an importance/decay curve, and orphan / broken-link / stale / dead-end detection over a
  file-based memory store, then emits a consolidation proposal. Read-only: it proposes, never writes.
- **Decay model (since 2026-07-04):** per-note-type base half-life via frontmatter `metadata.type` --
  `user` 365d / `reference` 270d / `feedback` 180d / `project` 90d; untyped notes keep the prior 90d
  curve exactly. Reference count still multiplies the half-life (`base * (1 + log2(refs + 1))`).
- **Snooze (since 2026-07-04):** a `reviewed: YYYY-MM-DD` frontmatter stamp suppresses the stale flag
  for 120 days (override with `ttl: <days>`). Use it after deliberately re-validating an old note.
- **Index lint (since 2026-07-04):** `--lint` is an advisory, no-model check that a memory *index*
  file - the always-loaded entrypoint that a harness reads first - stays inside its read cap and
  reads as a tight index. Three axes: the two-axis load cap (200 lines OR 25000 bytes, whichever comes
  first, warn at a headroom target); one-line-per-entry telegraphic compression (no ` - ` / ` -> `
  separators, entry-length ceiling); and link integrity. Wikilink targets and backtick paths are
  stripped before the separator check, so a legitimate dash inside a real note name is never flagged.
  Never blocks (exit 0) - a nudge, not a gate.
- **Candidate detection (since 2026-07-04):** `--candidates` emits deterministic MERGE and
  CONTRADICTION candidate pairs as JSON. MERGE keys on filename-stem token overlap or a shared
  `originSessionId`; CONTRADICTION on feedback-rule pairs that share a domain keyword and carry
  opposite stance words (always/never, prefer/avoid, ...). It is a narrowing pre-filter for a gated
  judge, the same deterministic-first shape as the tag reconcile fuzzy-gate, on memory files: the
  engine proposes candidates, never verdicts. (Roadmap R14.)
- **Contract:** `--json`, `--check`, `--terse`, `--lint`, `--candidates`, `--today YYYY-MM-DD`.
- **Audit (capability):** append-only, hash-chained log (not git - see [[explanation/index]]).
- **Env:** `CLAUDE_MEMORY_DIR`, optional `VAULT_INBOX_DIR`, `VAULT_ROOT`.

### `registry-generate`
- **compute x effect:** deterministic x read-only
- **What it does:** scans the harness for per-engine metadata headers and emits the capability registry.
  Anti-rot by construction - the catalog is generated from the source-of-truth headers, never
  hand-maintained. Engines without a header are listed as the classification backlog.
- **Contract:** `--json`, `--write` (writes the registry doc; prints to stdout otherwise).
- **Env:** `HARNESS_ROOT` (defaults to the repo root).

### `egress-gate`
- **compute x effect:** deterministic x read-only
- **What it does:** scans what a push, publish or paste would disclose, **before** it leaves the
  machine. Complements the gitleaks pre-push guard rather than replacing it: gitleaks matches raw
  bytes and owns secrets plus the author-identity allowlist, this folds NL/FR/EN diacritics and owns
  vocabulary, so a term list written in ASCII still matches accented prose. Scans non-git surfaces
  too (staged changes, a tracked tree, ad-hoc text). In `--push-stdin` it reads git's pre-push refs
  and covers the whole outgoing range: commit **messages**, **patches** and author **identities**,
  because history is egress - a term deleted in a later commit still ships in the objects the push
  transfers. Term sources may be plaintext (literal + `regex:`) or **hashed** (one sha256 per
  lowercase folded word-token), the latter so a PUBLIC repo can carry its own gate without the gate
  disclosing what it guards; hashed matches report `<redacted>` and never echo the term.
- **Fails closed.** No loadable term source, or a failed git call, exits `2` and means BLOCKED. A
  gate that could not scan must never report clean.
- **Contract:** `--staged`, `--push-stdin`, `--range`, `--tree`, `--file`, `--text`, `--stdin`,
  `--json`, `--baseline` (accepted-finding fingerprints; new findings still block),
  `--print-fingerprints`, `--emit-hashes` (derive a public hashed list from a private plaintext one;
  drops multiword and short terms and reports how many, so the weakening is visible).
- **Exit:** `0` clean, `1` findings at block severity, `2` environment error (also BLOCKED).
- **Env:** `EGRESS_GATE_CONFIG` (config path), `EGRESS_DENYLIST` (a term-source path).
- **Config:** `config.example/egress-gate.example.yaml` - sources, caps, severities, per-mode
  behaviour and baseline path. The fold table and the match loop stay in code on purpose: a
  misconfigured fold silently weakens the gate while still reporting clean.
- **Hooks:** `bootstrap/install-hooks.sh` wires pre-commit and pre-push via `core.hooksPath`.
  Pre-commit arms only in a repo that has a public remote (override with
  `git config neurokeeper.egressGate.precommit always|never`), so a private repo whose purpose is
  to hold sensitive content is not blocked on every commit.

> [!info] Shared internals (not dispatcher subcommands)
> Two helper modules are imported by the engines rather than run directly: a **shared library**
> (vault walk, frontmatter split, slug helpers - one definition, imported everywhere) and a
> **write-guard** preflight (refuses bulk vault writes while the notes app is open). Both are
> deterministic and read-only.

---

## The metadata-header spec

Every engine carries a machine-parseable header in its top comment block (one field per line, matching
`@field: value`). `registry-generate` harvests these to build the catalog, so a new engine becomes
discoverable the moment it has a header.

```text
# @capability:   <short-name>          # the capability id
# @compute:      hybrid                # deterministic | llm | hybrid
# @effect:       mutating              # read-only | mutating
# @engine:       path/to/engine.py     # the deterministic script
# @prompt:       path/to/prompt.md     # the judgment template, or (none)
# @adapters:     skill:<name>, cli     # which bindings exist
# @portability:  L1a-generic           # L1a-generic | L1b-private | L2-config
# @forbidden:    enforced              # n/a | enforced | scoped
# @audit:        dream-log             # none | git | dream-log
# @status:       active                # active | experimental | deprecated
# @doc:          path/to/design.md     # the design/runbook
# @doctor:       gate                  # gate | advisory | no   (external engines; opt-in)
```

Field meanings:

| Field | Meaning |
|---|---|
| `@capability` | The capability id (the dispatcher subcommand / registry key). |
| `@compute` | Whether work is done by code, an LLM, or both. |
| `@effect` | Whether it can write (`mutating`) or only reports (`read-only`). |
| `@engine` | Path to the deterministic script. |
| `@prompt` | Path to the LLM-judgment template, or `(none)`. |
| `@adapters` | Which bindings exist (CLI, a plugin skill, MCP, ...). |
| `@portability` | `L1a-generic` (portable core), `L1b-private` (private mechanism), `L2-config`. |
| `@forbidden` | Whether the engine enforces the forbidden-zones denylist. |
| `@audit` | Audit substrate: `none`, `git`, or a hash-chained `dream-log`. |
| `@status` | Lifecycle state. |
| `@doc` | The design/runbook for the capability. |
| `@doctor` | For engines loaded from `NEUROKEEPER_ENGINE_PATH`: whether `doctor` composes this engine, and whether it may fail the roll-up. `gate` may fail it, `advisory` reports only, absent or `no` means `doctor` ignores the engine. Participation is opt-in because being dispatchable must not mean "run this whenever someone asks about the health of my collection". An unrecognised value is refused rather than guessed at, since this field decides whether a failure is allowed to be invisible. |

---

## Environment configuration

Engines are config-free by design - they read their target and options from the environment, so the
same binary works against any vault or memory store. Provide your own values (an example config file
ships with the repo; the harness ships schemas and examples only, never real config or content).

| Variable | Read by | Meaning |
|---|---|---|
| `VAULT_ROOT` | the vault engines | Path to your notes vault (defaults to the current directory). |
| `VAULT_SCAN_EXCLUDE` | the vault engines | Comma-separated directory prefixes to skip while scanning. |
| `VAULT_REFAUDIT_EXCLUDE` | `ref-audit` | Comma-separated dirs the audit never walks (default: system/tool dirs only - attachment dirs ARE walked, to flag orphan media). |
| `VAULT_NORENAME_ZONES` | `name-reconcile` | Comma-separated folders to protect from rename (still scanned as link sources). |
| `VAULT_FORBIDDEN_ZONES` | the mutating engines | Optional. Comma-separated reldir prefixes the mutators skip writing entirely. Unset (default) = no skipping; the operator watching the run plus the git diff is the control. |
| `FRONTMATTER_SCHEMA` | the frontmatter engines | Path to your schema-as-code file. |
| `CLAUDE_MEMORY_DIR` | `memory-consolidate` | Path to the file-based memory store. |
| `VAULT_INBOX_DIR` | `memory-consolidate` | Optional - enables an inbox-pressure metric. |
| `HARNESS_ROOT` | `registry-generate` | Root to scan for metadata headers (defaults to the repo root). |
| `NEUROKEEPER_ENGINE_PATH` | the dispatcher, `doctor` | Optional. `PATH`-style list of directories holding engines that live outside this repository, so a domain-specific capability can stay in its owner's repo and still run as `neurokeeper <name>`. Only files carrying an `@capability` header register. A name that collides with a built-in is refused rather than resolved either way, and a directory on the list that does not exist is a hard error rather than a skip: continuing would report those engines as absent rather than as misconfigured. See [[how-to/extend-with-your-own-engine|Extend with your own engine]]. |

### Schema-as-code (the frontmatter engines)

The frontmatter lint and fix validate notes against a schema file you supply. The schema defines your
controlled axes - for example `note_type`, `status`, `maturity`, `horizon`, and `lang`, plus any
project-specific axes you add and their vocabularies and reconciliation maps. The **engine is
vault-agnostic**; all vocabulary lives in your schema, not in the code.
