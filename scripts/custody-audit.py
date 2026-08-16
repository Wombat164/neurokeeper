#!/usr/bin/env python3
# @capability:  custody-audit
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/custody-audit.py
# @prompt:      (none)
# @adapters:    cli, ci
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         wiki/content/reference/index.md
"""custody-audit.py -- is the substrate actually kept, or only internally valid?

Every other engine here validates CONTENT: links resolve, frontmatter conforms, the index is tidy.
All of them pass happily whether or not that content has ever been committed, pushed, or backed up.
Custody is the durability question none of them ask, and its failures are invisible by construction:

  * two sensitive files, deliberately gitignored, with sanitised examples committed beside them.
    Everything parsed, every check was green, and the real files existed on exactly one disk. The
    example sitting next to the gap is what made it invisible.
  * a collection 80 commits ahead of its remote for months. Nothing is wrong with the content.
  * a second machine holding dozens of files in an unversioned directory beside a correctly cloned
    sibling repository.

None of these is a content defect, so nothing that inspects content can find them.

FOUR QUESTIONS, AND NOTHING MORE

  tracked?      is each declared artifact tracked, or deliberately ignored WITH a stated
                disposition? Untracked-and-unignored is the silent gap.
  counterpart?  where the disposition is "ignored, sanitised example committed", is there a
                CURRENT encrypted counterpart? This is a good pattern that nothing enforces, so a
                new sensitive file simply joins the gap unnoticed.
  pushed?       is HEAD on a declared remote? A local ref comparison, no network.
  canonical?    is this the working copy the collection is supposed to live in? A copy kept as a
                rollback is complete, valid, and indistinguishable from the original in an editor.

RECEIPTS, NOT PROCESS INTROSPECTION

Scheduled work declares a receipt file: what ran, when, what it covered. This engine checks receipt
freshness and NEVER introspects systemd, cron or Task Scheduler. Three platforms, three failure
modes, no determinism. It also sidesteps a specific trap: a unit that reported failed every night
since it was written, while the half that mattered succeeded throughout. A permanently red signal
is indistinguishable from a real one.

  custody-audit.py --check    # 0 clean, 1 findings, 2 no manifest, 3 manifest unreadable
  custody-audit.py --json
"""
import argparse
import json
import os
import subprocess
import sys
import time

EXIT_OK, EXIT_FINDINGS, EXIT_UNCONFIGURED, EXIT_UNREACHABLE = 0, 1, 2, 3

DISPOSITIONS = ("tracked", "ignored-ephemeral", "ignored-encrypted")


def git(root, *args):
    try:
        p = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=15)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def load(path):
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except OSError as e:
        print(f"custody-audit: manifest configured but unreadable: {path}\n  {e}\n"
              f"  An error rather than a skip: a manifest was named and could not be read, so no\n"
              f"  answer is available and reporting 'nothing to keep' would be a lie.", file=sys.stderr)
        raise SystemExit(EXIT_UNREACHABLE)
    except ValueError as e:
        print(f"custody-audit: manifest is not valid JSON: {path}\n  {e}", file=sys.stderr)
        raise SystemExit(EXIT_UNREACHABLE)
    return data


def check_artifacts(root, artifacts):
    out = []
    for a in artifacts:
        rel = a.get("path")
        disp = a.get("disposition")
        if not rel or disp not in DISPOSITIONS:
            out.append({"state": "malformed", "path": rel,
                        "detail": f"disposition must be one of {', '.join(DISPOSITIONS)}"})
            continue
        abs_p = os.path.join(root, rel)
        if not os.path.exists(abs_p):
            out.append({"state": "declared-missing", "path": rel,
                        "detail": "declared in the manifest and not present on disk"})
            continue

        tracked = git(root, "ls-files", "--error-unmatch", rel) is not None
        ignored = git(root, "check-ignore", "-q", rel) is not None

        if disp == "tracked" and not tracked:
            out.append({"state": "untracked", "path": rel,
                        "detail": "declared tracked and git does not carry it. If this is "
                                  "deliberate, say so with an ignored-* disposition"})
        if disp.startswith("ignored") and not ignored and not tracked:
            out.append({"state": "unignored-gap", "path": rel,
                        "detail": "neither tracked nor ignored: it exists on this disk only, and "
                                  "nothing declares that to be intentional"})
        if disp == "ignored-encrypted":
            cp = a.get("encrypted_counterpart")
            if not cp:
                out.append({"state": "no-counterpart-declared", "path": rel,
                            "detail": "ignored-encrypted requires encrypted_counterpart, or the "
                                      "sanitised example beside it hides the gap"})
            else:
                cp_abs = os.path.join(root, cp)
                if not os.path.isfile(cp_abs):
                    out.append({"state": "counterpart-missing", "path": rel,
                                "detail": f"no encrypted counterpart at {cp}: the real content is "
                                          f"on this machine only"})
                elif os.path.getmtime(cp_abs) < os.path.getmtime(abs_p):
                    out.append({"state": "counterpart-stale", "path": rel,
                                "detail": f"{cp} is older than the file it backs up, so the backup "
                                          f"does not contain the current content"})
                elif git(root, "ls-files", "--error-unmatch", cp) is None:
                    out.append({"state": "counterpart-untracked", "path": rel,
                                "detail": f"{cp} exists and is not committed, so it protects "
                                          f"against nothing beyond this disk"})
    return out


