"""Enforcement scoping: which part of a collection a rule is allowed to fail on.

Applying a new rule to a mature collection produces hundreds of findings on day one, none of which
the person running it caused. A reader ignores all of them to reach the one that is theirs, and then
stops reading. The documented outcome is that the check gets switched off, and a check nobody runs
protects nothing. Scoping to the change in hand is what makes a rule adoptable at all.

Out-of-scope findings are COUNTED, never discarded. A backlog that is invisible cannot be worked
down and cannot be shown to be growing; a backlog reduced to one number stays honest and stays out
of the way.

ONE implementation, because two engines answering "what changed" differently is how a pre-commit
hook and its own CI job come to disagree about the same commit.

Three members of the family:
  file-level  -- staged_paths() / changed_since(): which FILES this change touches
  line-level  -- changed_lines(): which LINES it touches, for an author-time guard that must not
                 fire on the pre-existing content of a file you happened to edit
  baseline    -- an accepted set of known findings, owned by the caller

Every one exits 2 on a git error rather than returning an empty set, because empty reads as
"nothing here is broken" and that is the most expensive wrong answer this module could give.
"""
import os
import subprocess
import sys


def _git(vault, *args):
    return subprocess.run(["git", "-C", vault, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _root(vault, who):
    top = _git(vault, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        sys.stderr.write(f"{who}: '{vault}' is not inside a git repository.\n")
        sys.exit(2)
    return top.stdout.strip()


def _rel_set(root, vault, lines):
    out = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        abs_p = os.path.normpath(os.path.join(root, line))
        rel = os.path.relpath(abs_p, vault).replace(os.sep, "/")
        if not rel.startswith(".."):
            out.add(rel)
    return out


def staged_paths(vault, who="scope --staged"):
    """Collection-relative posix paths in the git INDEX: exactly what this commit would introduce."""
    root = _root(vault, who)
    diff = _git(vault, "diff", "--cached", "--name-only")
    if diff.returncode != 0:
        sys.stderr.write(f"{who}: 'git diff --cached' failed: {diff.stderr.strip()}\n")
        sys.exit(2)
    return _rel_set(root, vault, diff.stdout.splitlines())


def changed_since(vault, ref, who="scope --since"):
    """Collection-relative posix paths changed vs `ref`, staged and unstaged alike."""
    root = _root(vault, who)
    diff = _git(vault, "diff", "--name-only", ref)
    if diff.returncode != 0:
        sys.stderr.write(f"{who}: 'git diff {ref}' failed: {diff.stderr.strip()}\n")
        sys.exit(2)
    return _rel_set(root, vault, diff.stdout.splitlines())


def changed_lines(vault, path, ref=None, who="scope"):
    """1-based line numbers of `path` that this change ADDS or MODIFIES.

    File-level scoping is too coarse for an author-time guard: editing one line of a document that
    carries five old findings would report all five as yours. This reads the hunk headers of a
    unified diff, which is the cheapest thing that answers "did I write this line".

    Returns None when the answer is unknown -- not in a repo, untracked, git unavailable. None means
    "cannot narrow", and a caller must then treat every line as in scope rather than none: a guard
    that silently narrows to nothing reports a clean file it never examined.
    """
    top = _git(vault, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return None
    args = ["diff", "--unified=0"]
    if ref:
        args.append(ref)
    else:
        args.append("HEAD")
    rel = os.path.relpath(os.path.abspath(path), top.stdout.strip()).replace(os.sep, "/")

    # An UNTRACKED file has no diff, and `git diff` reports that as silence rather than as an
    # error. Read literally that says "no lines changed", which would wave through a brand-new
    # document -- exactly the one most likely to be wrong, and the whole of it. Untracked means
    # every line is new, so the honest answer is "cannot narrow".
    tracked = _git(vault, "ls-files", "--error-unmatch", "--", rel)
    if tracked.returncode != 0:
        return None

    diff = _git(vault, *args, "--", rel)
    if diff.returncode != 0:
        return None

    lines = set()
    for line in diff.stdout.splitlines():
        if not line.startswith("@@"):
            continue
        # @@ -old,count +new,count @@
        try:
            after = line.split("+", 1)[1].split("@@")[0].strip()
            start, _, count = after.partition(",")
            start = int(start)
            count = int(count) if count else 1
        except (ValueError, IndexError):
            # An unparseable hunk header means the answer is unknown, and unknown must not read as
            # "no lines changed" -- that would silently exempt the whole file.
            return None
        lines.update(range(start, start + max(count, 1)))
    return lines


def partition(findings, in_scope, line_of=None, changed=None):
    """Split findings into (introduced, pre_existing).

    `in_scope` is the set of paths the change touches; `changed` (optional) narrows further to the
    lines it touches. A finding with no line number stays with its file: guessing that it is
    pre-existing would hide it, and this module's whole premise is that hiding is the failure.
    """
    introduced, pre_existing = [], []
    for f in findings:
        path = f.get("path") or f.get("note") or f.get("file")
        if path not in in_scope:
            pre_existing.append(f)
            continue
        if changed is None:
            introduced.append(f)
            continue
        ln = (line_of(f) if line_of else f.get("line"))
        if ln is None or ln in changed:
            introduced.append(f)
        else:
            pre_existing.append(f)
    return introduced, pre_existing
