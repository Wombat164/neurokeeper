#!/usr/bin/env python3
# @capability:  ref-audit
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/vault-ref-audit.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""vault-ref-audit.py -- deterministic, READ-ONLY reference-integrity audit for a markdown vault.

Reports (never mutates anything):
  broken_links   a wikilink / markdown-link / embed whose target resolves to no file
  orphans        notes with ZERO inbound links
  dead_ends      notes with ZERO outbound links
  broken_canvas  a .canvas file-node pointing at a missing file
  broken_base    a .base reference pointing at a missing file (best-effort)
  orphan_media   attachment files (images / pdf / ...) referenced by nothing

Wikilink parsing goes through the backend contract (get_backend().find_links); a markdown-link pass
covers `[a](t)` / `![a](t)`. Resolution follows Obsidian semantics: basename / shortest-path,
case-insensitive; an extension-less target is a NOTE, a target with an extension is a file. This is the
read-only counterpart to vault-name-reconcile (which can rewrite links but could not, before this,
audit them); it also covers the .canvas / .base / orphan-media gaps no GUI-free tool fills.

Unresolved wikilinks are reported but are INFORMATIONAL by default: in Obsidian a `[[link]]` to a
not-yet-created note is a legitimate forward-reference, so they do not fail `--check` unless `--strict`.
canvas / base broken refs are always real defects and fail `--check`.

Usage: vault-ref-audit.py [--json] [--check] [--strict] [--since <git-ref>]
                          [--write-baseline <file> | --baseline <file>]
  --since <git-ref>       : report only findings for notes changed since <git-ref> (the scan stays
                            graph-global; only the surfaced findings and the --check gate are narrowed).
  --write-baseline <file> : write the current findings as an accepted baseline, then exit 0.
  --baseline <file>       : report only NET-NEW findings (those absent from the baseline), and gate
                            --check on them, so a dirty vault can adopt the tool on day one.
  --sarif                 : emit findings as SARIF 2.1.0 (GitHub code-scanning) via the Findings IR;
                            composes with --since / --baseline (the SARIF is built from the scoped set).
  --check  : exit 1 on broken canvas / base refs (always-defects). orphans / dead-ends / media /
             unresolved-links are informational and do not fail.
  --strict : also count unresolved links as failures under --check.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _vault_lib import VAULT  # noqa: E402
try:
    from _vault_lib import force_utf8_stdout
    force_utf8_stdout()
except Exception:
    pass
from _backend import get_backend  # noqa: E402
from _findings import Finding, pkg_version, to_sarif  # noqa: E402

NOTE_EXTS = {".md", ".markdown"}
# Root config/meta notes -- resolvable as link targets, but their own links are NOT audited (e.g.
# CLAUDE.md ships `[[wikilinks]]` examples that are not real links).
META_FILES = {"CLAUDE.md", "README.md"}
MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".pdf",
              ".mp4", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".ogg", ".excalidraw"}
# Dirs that never hold vault content (system/tool). Unlike VAULT_SCAN_EXCLUDE this does NOT exclude
# attachment dirs -- the audit must SEE media to flag orphans. Override via VAULT_REFAUDIT_EXCLUDE.
WALK_EXCLUDE = tuple(x for x in (os.environ.get("VAULT_REFAUDIT_EXCLUDE")
                                 or ".obsidian,.git,.trash,.claude,node_modules").split(",") if x)
_MDLINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_URI = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.I)
_FENCE = re.compile(r"```.*?```", re.S)
_BASE_REF = re.compile(r'["\']([^"\']+\.(?:md|canvas|png|jpe?g|gif|svg|webp|pdf|excalidraw))["\']', re.I)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)")
_BLOCKID = re.compile(r"\s\^([A-Za-z0-9][\w-]*)\s*$")


def _norm_heading(s):
    return re.sub(r"[^a-z0-9 ]+", "", s.lower()).strip()


def _heading_block_index(body):
    """(normalized heading-slug set, block-id set) for resolving [[note#heading]] / [[note#^block]] anchors."""
    heads, blocks = set(), set()
    for line in body.splitlines():
        hm = _HEADING.match(line)
        if hm:
            heads.add(_norm_heading(hm.group(1).rstrip("# ").strip()))
        bm = _BLOCKID.search(line)
        if bm:
            blocks.add(bm.group(1).lower())
    return heads, blocks


