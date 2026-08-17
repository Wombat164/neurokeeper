# Changelog

All notable changes to neurokeeper are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning.
Full per-release notes: https://github.com/Wombat164/neurokeeper/releases

## [Unreleased]

## [0.10.0] - 2026-08-17

The release where the private consumer paid the core back: three of the fixes below were found by wiring these engines into a real 3000-note collection and a real mail corpus, not by reading the code.

### Fixed
- **`safe_write` truncated the target before writing it.** It opened the destination directly, so a
  run interrupted between that and the last byte left a half-written or empty file. The engines it
  backs are bulk mutators walking thousands of notes, and the damage is to exactly the content the
  caller was trying to preserve. It now writes a temp file beside the target and `os.replace`s it,
  which is atomic on POSIX and on Windows for a same-directory rename; on failure the partial is
  removed and the original is left untouched. Verified by a test the previous implementation fails:
  the rename is made to raise and the original is asserted byte-identical.

### Added
- **`safe_write` gains `root`, `zones` and `allow_zones`**, all defaulting off so existing callers
  are unaffected. `root` makes the confinement boundary explicit instead of always the global vault,
  which is what an ingestion engine writing to a staging directory needs; `zones` refuses a write
  into a configured forbidden zone, with `allow_zones` as the deliberate override.

  Ported from a private consumer that had all three properties while this core had none of them.
  Worth stating plainly rather than quietly: the generic core was the weaker of the two
  implementations, because the private one is where the writes actually hurt.

### Fixed
- **`register-lint` reported OK over a scan of nothing.** A register that declares entities but no
  `tier_fields` names no frontmatter field, so the check watched nothing and still printed "OK:
  every declared identifier is used as the register describes (141 entities)". Found on a real
  register. It now reports NOT CONFIGURED, because a pass over nothing is the most expensive kind
  of green.
- **A central `alias -> canonical` map was ignored.** Aliases were read per entity only, so a
  register declaring them centrally lost every alias silently - and alias is the one class exact
  matching cannot see, which made the check look present while catching nothing. An alias naming a
  missing entity is now refused rather than mapped to nothing.
- **List and wikilink values were stringified and checked as single identifiers.** An empty list
  became the literal identifier `[]`, `[A, B]` became one nonexistent name instead of two real
  ones, and `[[A]]` never resolved to A. On a real 3000-note collection that was 418 findings of
  which 307 were artefacts; after the fix, 111 findings with all 95 enforceable ones unchanged. An
  empty value is ABSENT, not wrong - the same distinction the exit contract draws one layer down.
- **`register-lint` printed "this report never blocks" and exited 1 anyway.** The contradiction
  made it impossible to compose as an advisory member of an aggregate: the whole roll-up went red
  on findings the report itself calls non-blocking. Findings now exit 0 unless `--check` is passed,
  which is what turns the report into a gate.

### Changed
- **`register-lint` is composed into `doctor`** as an advisory member whenever
  `IDENTIFIER_REGISTER` is set. Identifier conformance is collection health; it contributes counts
  and can never fail the roll-up.

## [0.9.0] - 2026-08-16

Three engines that answer questions the tool could not answer before: how do I start, what stops a new contradiction entering, and what should link to what.

