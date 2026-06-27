# Prompt template: memory-audit judgment (portable)

Harness-neutral judgment layer for the `memory-audit` capability. Pair it with the deterministic engine
`scripts/memory-consolidate.py` (the engine produces the facts; this prompt does only the judgment the
engine cannot). Any harness adapter (Claude Code skill, MCP, plain CLI + an open LLM) feeds the engine
output into this prompt. See `docs/pattern-portable-core-and-adapters.md`.

## Inputs (from the engine -- never recomputed by the LLM)
Run `python scripts/memory-consolidate.py --json` and treat its output as ground truth:
- `score` (5-metric health), `orphans`, `broken_links`, `stale`, `dead_ends`, `lowest_importance`,
  `heaviest_files`, `memory_lines`, byte size.

## Hard invariant
NEVER state a count, filename, score, or line number the engine did not produce. If you need a number,
it comes from `--json`. (This is the never-hallucinate guard: LLM-fabricated counts are a documented failure mode.)

## Your job (judgment only)
1. **Read the engine output.** If `broken_links` or `orphans` are non-empty, those are unambiguous
   defects -> propose fixes first (repoint dangling refs; re-index or archive orphans).
2. **Size pressure.** If MEMORY.md is over the byte-budget, the lever is index compression, NOT
   file-archiving (unless the engine reports genuinely `stale` files). Prefer: tighten verbose entries to
   one-liners (detail stays in topic files), then demote whole settled lookup-clusters to `archive-*.md`.
   Protect always-loaded clusters (behaviour rules, cross-env core, personnel, active programmes,
   LOAD-BEARING entries). Target lookup-on-demand clusters only.
3. **Contradiction sweep.** Scan `feedback-*` entries for same-domain pairs with opposite stance words
   ("always"/"never", "do"/"don't"). Report pairs for human review; do NOT auto-resolve.
4. **Build a proposal table** (one row per action): `# | action(archive/merge/demote/tighten/rename/
   flag-contradiction) | file(s) | importance(from engine) | rationale | risk`. Group/protect per (2).

## Output + gate (mutating capability)
- Present the proposal table. STOP. Do not write.
- The operator confirms per row (yes/skip/abort). Default-skip anything the operator does not confirm.
- On confirmation: apply deterministically, then APPEND one entry to the memory dream-log
  (`audit/dream-log.jsonl` via `dream-log-helper.py`) covering the batch, then `render` + `verify` the
  chain. (Memory mutations audit to dream-log; vault-content mutations audit to git -- do not cross them.)
- Re-run `--check` after applying to confirm 0 defects.

## Forbidden / safety
- Refuse any write whose target matches `.claude/forbidden-zones.txt` (even with confirmation).
- This capability mutates the memory store (not the Obsidian vault), so the Obsidian-running guard does
  not apply; the dream-log hash-chain is the integrity control instead.