def _walk_all(vault):
    for root, dirs, files in os.walk(vault):
        rel = os.path.relpath(root, vault)
        rel = "" if rel == "." else rel.replace(os.sep, "/")
        if rel and any(rel == e or rel.startswith(e + "/") for e in WALK_EXCLUDE):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in WALK_EXCLUDE and not d.startswith(".")]  # Obsidian ignores dot-dirs (tool caches, .obsidian, ...)
        for f in files:
            yield (rel + "/" + f) if rel else f


def _arg_value(args, flag):
    """The token after `flag`, or None. Refs never start with '-', so a bare flag yields None."""
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args) and not args[i + 1].startswith("-"):
            return args[i + 1]
    return None


def _changed_since(vault, ref):
    """Set of vault-relative posix paths changed vs `ref` (git diff --name-only). Exits 2 on git error
    rather than silently scanning the wrong scope. Includes staged + unstaged changes vs the ref."""
    import subprocess

    def _git(*a):
        return subprocess.run(["git", "-C", vault, *a], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    top = _git("rev-parse", "--show-toplevel")
    if top.returncode != 0:
        sys.stderr.write(f"ref-audit --since: '{vault}' is not inside a git repository.\n")
        sys.exit(2)
    root = top.stdout.strip()
    diff = _git("diff", "--name-only", ref)
    if diff.returncode != 0:
        sys.stderr.write(f"ref-audit --since: 'git diff {ref}' failed: {diff.stderr.strip()}\n")
        sys.exit(2)
    changed = set()
    for line in diff.stdout.splitlines():
        line = line.strip()
        if line:
            rel = os.path.relpath(os.path.join(root, line), vault).replace(os.sep, "/")
            changed.add(rel)
    return changed


def _finding_fp(kind, x):
    """A stable, human-readable fingerprint for one finding. Broken links/anchors key on the missing
    TARGET (a renamed source note does not resurrect the issue); connectivity findings key on the note
    path. Kept plain-text so a baseline file stays reviewable in a diff."""
    if kind == "broken_link":
        return f"broken_link|{x['target']}"
    if kind == "broken_anchor":
        return f"broken_anchor|{x['target']}"
    if kind == "broken_canvas":
        return f"broken_canvas|{x['canvas']}|{x['target']}"
    if kind == "broken_base":
        return f"broken_base|{x['base']}|{x['target']}"
    return f"{kind}|{x}"          # orphan / dead_end / isolated / orphan_media: x is the note path


_FP_LIST_KINDS = ("broken_link", "broken_anchor", "broken_canvas", "broken_base",
                  "orphan", "dead_end", "isolated", "orphan_media")


def _all_fps(lists):
    """Sorted, de-duplicated fingerprints for every finding in a {kind: list} mapping."""
    fps = set()
    for kind in _FP_LIST_KINDS:
        for x in lists[kind]:
            fps.add(_finding_fp(kind, x))
    return sorted(fps)


def _load_baseline(path):
    """Fingerprints from a baseline file (one per line; '#' comments and blanks ignored)."""
    out = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.add(line)
    except FileNotFoundError:
        sys.stderr.write(f"ref-audit --baseline: file not found: {path}\n")
        sys.exit(2)
    return out


def _to_findings(bl, ba, bc, bb, orph, de, iso, om, strict):
    """Convert ref-audit's finding lists into the canonical Findings IR (scripts/_findings.py)."""
    f = []
    for x in bl:
        f.append(Finding("ref-audit", "broken-link", "error" if strict else "warning", x["note"],
                         None, f"link to '{x['target']}' resolves to no note", _finding_fp("broken_link", x)))
    for x in ba:
        f.append(Finding("ref-audit", "broken-anchor", "note", x["note"], None,
                         f"anchor '{x['target']}' has no matching heading or block", _finding_fp("broken_anchor", x)))
    for x in bc:
        f.append(Finding("ref-audit", "broken-canvas-ref", "error", x["canvas"], None,
                         f"canvas references missing file '{x['target']}'", _finding_fp("broken_canvas", x)))
    for x in bb:
        f.append(Finding("ref-audit", "broken-base-ref", "error", x["base"], None,
                         f"base references missing '{x['target']}'", _finding_fp("broken_base", x)))
    for p in orph:
        f.append(Finding("ref-audit", "orphan", "note", p, None, "note has no inbound links", _finding_fp("orphan", p)))
    for p in de:
        f.append(Finding("ref-audit", "dead-end", "note", p, None, "note has no outbound links", _finding_fp("dead_end", p)))
    for p in iso:
        f.append(Finding("ref-audit", "isolated", "note", p, None, "note is fully disconnected", _finding_fp("isolated", p)))
    for p in om:
        f.append(Finding("ref-audit", "orphan-media", "note", p, None, "attachment referenced by nothing", _finding_fp("orphan_media", p)))
    return f


def main():
    args = sys.argv[1:]
    as_json, check, strict = "--json" in args, "--check" in args, "--strict" in args
    since = _arg_value(args, "--since")
    baseline_path = _arg_value(args, "--baseline")
    write_baseline = _arg_value(args, "--write-baseline")
    backend = get_backend()

    all_files = list(_walk_all(VAULT))
    notes_by_stem, files_by_name, notes = {}, {}, []
    for rp in all_files:
        base = rp.split("/")[-1]
        stem, ext = os.path.splitext(base)
        files_by_name.setdefault(base.lower(), []).append(rp)
        if ext.lower() in NOTE_EXTS:
            notes_by_stem.setdefault(stem.lower(), []).append(rp)   # resolvable as a link target
            if rp not in META_FILES:                                # but don't AUDIT config/meta notes
                notes.append(rp)

    def _shortest(paths):
        return min(paths, key=lambda p: (p.count("/"), len(p))) if paths else None

    def resolve(target):
        """Return the resolved relpath, '__external__' for a URL, or None if broken (Obsidian semantics)."""
        t = (target or "").strip().replace("\\", "/")
        if not t or t.startswith("#"):
            return "__external__"            # intra-doc anchor -- not a file ref, never "broken"
        if _URI.match(t):
            return "__external__"
        base = t.split("/")[-1]
        stem, ext = os.path.splitext(base)
        if "/" in t:
            cands = [t.lower()] + ([t.lower() + ".md"] if not ext else [])
            hits = [rp for rp in all_files if rp.lower() in cands or any(rp.lower().endswith("/" + c) for c in cands)]
            if hits:
                return _shortest(hits)
        if ext:
            return _shortest(files_by_name.get(base.lower(), []))
        return _shortest(notes_by_stem.get(stem.lower(), [])) or _shortest(files_by_name.get(base.lower(), []))

    inbound = {rp: 0 for rp in notes}
    outbound = {rp: 0 for rp in notes}
    referenced, broken_links = set(), []
    headings_by_note = {}          # relpath -> (heading-slug set, block-id set), for anchor resolution
    anchor_links = []              # (source, resolved-note, anchor) for links carrying a #heading / #^block

    for rp in notes:
        try:
            text = open(os.path.join(VAULT, rp.replace("/", os.sep)), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        body = _FENCE.sub("", text)
        headings_by_note[rp] = _heading_block_index(body)
        pairs = [(lk.target, lk.anchor) for _s, lk in backend.find_links(body)]   # wikilinks carry .anchor
        for m in _MDLINK.finditer(body):
            t, _, a = m.group(1).split('"')[0].strip().partition("#")
            pairs.append((t.strip(), a.strip()))
        for tgt, anchor in pairs:
            tgt = (tgt or "").strip()
            if not tgt or tgt.startswith("#"):
                continue
            outbound[rp] += 1
            r = resolve(tgt)
            if r is None:
                broken_links.append({"note": rp, "target": tgt})
            elif r != "__external__":
                referenced.add(r)
                if r in inbound:
                    inbound[r] += 1
                if anchor:
                    anchor_links.append((rp, r, anchor))

    broken_canvas = []
    for rp in (f for f in all_files if f.endswith(".canvas")):
        try:
            data = json.load(open(os.path.join(VAULT, rp.replace("/", os.sep)), encoding="utf-8"))
        except Exception:
            continue
        for node in (data.get("nodes") or []):
            if node.get("type") == "file" and node.get("file"):
                r = resolve(node["file"])
                if r is None:
                    broken_canvas.append({"canvas": rp, "target": node["file"]})
                elif r != "__external__":
                    referenced.add(r)

    broken_base = []
    for rp in (f for f in all_files if f.endswith(".base")):
        try:
            raw = open(os.path.join(VAULT, rp.replace("/", os.sep)), encoding="utf-8").read()
        except OSError:
            continue
        for m in _BASE_REF.finditer(raw):
            r = resolve(m.group(1))
            if r is None:
                broken_base.append({"base": rp, "target": m.group(1)})
            elif r != "__external__":
                referenced.add(r)

    orphans = sorted(rp for rp in notes if inbound[rp] == 0)
    dead_ends = sorted(rp for rp in notes if outbound[rp] == 0)
    orphan_media = sorted(rp for rp in all_files
                          if os.path.splitext(rp)[1].lower() in MEDIA_EXTS and rp not in referenced)
    # exact name/stem collisions: a bare [[stem]] to a duplicated stem is ambiguous -- Obsidian resolves
    # it to one shortest-path note. Informational (same basename in different folders is legal, and a
    # path-qualified [[folder/stem]] still resolves), surfaced like orphans.
    stem_collisions = sorted(({"stem": s, "paths": sorted(p)} for s, p in notes_by_stem.items() if len(p) > 1),
                             key=lambda x: x["stem"])
    isolated = sorted(set(orphans) & set(dead_ends))   # neither inbound nor outbound (fully disconnected)
    # broken anchors: a link resolves the file but its #heading / #^block target does not exist. INFORMATIONAL
    # (heading drift is common; never gates), like unresolved links.
    broken_anchors = []
    for src, tgt, anchor in anchor_links:
        idx = headings_by_note.get(tgt)
        if idx is None:
            continue                                   # target not an audited note (media/meta) -> no anchors
        heads, blocks = idx
        a = anchor.strip().lstrip("#")
        ok = (a[1:].lower() in blocks) if a.startswith("^") else (_norm_heading(a) in heads)
        if a and not ok:
            broken_anchors.append({"note": src, "target": f"{tgt}#{anchor}"})
    broken_anchors.sort(key=lambda b: b["note"])

    # --baseline / --write-baseline: track known debt so a run reports only NET-NEW findings. Computed
    # against the WHOLE-vault findings (before any --since scoping) so the baseline is complete.
    _lists_full = {"broken_link": broken_links, "broken_anchor": broken_anchors,
                   "broken_canvas": broken_canvas, "broken_base": broken_base,
                   "orphan": orphans, "dead_end": dead_ends, "isolated": isolated,
                   "orphan_media": orphan_media}
    if write_baseline:
        fps = _all_fps(_lists_full)
        with open(write_baseline, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# neurokeeper ref-audit baseline: accepted findings (CI gates on NET-NEW only).\n")
            fh.write("# Regenerate after fixing debt to shrink it. One fingerprint per line.\n")
            fh.write("\n".join(fps) + ("\n" if fps else ""))
        sys.stderr.write(f"ref-audit: wrote {len(fps)} accepted findings to baseline {write_baseline}\n")
        sys.exit(0)
    current_fps = set(_all_fps(_lists_full)) if baseline_path else set()

    # --since: filter the REPORTED findings to notes changed vs a git ref. The scan stays graph-global
    # (a renamed target breaks backlinks in unchanged files, so the whole graph must be built); only the
    # surfaced findings, and therefore the --check gate, are narrowed to the diff. Ideal for pre-commit / CI.
    scope = None
    if since:
        changed = _changed_since(VAULT, since)
        broken_links = [x for x in broken_links if x["note"] in changed]
        broken_canvas = [x for x in broken_canvas if x["canvas"] in changed]
        broken_base = [x for x in broken_base if x["base"] in changed]
        broken_anchors = [x for x in broken_anchors if x["note"] in changed]
        orphans = [p for p in orphans if p in changed]
        dead_ends = [p for p in dead_ends if p in changed]
        isolated = [p for p in isolated if p in changed]
        orphan_media = [p for p in orphan_media if p in changed]
        stem_collisions = [c for c in stem_collisions if any(p in changed for p in c["paths"])]
        scope = {"since": since, "changed_paths": len(changed), "scanned_notes": len(notes)}

    # --baseline: drop findings already accepted in the baseline file, so only NET-NEW debt is reported
    # (and gates --check). A finding fixed since the baseline was written is counted as "resolved".
    baseline_info = None
    if baseline_path:
        base = _load_baseline(baseline_path)
        broken_links = [x for x in broken_links if _finding_fp("broken_link", x) not in base]
        broken_anchors = [x for x in broken_anchors if _finding_fp("broken_anchor", x) not in base]
        broken_canvas = [x for x in broken_canvas if _finding_fp("broken_canvas", x) not in base]
        broken_base = [x for x in broken_base if _finding_fp("broken_base", x) not in base]
        orphans = [p for p in orphans if _finding_fp("orphan", p) not in base]
        dead_ends = [p for p in dead_ends if _finding_fp("dead_end", p) not in base]
        isolated = [p for p in isolated if _finding_fp("isolated", p) not in base]
        orphan_media = [p for p in orphan_media if _finding_fp("orphan_media", p) not in base]
        baseline_info = {"file": baseline_path, "size": len(base), "resolved": len(base - current_fps)}

    # Unresolved wikilinks are often INTENTIONAL in Obsidian (forward-links to not-yet-created notes), so
    # --check fails only on canvas/base broken refs (always-defects) unless --strict adds unresolved links.
    hard_defects = len(broken_canvas) + len(broken_base) + (len(broken_links) if strict else 0)
    result = {
        "notes": len(notes), "files": len(all_files),
        "counts": {"broken_links": len(broken_links), "broken_canvas": len(broken_canvas),
                   "broken_base": len(broken_base), "broken_anchors": len(broken_anchors),
                   "orphans": len(orphans), "dead_ends": len(dead_ends), "isolated": len(isolated),
                   "orphan_media": len(orphan_media), "stem_collisions": len(stem_collisions)},
        "broken_links": broken_links, "broken_canvas": broken_canvas, "broken_base": broken_base,
        "broken_anchors": broken_anchors,
        "orphans": orphans, "dead_ends": dead_ends, "isolated": isolated, "orphan_media": orphan_media,
        "stem_collisions": stem_collisions, "scope": scope, "baseline": baseline_info,
    }

    if "--sarif" in args:                               # canonical Findings IR -> SARIF 2.1.0
        findings = _to_findings(broken_links, broken_anchors, broken_canvas, broken_base,
                                orphans, dead_ends, isolated, orphan_media, strict)
        print(json.dumps(to_sarif(findings, tool_version=pkg_version()), indent=2, ensure_ascii=False))
        sys.exit(1 if (check and hard_defects) else 0)
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1 if (check and hard_defects) else 0)
    if check:
        if hard_defects:
            extra = f", {len(broken_links)} unresolved links" if strict else ""
            print(f"REF-AUDIT FAIL: {len(broken_canvas)} broken canvas, {len(broken_base)} broken base refs{extra}")
            sys.exit(1)
        print(f"ref-audit OK: 0 broken canvas/base refs ({len(notes)} notes; "
              f"{len(broken_links)} unresolved links [informational], orphans {len(orphans)}, "
              f"dead-ends {len(dead_ends)}, orphan-media {len(orphan_media)})")
        sys.exit(0)

    def _section(title, items, fmt, limit=25):
        print(f"\n{title}: {len(items)}")
        for it in items[:limit]:
            print("  " + fmt(it))
        if len(items) > limit:
            print(f"  ... +{len(items) - limit} more")

    print(f"=== VAULT REF AUDIT ({len(notes)} notes, {len(all_files)} files) ===")
    if scope:
        print(f"    scope: findings for {scope['changed_paths']} path(s) changed since {scope['since']} "
              f"(full graph scanned over {scope['scanned_notes']} notes)")
    if baseline_info:
        b = baseline_info
        nag = f", {b['resolved']} now resolved (rewrite --write-baseline to shrink)" if b["resolved"] else ""
        print(f"    baseline {b['file']}: {b['size']} accepted, reporting net-new only{nag}")
    _section("unresolved links (incl. intentional forward-links; informational)", broken_links,
             lambda b: f"{b['note']}  ->  {b['target']}")
    _section("broken canvas refs", broken_canvas, lambda b: f"{b['canvas']}  ->  {b['target']}", 15)
    _section("broken base refs", broken_base, lambda b: f"{b['base']}  ->  {b['target']}", 15)
    _section("broken anchors (file resolves, #heading/#^block does not; informational)", broken_anchors,
             lambda b: f"{b['note']}  ->  {b['target']}", 20)
    _section("orphans (no inbound)", orphans, lambda o: o, 20)
    _section("dead-ends (no outbound)", dead_ends, lambda o: o, 20)
    _section("isolated (no inbound AND no outbound)", isolated, lambda o: o, 20)
    _section("orphan media (referenced by nothing)", orphan_media, lambda o: o, 20)
    _section("name/stem collisions (ambiguous bare-link resolution)", stem_collisions,
             lambda c: f"{c['stem']}  ->  {', '.join(c['paths'])}", 15)


if __name__ == "__main__":
    main()
