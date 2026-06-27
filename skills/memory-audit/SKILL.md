---
name: memory-audit
description: Health-check + consolidate a file-based Claude memory store. Deterministic engine produces the facts; this skill is the thin Claude Code adapter. Use when memory is bloated, may have orphans/broken-links, or before a memory cleanup.
---

# memory-audit (Claude Code adapter)

This skill is the **Claude Code adapter** over a portable core. It does no analysis itself.

1. **Run the engine** (the only source of truth for counts/scores):
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/memory-consolidate.py" --json
   ```
   (Set `CLAUDE_MEMORY_DIR` to the memory store; optional `VAULT_INBOX_DIR` / `VAULT_ROOT` enable the
   inbox-pressure + note-count metrics.)
2. **Apply the judgment** per the portable prompt template
   `${CLAUDE_PLUGIN_ROOT}/prompts/memory-audit.md` (engine facts -> proposal; never invent counts).
3. **Gate + audit**: present the proposal, operator-confirms per row, apply deterministically, append a
   hash-chained audit entry, then re-run `--check`.

The engine + prompt are harness-agnostic; an MCP or plain-CLI adapter binds the same core. See
`docs/pattern-portable-core-and-adapters.md`.
