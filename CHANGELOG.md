# Changelog

All notable changes to neurokeeper are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning.
Full per-release notes: https://github.com/Wombat164/neurokeeper/releases

## [Unreleased]

## [0.7.0] - 2026-08-16

### Added
- **`denylist-audit`**: audits the term list a scanning gate enforces, which nothing else did. A
  partially-listed identifier family certifies its own siblings, because the member that is caught
  is what makes the clean verdict on the others credible; given a register that check is fully
  deterministic. It also proves each entry still MATCHES something, after a real incident where
  narrowing a term produced a pattern containing a literal backspace that matched nothing at all.
  Standalone by design: it audits any term list, and composes with a scanning gate rather than
  depending on one.
- **`path-audit`**, closing the last open principle (O1, now P9). Reports what still points at a
  location the project has left: broken and stale worktrees, editable installs naming a path that is
  gone, dangling links, and a `core.hooksPath` pointing at nothing. Each finding carries its repair
  command. Prompted by renaming this repository, which silently broke both of its own worktrees.
- **Substrate awareness.** A probe reports whether the filesystem under a root can be trusted, and
  `doctor`'s run-receipt names it once per run. On synced mounts size and mtime are the sync
  client's answers rather than the author's.

### Fixed
- **`correlate`'s index cache could serve stale cards indefinitely on a synced mount.** The key was
  `(mtime, size)`; on those substrates an edited note can keep both, so the cache never invalidated
  and the run reported plausible output over an index that no longer matched the notes. The key is
  now a content hash wherever the probe distrusts metadata, and `CACHE_VERSION` is bumped because
  old entries are not comparable. Covered by a test that edits content while holding mtime and size
  fixed, and which fails against the previous behaviour.
- **The identifier register (ADR-0005)** and **`register-lint`**, its first consumer. One optional
  file at `IDENTIFIER_REGISTER` declares identifiers, their category, aliases, typed relations and
  provenance; the lint catches four classes structural validation cannot express: wrong-category,
  alias, compound and unknown. Report-only by design, because applying a new register to a mature
  collection produces hundreds of day-one findings and enforcement belongs to the diff-scoped guard.
- **`correlate` inherits a parent's matches** down `parent` edges when a register is
  configured, so an item naming a specific identifier reaches notes written at the level
  people actually write at. Scored below a direct hit and decaying with distance.
- **Provenance is the limit on enforcement**, not metadata. `decided` entries may be enforced and
  fixed; `harvested` may be enforced but never fixed, and messages hedge toward the register being
  wrong rather than the document; `inferred` is never enforced at all. Without that split, a name a
  tool invented becomes canonical by being the only spelling that passes a check, and the tool
  starts writing reality instead of describing it.
- **How-to: "Adopt on an existing collection"**, the case every actual user has and the one that
  existed only in the changelog. Someone installs on a mature collection, sees a number that looks
  like a verdict on them, and closes the terminal. The sequence that avoids that is baseline, gate
  on net-new, clear opportunistically, re-baseline and watch it shrink.
- **An `adoption:` summary line** on `ref-audit` when a baseline is in use: `N new, N baselined,
  N resolved`. One frame carrying the whole posture, that the past is not billed to you and the
  present cannot get worse.
- The quickstart demo now shows the MESSY case rather than a clean run, because a clean-vault demo
  cannot answer the objection every prospective user actually has. Every number on it comes from a
  real run over a generated 120-note collection with realistic decay: 257 findings on day one, 255
  baselined, then 2 new.
- **Wiki explanation, "Evidence and enforcement"**: the invariant every engine is shaped by, stated
  once instead of implied across an ADR, several roadmap items and one engine page. Both halves are
  load-bearing, and the second is the one usually dropped: no verdict stronger than its evidence,
  no enforcement stronger than its mandate.
- **ADR-0004, the substrate boundary**: where this project's edge falls, written as refusals. No OS
  provisioning, no generic machine-drift detection, no network fetch inside an engine (that one is
  structural: the CI-gate positioning depends on offline determinism), no scheduler introspection,
  no model-scored similarity in the core. Also records that a named market gap is not a mandate.

## [0.6.0] - 2026-08-16

### Added
- **`custody-audit`**: asks whether the substrate is actually kept, which no content check does.
  Four questions and nothing more: is each declared artifact tracked or deliberately ignored with a
  stated disposition; where the disposition is ignored-with-an-example, is there a current and
  committed encrypted counterpart; is HEAD on a declared remote (a local ref comparison, no
  network); and is this the canonical working copy. Scheduled work is checked by receipt freshness,
  never by introspecting systemd, cron or Task Scheduler.
- The quickstart demo card derives its version from the package at render time. It read
  "neurokeeper 0.4.0" while the package was at 0.6.0: `check-release` inspects prose pins and cannot
  see inside a rendered image, so the only safe version in a demo is one taken at render time.
