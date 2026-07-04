# Changelog

All notable changes to neurokeeper are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning.
Full per-release notes: https://github.com/Wombat164/neurokeeper/releases

## [Unreleased]

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

[Unreleased]: https://github.com/Wombat164/neurokeeper/compare/v0.3.4...HEAD
[0.3.4]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.4
[0.3.3]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.3
[0.3.2]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.2
[0.3.1]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.1
[0.3.0]: https://github.com/Wombat164/neurokeeper/releases/tag/v0.3.0
