# Contributing to neurokeeper

Thanks for your interest. neurokeeper is a portable-core harness for knowledge-base and agent-memory
hygiene: deterministic engines + prompt templates + thin adapters. Contributions that keep the core
domain-neutral and honest about what is built are very welcome.

## Development setup

```sh
git clone https://github.com/Wombat164/neurokeeper
cd neurokeeper
pip install -e ".[dev]"    # editable install + pytest + ruff
pytest -q                  # the full suite
ruff check scripts/ tests/ neurokeeper/
```

`pip install -e .` is the supported install mode: the `neurokeeper` dispatcher resolves the engines by
repo-relative path, so an editable install is what wires `neurokeeper <engine>` correctly. Run
`neurokeeper --list` to see the engines.

## Test discipline

- **Every change lands with tests.** A new engine, flag, gate, or contract change is not done until it
  has coverage; tests shadow the code as it lands, not at the end.
- **Fixtures are built programmatically, never committed as binaries.** The suite constructs throwaway
  vaults and config in a temp dir (see `tests/conftest.py`'s `mini_vault`). Keeping fixtures in code
  keeps the tree reviewable and the fixtures self-documenting.
- Prefer real end-to-end exercise over mock-only tests where an engine can actually be driven (run the
  engine over a real mini-vault and assert the report or the gate held).

## Prose and file conventions

- **ASCII only** in code, docs, and generated text (plus the diacritics a target language needs). No
  smart quotes, em dashes, or other decorative Unicode.
- **Do not use the spaced double-hyphen token** as a separator anywhere (prose, headings, filenames).
  Use a colon, a comma, parentheses, or a single hyphen instead.
- Keep the portable core **domain-neutral**: no organisation-, locale-, or consumer-specific content,
  paths, or branding in the repo. This repo ships schemas and examples only, never real config or
  content; domain specifics belong in a consumer's private config or adapter.
- Files are UTF-8 without BOM.

## Engine conventions

- **Report by default; mutate only on `--apply`.** A read-only engine writes nothing. A mutating engine
  does nothing destructive without an explicit `--apply`, refuses bulk vault writes while a notes app is
  open (pass `--force` to override deliberately), and treats git as its audit trail.
- **Every engine speaks the contract:** a `--json` flag and meaningful exit codes.
- **Add the metadata header** (`@capability` / `@compute` / `@effect` / ...) at the top of a new engine.
  `neurokeeper registry-generate` harvests it, so the capability registry stays anti-rot by construction.

## Pull requests

- Keep each PR to a single reviewable unit of work (one engine, one flag, one fix), with its tests.
- State honestly what is DONE versus specified: a claim in the docs must match the code. If something is
  a stub or roadmap-only, say so rather than implying it works.
- Update the relevant doc in the same PR: `docs/roadmap.md` for what is next, an ADR under `docs/` for a
  genuinely new architectural decision.
- Add a `CHANGELOG.md` entry under `## [Unreleased]` for any user-visible change.

## CI must be green

Every PR runs the test suite (Linux + Windows, across supported Python versions), `ruff`, and a
blocking `gitleaks` secret scan. A PR does not merge with a red CI. If a hygiene gate fails, fix the
underlying issue rather than bypassing the gate.

## Keep the docs site in sync

The documentation site lives in [`wiki/`](wiki/) (Quartz, Diataxis-structured). It is not optional
decoration: **a new engine or a new `--flag` must be documented in the wiki reference in the same PR.**
CI enforces this deterministically. `tests/test_wiki_coverage.py` derives the ground truth from code
(the `cli.py` dispatch map and each engine's declared flags) and fails when a user-facing engine or
flag is missing from `wiki/content/reference/index.md`. If something genuinely needs no reference entry,
add it to that test's `INTERNAL` (subcommands) or `IGNORE_FLAGS` (flags) with a reason, rather than
skipping the check. New capabilities should also gain a how-to recipe and, when they introduce a
concept, an explanation entry.
