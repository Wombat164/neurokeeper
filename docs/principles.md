# Principles

Every principle here has to name the check that enforces it. A principle with no check is listed as
an OPEN ITEM rather than as guidance, because a register of good intentions is decoration and this
project's whole claim is evidence over assertion.

They all descend from one observation. Almost every serious failure found in this codebase and in
the collections it manages had the same shape: **a check that looked healthy while unable to see.**
None of them errored. All of them reported success.

---

## P1. Unreachable is not empty

An engine that could not reach its subject must not return the same signal as one that reached it
and found nothing.

A scan rooted at a path that does not exist reports zero findings, and zero findings reads as clean.
The wrong-path case is the one that looks fine, which is what makes it dangerous rather than merely
annoying.

**Enforced by:** `memory-consolidate` exits 3 for a configured store it cannot read, and 0 for a
store that exists and is empty. See ADR-0002's amendment for the full exit contract.

---

## P2. Named is not the same as configured

If a configuration value was supplied at all, run the thing and let it speak. Deciding
applicability by testing whether the value RESOLVES folds "you configured it wrongly" into "you did
not configure it".

The aggregate health check once decided a memory store was applicable by asking whether the
directory existed. A mistyped or moved store was therefore reported as "required config not set",
skipped, and rolled up green. The operator had turned the check on. It was pointing at nothing.

**Enforced by:** `doctor` tests presence, not resolution, and maps exit 3 to an error that fails the
roll-up while exit 2 stays a skip.

---

## P3. A narrowing filter must narrow, and must say what it dropped

A pre-filter exists to reduce what an expensive consumer has to read. If its output grows with the
size of the input rather than with the number of real signals, it is not narrowing anything, and
the cost lands on whoever reads the residue.

Silence about what was suppressed is the second half of the same problem: a silent cap reads as
"nothing more to find", which is what makes a narrowing filter dangerous rather than merely noisy.

Measured instance: a merge-candidate pre-filter emitted 1846 pairs on a 317-file store, of which
1806 were paired on a shared session identifier and nothing else. Two notes share a session because
they share a clock, not a subject.

**Enforced by:** `memory-consolidate --candidates` requires a content signal, treats co-session as a
tiebreaker, and reports the suppressed count with the rule that produced it.

---

## P4. Check the references a human copies, not only the ones a machine reads

Machine-read values fail loudly when they drift: a build breaks, a manifest is rejected. Values that
a person copies out of documentation drift silently, because the copy works and simply does the
wrong thing.

Instance: a release gate compared the package version across three manifests, reported "version
synced", and exited 0 while seven references in prose still pinned readers to a release two minor
versions behind.

The corollary that makes this usable: prose which merely MENTIONS a version is not a pin. A linter
that fires on correct text is one nobody leaves switched on.

**Enforced by:** `check-release` scans copyable references (a pre-commit `rev:`, a workflow `uses:`
ref, a status line) across the documentation set, skips historical files by name, and honours an
inline opt-out.

---

## P5. A control that lives only in an instruction is not a control

"Kept in sync by hand" is a hope. Where a copy must exist for a good reason, the drift has to
produce a signal.

Instance: a file vendored deliberately, because a gate in another repository calls it and a
delegating shim would break that caller, drifted to 311 lines against upstream's 416, missing an
entire flag and four functions. Nothing noticed, because a stale analyzer reports cheerfully.

The check must report that UPSTREAM MOVED, never that the two files differ. They always differ; that
is the point of the copy. A check that fires constantly is one nobody reads.

**Enforced by:** `vendor-audit`, against a manifest that records the upstream hash at reconciliation
and requires every entry to state why it is resident.

---

## P6. A detector that has never been observed to fire is indistinguishable from one that cannot

The principles above are themselves checks, and checks rot. A refactor stops a pattern matching, an
upgrade changes a default, a scan quietly narrows. Every run afterwards reports fewer findings,
which looks like improvement.

So each detector carries a known-bad fixture and must find every defect planted in it, on demand, at
the install site rather than only in the maintainer's CI.

Both halves are required. A fixture asserts what must be detected AND what must not: a detector that
reports everything also "finds" the planted defect, so negative controls are load-bearing rather
than padding.

**Enforced by:** `selftest`, run in CI on every push and available as a command wherever the package
is installed.

---

## P7. A control that lives in `.git/` does not exist for anyone who clones

`.git/hooks` is machine-local by design, so a gate placed there is a gate exactly one person has.
Nothing reports its absence elsewhere, because the ruleset is in the tree, tracked and visible,
which is what makes the arrangement convincing.

There is a quieter second shape. Once `core.hooksPath` is set, git stops reading `.git/hooks`
entirely, so a hook still sitting there is executable, plausible and dead. Found in this repository
while the check was being written: a staged-changes secret scan in `.git/hooks/pre-commit`,
shadowed by a `core.hooksPath` set later, silently not running on any commit since.

**Enforced by:** `hooks-audit`, which reports gates that are untracked, shadowed by `hooksPath`,
shipped but not wired, or pointed at a directory that does not exist.

---

## P8. Content validity says nothing about custody

Every check that inspects content passes happily whether or not that content has ever been
committed, pushed or backed up. Durability is a separate question and its failures are invisible by
construction: nothing is wrong with the work, it simply exists in one place.

The subtlest instance is a good pattern nothing enforces. "Sensitive file gitignored, sanitised
example committed beside it" is correct practice, and the example sitting next to the gap is exactly
what makes a missing encrypted counterpart invisible.

Scheduled work is checked by RECEIPT, never by introspecting the scheduler: three platforms, three
failure modes, no determinism. That also avoids a specific trap, a job reporting failed every night
while the half that mattered succeeded throughout, because a permanently red signal is
indistinguishable from a real one.

**Enforced by:** `custody-audit`, which asks four questions and nothing more: is it tracked or
deliberately ignored with a stated disposition, is the encrypted counterpart present and current, is
HEAD on a declared remote, and is this the canonical working copy.

---

## P9. A structural change breaks things that never mention it

Renaming or moving a repository silently breaks every worktree attached to it: the pointer names the
old path, and the failure surfaces only the next time someone touches that directory. Nothing warns
at rename time, and the repair command exists but is easy not to know about.

The general form is broader than worktrees. Symlinks and junctions, editable installs, scheduled
jobs, cached absolute paths in state files and hook configuration all hold a location that a move
invalidates without complaint.

It carries an extra turn beyond P1. A scan rooted at a stale path reports zero findings and zero
findings reads as clean, and a rollback copy usually still exists at the old location, so the tool
does not merely succeed: it succeeds against real, stale content.

**Enforced by:** `path-audit`, which reports broken and stale worktrees, editable installs naming a
path that is gone, dangling links, and a `core.hooksPath` pointing at nothing. It carries the repair
command with each finding, because a check that names a fault without its remedy gets silenced as
surely as one that fires too often.

---

## Open items: principles with no check yet

Listed here rather than above, because an unenforced principle is a task, not guidance.

*(none open. O1 graduated to P9 on 2026-08-16.)*
