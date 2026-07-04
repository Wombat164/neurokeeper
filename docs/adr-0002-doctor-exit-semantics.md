# ADR-0002: `doctor` exit semantics - tri-state, honest roll-up

- Status: **Accepted** (2026-06-28)
- Context engine: `scripts/vault-doctor.py` (and the CI/pre-commit adapters that consume it)

## Context

`doctor` aggregates the read-only engines into one report + one exit code. The naive design ("run them
all, exit non-zero if anything is wrong") is a **false-assurance trap**, because the engines do not all
gate equally:

- `taxonomy-inventory` - no `--check`, no failure exit. Pure inventory.
- `frontmatter-lint --check` - **advisory**: it reports off-vocab/missing-axes counts but exits 0 by design.
- `memory-consolidate --check` - a real gate, but only when a memory store is configured; absent
  `CLAUDE_MEMORY_DIR` it is a no-op.
- `ref-audit --check` - a real gate, but narrow: fails only on broken `.canvas`/`.base` refs (and, with
  `--strict`, unresolved links). Orphans / dead-ends / orphan-media never fail it.

A green roll-up built naively would mean "ref-audit found no broken canvas/base ref" while a vault full of
off-vocab frontmatter and thousands of orphans stays green. Shipping that as a "health gate" is dishonest.

A second hazard: `frontmatter-lint` **falls back to the bundled example schema** when `FRONTMATTER_SCHEMA`
is unset. Running it anyway in `doctor` would flood a consumer with false off-vocab "errors" (their vocab
!= our example). Absent config must mean **skip**, not run-with-the-wrong-config.

## Decision

1. **Tri-state per engine: `ok` / `fail` / `skipped`.** `skipped` = the engine's required config is not
   present (e.g. `frontmatter-lint` without `FRONTMATTER_SCHEMA`, `memory-consolidate` without an existing
   `CLAUDE_MEMORY_DIR`). A skipped engine is reported as skipped - **never silently counted as a pass.**
2. **The exit code asserts: "an engine ERRORED, or a real gate FAILED" - NOT "the vault is healthy."**
   - `--check` exits 1 iff a *gating* engine returned a failure (`ref-audit` broken canvas/base; with
     `--strict` also unresolved links; `memory-consolidate` broken-links/orphans) **or** any engine
     crashed/errored unexpectedly.
   - Advisory/informational engines (`taxonomy-inventory`, `frontmatter-lint`) contribute their numbers to
     the report but **cannot fail** the roll-up.
3. **Skipped never fails.** A vault repo with no memory store and no schema yields a green `doctor` with
   two engines reported `skipped` - which is honest ("not configured"), not a false pass.
4. **Compose by subprocess.** `doctor` runs each engine as a subprocess and reads its exit code + `--json`,
   reusing the test suite's pattern - not in-process (the CLI dispatcher runs engines via `runpy` which
   calls `sys.exit`).

## Consequences

- `doctor --check` is a usable CI gate with meaningful teeth (it fails on genuine reference/memory
  defects + crashes) and an honest scope (it does not pretend advisory checks are gates).
- The CI/pre-commit adapters (the Action, the pre-commit hooks) inherit this: they gate on `doctor --check`
  knowing exactly what green means, and pass `--strict` when a stricter vault wants unresolved links to fail.
- The report surfaces *everything* (advisory counts, skips, fails) for human review; the **exit code** is
  the narrow, honest subset that is safe to automate on.
