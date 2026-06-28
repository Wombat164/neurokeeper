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

Usage: vault-ref-audit.py [--json] [--check] [--strict]
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


def _walk_all(vault):
    for root, dirs, files in os.walk(vault):
        rel = os.path.relpath(root, vault)
        rel = "" if rel == "." else rel.replace(os.sep, "/")
        if rel and any(rel == e or rel.startswith(e + "/") for e in WALK_EXCLUDE):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in WALK_EXCLUDE]
        for f in files:
            yield (rel + "/" + f) if rel else f


def main():
    args = sys.argv[1:]
    as_json, check, strict = "--json" in args, "--check" in args, "--strict" in args
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

    for rp in notes:
        try:
            text = open(os.path.join(VAULT, rp.replace("/", os.sep)), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        body = _FENCE.sub("", text)
        targets = [lk.target for _s, lk in backend.find_links(body)]
        targets += [m.group(1).split("#")[0].split('"')[0].strip() for m in _MDLINK.finditer(body)]
        for tgt in targets:
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

    # Unresolved wikilinks are often INTENTIONAL in Obsidian (forward-links to not-yet-created notes), so
    # --check fails only on canvas/base broken refs (always-defects) unless --strict adds unresolved links.
    hard_defects = len(broken_canvas) + len(broken_base) + (len(broken_links) if strict else 0)
    result = {
        "notes": len(notes), "files": len(all_files),
        "counts": {"broken_links": len(broken_links), "broken_canvas": len(broken_canvas),
                   "broken_base": len(broken_base), "orphans": len(orphans), "dead_ends": len(dead_ends),
                   "orphan_media": len(orphan_media), "stem_collisions": len(stem_collisions)},
        "broken_links": broken_links, "broken_canvas": broken_canvas, "broken_base": broken_base,
        "orphans": orphans, "dead_ends": dead_ends, "orphan_media": orphan_media,
        "stem_collisions": stem_collisions,
    }

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
    _section("unresolved links (incl. intentional forward-links; informational)", broken_links,
             lambda b: f"{b['note']}  ->  {b['target']}")
    _section("broken canvas refs", broken_canvas, lambda b: f"{b['canvas']}  ->  {b['target']}", 15)
    _section("broken base refs", broken_base, lambda b: f"{b['base']}  ->  {b['target']}", 15)
    _section("orphans (no inbound)", orphans, lambda o: o, 20)
    _section("dead-ends (no outbound)", dead_ends, lambda o: o, 20)
    _section("orphan media (referenced by nothing)", orphan_media, lambda o: o, 20)
    _section("name/stem collisions (ambiguous bare-link resolution)", stem_collisions,
             lambda c: f"{c['stem']}  ->  {', '.join(c['paths'])}", 15)


if __name__ == "__main__":
    main()