### Added
- **`init`** (closes #38): configure the tool for a collection, and be checkable about it. Adoption
  on an existing collection was documented; starting from nothing was not, and the result is worse
  than it looks - every engine skips cleanly when unconfigured, which is correct, so a fresh
  collection reports a clean bill of health while doing almost nothing. A newcomer cannot tell
  "correctly minimal" from "silently doing nothing", which is the same confusion between absent and
  empty that the exit contract fixes one layer down.
  It states the note count it can see **before** writing anything, because a wizard that silently
  scopes to the wrong root writes a config that reports clean forever and nobody can tell. That line
  earned itself: an early version counted the working directory instead of the collection, and the
  count is what made it visible.
  `--schema derive` drafts a schema from the vocabulary already in use - few distinct values become
  an enumerated axis, high-cardinality fields become open, since enumerating free text produces a
  schema that fails on nearly every note. Always written `provenance: harvested`, and it says in the
  file that it describes what the collection CONTAINS rather than what it should; promoting it
  silently would make this tool's reading of a collection into that collection's law. There is
  deliberately no `--register derive`, because identifiers are your canon and a tool that invents
  them has decided what they mean.
  It writes **config only** - no notes, no folders, no naming convention (ADR-0004) - prints every
  file it wrote with the variables that config needs, and ends on a real `doctor --check` rather
  than a claim of success.
- **`register-lint --guard`: the author-time guard** (closes #22). The whole-collection report never
  blocks, on purpose; this is the half that enforces, and it enforces only what your edit
  introduced. Findings on lines the change touched are reported in full with their remedy and
  block; findings elsewhere in the same document collapse to one count and do not. File-level
  scoping was too coarse for this: edit one line of a document carrying five old findings and all
  five would have been reported as yours, which is the documented way a linter gets switched off.
  `--hook` blocks with exit 2 for a `PostToolUse` hook, and is opt-in because 2 is also this
  engine's NOT-CONFIGURED code: a caller that cannot tell "blocked" from "no register configured"
  is a coin-flip. Only enforceable findings block, per ADR-0005 - stopping someone's work over an
  entry the tool merely inferred is how it loses the argument about whether it should exist.
  `--staged` / `--since` bring the same enforcement-scoping family to the report, with out-of-scope
  findings counted rather than discarded.
- **`semantic-gaps`** (closes #17): which existing notes should link to the one you just wrote.
  `ref-audit` asks whether every link resolves; this asks the question that actually costs a
  collection its value, namely whether the note you just added is connected to the notes already
  covering its subject. Structurally such a collection is perfect - every link resolves, nothing is
  orphaned - and the knowledge is still in two halves.
  It **reuses `correlate` rather than re-implementing it**. The obvious build, ranking by shared-term
  count, ranks by how common a word is: the note sharing "project" and "meeting" with everything
  outranks the one sharing a single rare identifier. A second scorer would also be a second set of
  answers to one question, and on the day they disagree neither is trustworthy.
  Already-linked notes are excluded in **both** directions, since the gap is symmetric and an engine
  that keeps suggesting what you already did teaches you to stop reading it. It never writes a link:
  a missing link is a gap someone may still find, a wrong one is an assertion the collection makes.
  Always exits 0 and stays out of the `doctor` composition, because a suggestion engine that can
  fail a health gate is one whose gate gets switched off.

### Changed
- **Enforcement scoping now has one implementation**, in `scripts/_scope.py`, used by both
  `ref-audit` and `register-lint`. It lived inside `ref-audit`, and a second copy in the guard would
  have been two engines answering "what changed" differently - which is how a pre-commit hook and
  its own CI job come to disagree about the same commit.

### Fixed
- **An untracked file was silently exempt from line-level scoping.** `git diff` reports a brand-new
  file as silence rather than as an error, so reading the empty result as "no lines changed" waved
  through the whole of the document most likely to be wrong. Untracked now means "cannot narrow",
  which is treated as every line in scope rather than none. Caught by its own test.

## [0.8.0] - 2026-08-16

The release that stops the core from being the only place an engine can live.

### Added
- **A plugin seam: engines can now live in someone else's repository.** `NEUROKEEPER_ENGINE_PATH`
  names directories the dispatcher searches, so `neurokeeper acme-owner-audit` runs an engine this
  project has never seen. It answers a question ADR-0004 kept creating: the core refuses
  domain-specific content, which left "add it upstream" as the wrong answer for most real needs and
  forking or vendoring as the worse ones. The directory is the manifest, because a name-to-path
  index file is a second surface that drifts. Only files carrying an `@capability` header register,
  so a helper module beside an engine does not become a phantom command, and a name that collides
  with a built-in is refused rather than resolved in either direction: a core engine quietly
  replaced would make every report from this tool untrustworthy.
- **`neurokeeper.lib`**, the stable import surface external engines build on, so nobody has to
  import a private `_module` that moves, or re-implement the frontmatter parse and the markdown
  walk. Divergent copies of those are exactly how two tools come to disagree about the same note.
- **External engines can join the `doctor` roll-up**, by opting in with a `@doctor: gate` or
  `@doctor: advisory` header and never automatically: being dispatchable must not mean "run this
  whenever someone asks about the health of my collection". Each engine in the report now carries
  an `origin`, because an operator reading a health summary is entitled to know whose engine
  produced which finding.
- **How-to: "Extend with your own engine"**, whose worked example is extracted from the page and
  executed by the test suite. A documented example that no longer runs is worse than none: it is a
  confident claim about the code that a reader will debug for an hour before doubting.
- **Example config for every file-shaped setting an engine reads**, plus a gate that keeps it that
  way. `custody-audit`, `vendor-audit` and the egress denylist shipped with no example between them,
  so a reader had to reverse-engineer the format from source. An engine that needs a config file
  nobody can see the shape of is an engine nobody adopts, which is the same class as an
  undocumented flag and now gets the same treatment. The denylist example is asserted to pass its
  own audit, since an example that would fail the check teaches a shape that does not work.

### Fixed
- **Two ways an external engine's failure could have been invisible**, both found by writing the
  tests. `argparse` exits 2 for an unrecognised flag and exit 2 already means NOT CONFIGURED, so an
  engine that never implemented `--check` would have been reported as a tidy skip while its entire
  subject went unchecked and the roll-up stayed green; that is now distinguished and reported as an
  error. And an engine declaring `advisory` while exiting 1 is a contract breach rather than an
  `ok`, since otherwise its only way of saying something is wrong would be swallowed by the
  participation level it declared for itself.
- **`--list` swallowed the one error discovery most needs to report.** A defensive `except
  SystemExit` meant that a `NEUROKEEPER_ENGINE_PATH` entry which does not exist produced a listing
  of the built-ins and silence about the external engines that had just gone missing, which reads
  as "you have none" rather than "your configuration is wrong".

### Changed
- **The bundled example vault now demonstrates the seam**, and CI proves it in both directions on
  every push: the external engine dispatches, composes into `doctor` tagged `origin: external`, and
  is then re-run against a shortened roster so the gate is observed FAILING. A detector only ever
  observed passing is not known to detect anything.

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