def check_pushed(root, remotes):
    # ABSENT means "assume origin"; an explicitly EMPTY list means "no remote is declared, do not
    # ask". Collapsing the two with `remotes or [...]` made a manifest that deliberately declares no
    # remote report a missing one, which is the absent-is-not-empty principle inside the engine that
    # exists to enforce it.
    if remotes is None:
        remotes = ["origin"]
    if not remotes:
        return []
    out = []
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    head = git(root, "rev-parse", "HEAD")
    if not head:
        return [{"state": "not-a-repo", "detail": f"{root} is not a git repository"}]
    for remote in remotes:
        ref = git(root, "rev-parse", f"{remote}/{branch}")
        if ref is None:
            out.append({"state": "no-remote-ref", "remote": remote,
                        "detail": f"no remote-tracking ref for {remote}/{branch}: this branch has "
                                  f"never been pushed there, or the remote is not configured"})
            continue
        if ref != head:
            ahead = git(root, "rev-list", "--count", f"{remote}/{branch}..HEAD") or "?"
            if ahead not in ("0", "?"):
                out.append({"state": "unpushed", "remote": remote, "count": ahead,
                            "detail": f"{ahead} commit(s) on {branch} exist only here. Content "
                                      f"checks stay green while work sits on one disk"})
    return out


def check_canonical(root, canonical):
    if not canonical:
        return []
    def norm(p):
        return os.path.normcase(os.path.abspath(p)).rstrip(os.sep)
    if norm(canonical) == norm(root):
        return []
    return [{"state": "non-canonical-copy", "here": os.path.abspath(root), "canonical": canonical,
             "detail": "this is not the canonical working copy. Edits here commit cleanly, pass "
                       "every content check, and are stranded. The marker travels with a copy, "
                       "which is what lets a copy report that it is one"}]


def check_receipts(root, receipts):
    out = []
    now = time.time()
    for r in receipts or []:
        name, rel = r.get("name", "?"), r.get("path")
        max_age = float(r.get("max_age_hours", 24))
        p = os.path.join(root, rel) if rel else None
        if not p or not os.path.isfile(p):
            out.append({"state": "receipt-missing", "job": name,
                        "detail": f"no receipt at {rel}: the job has not reported completing, and "
                                  f"a job that never ran looks exactly like one that never wrote"})
            continue
        age_h = (now - os.path.getmtime(p)) / 3600.0
        if age_h > max_age:
            out.append({"state": "receipt-stale", "job": name, "age_hours": round(age_h, 1),
                        "detail": f"last receipt is {age_h:.1f}h old, past the {max_age:.0f}h "
                                  f"expectation: the job has stopped running and nothing said so"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("VAULT_ROOT") or ".")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    manifest = os.environ.get("CUSTODY_MANIFEST", "")
    if not manifest:
        print("custody-audit: CUSTODY_MANIFEST not set; no artifacts are declared as kept.\n"
              "  Set it to a manifest to enable the custody checks.", file=sys.stderr)
        return EXIT_UNCONFIGURED

    root = os.path.abspath(args.root)
    m = load(manifest)
    findings = (check_artifacts(root, m.get("artifacts") or [])
                + check_pushed(root, m.get("remotes"))
                + check_canonical(root, m.get("canonical_root"))
                + check_receipts(root, m.get("receipts")))

    if args.json:
        print(json.dumps({"root": root, "manifest": manifest, "findings": findings}, indent=2))
        return EXIT_FINDINGS if findings else EXIT_OK

    if not findings:
        print("custody-audit OK: every declared artifact is kept, and HEAD is where it should be")
        return EXIT_OK
    print(f"custody-audit: {len(findings)} finding(s)")
    for f in findings:
        print(f"  [{f['state']}] {f.get('path') or f.get('job') or f.get('remote') or ''}")
        print(f"      {f['detail']}")
    return EXIT_FINDINGS


if __name__ == "__main__":
    sys.exit(main())