- **`--staged`** completes the enforcement-scoping family beside `--since` and `--baseline`, on
  `ref-audit` and forwarded by `doctor`: scope findings to the git index, so a new rule reports what
  this commit introduces rather than the collection's whole history on day one. Out-of-scope
  findings are COUNTED and named (`pre_existing_out_of_scope`) rather than discarded, because a
  scoped run that prints nothing reads as a clean collection.
- **`hooks-audit`**: finds gates that look installed and do not run. Reports hooks that are
  untracked (a control only this machine has), shadowed by `core.hooksPath` (git stops reading
  `.git/hooks` once it is set, so anything left there is executable and dead), shipped but not
  wired, or pointed at a directory that is not there. Run against this repository it found its own
  staged-changes secret scan sitting shadowed in `.git/hooks`, which is now restored as a tracked
  hook that clones with the tree.

## [0.5.0] - 2026-08-16

### Added
- **`selftest`**: a negative control for the detectors themselves. Each engine ships a known-bad
  fixture and must find every defect planted in it, on demand, at the install site rather than only
  in the maintainer's CI. A fixture asserts `must_detect` AND `must_not_detect`, because a detector
  that reports everything also finds the planted defect. `--engine <name>` runs one fixture; exit 2
  means no fixture matched, which is deliberately not success. Runs in CI on every push.
- **`vendor-audit`**: reports when an upstream file MOVES underneath a copy you keep vendored on
  purpose. It never reports that the two files differ, because they always differ; that is the point
  of the copy. Reads a manifest at `VENDOR_MANIFEST` recording the upstream hash at reconciliation,
  and requires each entry to state `why_resident`. `--adopt` records a new baseline after a human
  reconciles. It deliberately does not auto-sync: pulling discards local config, pushing leaks
  consumer specifics into the core.
- **`docs/principles.md`**: the register these checks descend from, where every principle names the
  check that enforces it and an unenforced principle is listed as an OPEN ITEM rather than guidance.
- README quickstart GIF (install then `doctor`, showcasing the run-receipt) and an `example-vault`
  CI badge: a workflow runs `doctor --check` against the bundled `examples/vault/` on every push,
  dogfooding the tool and proving a clean install. The GIF is now a theme-aware SVG pair.

### Changed
- **Exit-code contract, and ADR-0002 amended to match.** `0` reached the subject (an empty subject
  is still reached), `2` NOT CONFIGURED (still a `doctor` skip, because declining a check is
  legitimate), `3` UNREACHABLE (configured and unreadable: an error that fails the roll-up).
  Previously a missing memory store exited 0, so "the path is wrong" and "there is nothing here"
  were the same signal, and `--terse` feeds a hook that stays silent on a zero exit.
- **`doctor` decides applicability by presence, not resolution.** Testing whether a configured path
  resolved meant a mistyped or moved store was reported as "required config not set", skipped, and
  rolled up green. If a value was supplied at all, the engine now runs and speaks for itself.
- **`memory-consolidate --candidates` requires a content signal.** A shared session identifier is a
  tiebreaker, never sufficient alone: two notes share a session because they share a clock, not a
  subject. On a 317-file store this moved output from 1846 pairs to 40, with the 1806 suppressed
  reported in the payload rather than dropped silently.
- **`check-release` reads the version references a human copies** (a pre-commit `rev:`, a workflow
  `uses:` ref, a status line) across README, `docs/` and `wiki/content/`. Prose that merely mentions
  a version is not a pin; changelog, ADR and roadmap files are skipped by name; a single line can be
  exempted with `<!-- pin-ok -->`. A pin whose tag does not exist yet prints a NOTE rather than
  failing, because bumping docs before tagging is the normal release order.
- Brand: new mark and wordmark, a tagline, and theme-aware README imagery.

### Fixed
- `memory-consolidate` raised `KeyError` on a store that exists but has no index file. An empty
  store is a legitimate new collection and now reports normally on exit 0.

## [0.3.5] - 2026-07-04

### Added
- Reusable audit substrate (`scripts/_audit.py`): an append-only, hash-chained log any mutating engine
  can write to for a tamper-evident record of what it applied, where each entry chains the prior one's
  hash so a silent after-the-fact edit or reorder is detectable. `frontmatter-fix --apply --audit-log
  <file>` is the first consumer. This is the audit-substrate half of R13; the memory-specific apply
  primitives (archive / merge / demote) are a scoped follow-up.
- `memory-consolidate --candidates`: deterministic MERGE and CONTRADICTION candidate detection over the
  memory store (filename-stem token overlap or a shared `originSessionId` for merges; feedback-rule pairs
  with a shared domain keyword plus opposite stance words for contradictions). A narrowing pre-filter for
  a gated judge, the same deterministic-first shape as the tag fuzzy-gate, on memory files. (Roadmap R14.)
- Findings IR + SARIF: `ref-audit --sarif` emits SARIF 2.1.0 (GitHub code-scanning) through a canonical
  Findings IR (`scripts/_findings.py`: `engine` / `rule` / `severity` / `path` / `line` / `message` /
  `fingerprint`), the single seam that future output formats (JUnit, a Bases view) render over instead
  of per-engine serializers. Composes with `--since` / `--baseline`; reuses the baseline fingerprints as
  SARIF `partialFingerprints`. (Roadmap R16.)
