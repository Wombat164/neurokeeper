---
name: egress-gate
description: Check what a push, publish or paste would disclose, before it leaves the machine. Deterministic engine produces the findings; this skill is the thin Claude Code adapter and the escalation ladder. Use before any git push to a public remote, before composing any issue/PR/comment text, and before pasting repo content anywhere external.
---

# egress-gate (Claude Code adapter)

Thin adapter over a portable core. **It does no scanning itself and never adjudicates a finding
from memory.** The engine is the only source of truth for what matched.

## When this runs

Before **any** of: a `git push` to a public remote, composing issue / PR / comment text, pasting
repo or vault content into an external surface, publishing an artifact. The git hooks
(`bootstrap/install-hooks.sh`) enforce the push and commit cases mechanically; this skill covers
everything that is not a git operation, and interprets findings when the hooks fire.

## The ladder: deterministic first, on-device next, cloud never

Each tier runs only if the tier below it did not settle the question. Most invocations stop at
tier 0 having cost nothing.

### Tier 0 - deterministic engine (always, free)

```
neurokeeper egress-gate --push-stdin        # from a pre-push hook (refs on stdin)
neurokeeper egress-gate --staged            # a staged change
neurokeeper egress-gate --tree              # whole tracked tree, for CI
neurokeeper egress-gate --file X --json     # ad-hoc text about to be published
```

Exit `0` clean, `1` findings at block severity, `2` environment error which also means BLOCKED.

**Exit 0 ends the task.** Say so in one line and stop. Do not read the files "to be sure", do not
summarise what was scanned, do not narrate the gate. A clean gate is not a finding.

### Tier 1 - deterministic triage (only if tier 0 returned findings)

Run again with `--json` and sort the findings mechanically, without reading the source files:

- **fingerprint already in the baseline** - the engine suppressed it; nothing to do.
- **unit is a test fixture or an example** - still a real finding. Public is public. The path does
  not make a term safe, it only makes the fix easier.
- **term is a jurisdiction word with a generic equivalent** - the fix is a rename, not a baseline.
  This is the common case and it needs no model: the local word for an authorisation limit becomes
  `ceiling`, the local word for an annual roll-over becomes `renewal`, and an agency name becomes
  the tenant-config slot that supplies it. Deliberately stated without examples: naming the words
  here would put them in a file destined for a public repo, which is the mistake this whole engine
  exists to catch. It caught exactly that in the first draft of this paragraph.

Report counts and the affected units. Do not paste the flagged lines back at the operator; they
have the file, and echoing flagged content into a transcript is itself a small egress.

### Tier 2 - local model, and only local (only if tier 1 left a genuine ambiguity)

Escalate only for questions that are actually semantic: *is this term being used in its
jurisdiction sense or its ordinary-English sense?* A hashed-term hit reported as `<redacted>` can
also need a human-readable read of context.

> **HARD RULE. Flagged content never goes to a cloud model, including this one.**
> The content is flagged precisely because it may be sensitive. Sending it to a remote model to
> ask whether it is sensitive performs the exact disclosure the gate exists to prevent, and does
> so before anyone has decided it was safe. Use an on-device model (Ollama, or the local
> inference host). If no local model is available, skip tier 2 and go to tier 3. Waiting for a
> human is always cheaper than an unrecoverable disclosure.

This rule binds regardless of how small the snippet looks or how confident the classification
feels. There is no snippet-size exemption.

### Tier 3 - operator

Ambiguous after tier 2, or any finding whose fix would change meaning rather than wording.
Present: the unit, the count, the proposed rename, and what it would cost. One question, not a
survey.

## Fixing, in order of preference

1. **Rename to the generic term.** Almost always right, and it improves the public vocabulary
   rather than merely hiding a word.
2. **Move the value into tenant config.** If the term is a real jurisdiction value the engine
   needs, it belongs in the private config repo, referenced by a slot name.
3. **Baseline the fingerprint.** Only for a genuine false positive, and never as a way to get
   past a term that is correctly flagged. `--print-fingerprints` emits them.
4. **Weaken a term.** Effectively never. A term is on the list because someone was bitten.

If the leak is already committed but not pushed, `git commit --amend` is the right tool: a new
commit still ships the original message and blob in the objects the push transfers. Re-run the
gate after amending.

## Maintaining the lists

- Private plaintext lists are the primary source wherever one exists. They support multiword
  phrases and regexes; the hashed form cannot.
- `--emit-hashes <textlist>` regenerates the public hashed list. It drops multiword and short
  terms and says how many, so the weakening is visible rather than assumed.
- Extend the list whenever a new jurisdiction term surfaces. Keep entries specific enough not to
  fire on ordinary prose: a gate that cries wolf gets muted, and a muted gate catches nothing.

## What this skill must not do

- Conclude "probably fine" on a `2` exit. That is a BLOCK, not a warning.
- Re-implement the scan, or judge a term without running the engine.
- Send flagged content anywhere to get an opinion about it.
