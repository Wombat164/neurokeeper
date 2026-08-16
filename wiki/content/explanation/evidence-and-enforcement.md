---
title: Evidence and enforcement
description: The invariant every engine is shaped by, and why several apparently separate features are one idea.
tags:
  - explanation
  - architecture
---

The engine pages explain what each tool does. None of them explains the idea they share, so a reader
can learn what `doctor` reports without ever learning why its output is shaped that way.

Here is the whole of it:

> **No verdict stronger than its evidence; no enforcement stronger than its mandate.**

Both halves are load-bearing, and the second is the one usually dropped.

## The first half: no verdict stronger than its evidence

A tool that reports more confidence than it earned is worse than one that reports nothing, because
a wrong answer delivered plainly stops the reader looking. Several behaviours that look like
separate features are the same rule applied in different places.

**A pile of weak signals must not sum into confidence.** Correlation scoring carries an anchor
floor: without at least one strong, specific signal, a note does not become a match no matter how
many faint ones agree. Twenty coincidences are still coincidence, and a scorer without a floor will
happily add them up and present the total as certainty.

**A score built entirely from sub-threshold evidence says so.** `weak` is a distinct state rather
than a rounding-down of `correlated`, because "we found something, and it is not enough" is a
different message from "we found a match" and from "we found nothing".

**An engine that could not reach its subject reports that, not emptiness.** A scan rooted at a path
that does not exist finds zero problems, and zero problems reads as clean. This is why a configured
store that cannot be read exits distinctly from one that is genuinely empty, and why "no fixture
matched" is not success.

**Findings that were filtered out are counted, not dropped.** A narrowed report that silently omits
what it set aside reads as a clean collection, and ambushes whoever runs unscoped later. Scoped runs
carry the count of what they excluded.

## The second half: no enforcement stronger than its mandate

Detecting something is not permission to act on it, and this is where tools usually overreach.

**A tool's own guess never gains a mandate.** An entry marked `inferred` is used for reporting and
is never enforced, because enforcement on a guess converts a helpful hypothesis into a rule the
collection now has to obey.

**Enforcement covers what this change introduced, not what it inherited.** `--since`, `--baseline`
and `--staged` exist so that adopting a rule does not make one author answer for a decade of
history. A gate that blames people for what they did not do is a gate that gets switched off, and a
switched-off gate enforces nothing at all.

**Mutation waits for an explicit instruction.** Engines report by default and change files only on
`--apply`; the propose, review, apply shape exists so the mandate is granted per run rather than
assumed once.

**Refusing beats proceeding unverified.** The egress check fails closed: when it cannot confirm that
a payload is clean, it stops rather than guessing. Anything else makes the check advisory, and an
advisory secret-scan is decoration.

## Why the two halves need each other

Take either alone and the tool becomes a familiar bad shape.

Evidence without restraint on enforcement is the linter that is technically right and universally
disabled: it detects accurately, acts on everything it detects, and is switched off within a week.

Enforcement without restraint on evidence is worse, because it is confident. It blocks work on the
strength of a guess, and the people it blocks cannot tell which findings deserve attention.

Holding both is what makes a check something a person leaves switched on, which is the only state in
which it protects anything.

## See also

- [Principles](https://github.com/Wombat164/neurokeeper/blob/main/docs/principles.md), the register
  of specific failure modes and the check that enforces each one.
- [ADR-0002](https://github.com/Wombat164/neurokeeper/blob/main/docs/adr-0002-doctor-exit-semantics.md),
  the exit contract, which is the first half made mechanical.
- [ADR-0004](https://github.com/Wombat164/neurokeeper/blob/main/docs/adr-0004-substrate-boundary.md),
  where this project's edge falls and what it refuses to absorb.