- `ref-audit --baseline <file>` / `--write-baseline <file>`: adopt the tool on a dirty vault by
  accepting the current findings as a baseline, then reporting (and gating `--check` on) only NET-NEW
  debt. Findings are fingerprinted by semantic identity (a broken link keys on its missing target, not
  the source path), so a note rename does not resurrect the baseline; the output nags with how many
  baselined findings are now resolved, so the baseline shrinks instead of ossifying. (Roadmap R19.)

## [0.3.4] - 2026-07-04

### Added
- `doctor` run-receipt: every run emits a `receipt` (`tool` / `version` / `root` / `files_scanned` /
  `engines_run` / `duration_ms`) in `--json` and as the human report's header line, so a wrong-root or
  0-file run fails loudly instead of passing as a silent green. (Roadmap R18.)
- `ref-audit --since <git-ref>` (and `doctor --since`, forwarded): report only findings for notes
  changed since a git ref, narrowing the `--check` gate to the diff for pre-commit / CI. The scan stays
  graph-global (a renamed target can break backlinks in unchanged files); only the surfaced findings and
  the gate are scoped. A bad ref or non-git tree exits 2 rather than silently scanning the wrong scope.
  (Roadmap R15.)

## [0.3.3] - 2026-07-04

### Added
- R20 wiki-coverage gate (`tests/test_wiki_coverage.py`): a deterministic test that fails CI when a
  user-facing engine or flag is missing from the wiki reference catalog, deriving ground truth from
  `cli.py`'s dispatch map and each engine's declared flags. Escape hatches: `INTERNAL` (plumbing
  subcommands) and `IGNORE_FLAGS`.
- Community-health files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1),
  issue templates, pull-request template, and `THIRD-PARTY-LICENSES.md`.
- PyPI distribution under the natural name `neurokeeper`, published via Trusted Publishing (OIDC,
  no stored tokens) on a published GitHub Release. Install with `pipx install neurokeeper` or run
  one-shot with `uvx neurokeeper`.

### Fixed
- `frontmatter-lint` / `taxonomy-inventory` (#3, secondary): the shared `md_files()` walker now skips
  dot-prefixed directories (`.obsidian`, `.git`, tool caches) the way Obsidian does, so notes under
  `.extractor_cache/` etc. no longer inflate `no_fm` and other counts. The #2 dot-dir skip had landed
  only in `ref-audit`'s own walk; this moves it into the shared walker for every consumer.
- Documented three flags that the coverage gate surfaced as undocumented: `name-reconcile --under`
  and `--no-exclusions`, and `frontmatter-fix --dates`.
- Corrected docs that wrongly stated the PyPI name `neurokeeper` was taken (it is unregistered and
  free); removed the obsolete "rename the distribution" guidance from RELEASING.md.

### Changed
- README refreshed (centered header, badges, nav, ASCII-clean prose); documentation version pins
  bumped to v0.3.2.

## [0.3.2] - 2026-07-04

### Added
- `memory-consolidate --lint` (R11): an advisory index compression + size-cap + link-integrity check
  for the always-loaded entrypoint index (200-line / 25KB cap, with headroom targets and context-aware
  exclusion of wikilink targets and backtick paths). Never blocks (exit 0).

### Fixed
- `frontmatter-lint --json` (#3): off-vocabulary paths now live at `offvocab.<field>.<value> = [paths]`
  (per value; count is the list length), and each value is the note's relpath. v0.3.1 emitted the
  containing directory, which was not actionable.

## [0.3.1] - 2026-07-04

### Fixed
- `ref-audit`: skip dot-prefixed directories by default (Obsidian semantics), so tool caches no longer
  inflate the orphan / dead-end / isolated counts (#2).
- `frontmatter-lint --json`: emit a `files` block with per-finding paths, actionable without a second
  pass (#3).
- `config.example`: `memory_bytes_budget` corrected to 25000, the real index load cap (#4).
- `memory-consolidate`: `BYTES_BUDGET` recalibrated from 45000 to 25000.

### Added
- Obsidian integration guide (`docs/obsidian-integration.md`) mapping each backend seam
  (LINK / METADATA / TAGS / STORE / GUARD) to the Obsidian adapter; the core stays backend-agnostic.
- Dependabot: weekly grouped pip + github-actions updates.

## [0.3.0] - 2026-06-28

### Changed
- Project renamed to **neurokeeper** (the prior name was taken on PyPI/npm and saturated on GitHub; a
  `vault*` name would have tied the project to Obsidian, against the backend-agnostic design). No
  functional changes in this release: the package, CLI command, plugin, and docs URLs were renamed.

## [0.2.2] and earlier

The earlier release line. See the GitHub releases for details.

[Unreleased]: https://github.com/Wombat164/neurokeeper/compare/v0.3.5...HEAD
[0.3.5]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.5
[0.3.4]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.4
[0.3.3]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.3
[0.3.2]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.2
[0.3.1]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.1
[0.3.0]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.0
