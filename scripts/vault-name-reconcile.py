#!/usr/bin/env python3
# @capability:  name-reconcile
# @compute:     deterministic
# @effect:      mutating
# @engine:      scripts/vault-name-reconcile.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   attended-exempt (optional VAULT_FORBIDDEN_ZONES)
# @audit:       git
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""Deterministic filename reconciliation: de-dash + kebab-case.

DETECTS non-kebab filenames (the ' -- ' separator, em/en-dashes, double-hyphen, Title-Case, spaces) and
PROPOSES a kebab-case slug. LINK-AWARE --apply: when it renames a note it FIRST rewrites every wikilink
that referenced the old basename ([[x]], [[x|alias]], [[x#h]], ![[x]], [[folder/x]]) across the whole
vault, THEN renames the file -- so links never break. (Obsidian's in-app rename does this natively for a
single file; this is the bulk fallback -- see docs/SOURCES.md ecosystem doctrine.)

Read-only proposal by default. --apply is a MUTATING bulk write: guarded by assert_obsidian_closed()
(the linter-race) + --force overrides. git is the audit. The configured no-rename zones
(VAULT_NORENAME_ZONES) are EXCLUDED from RENAME (audit-trail) but still SCANNED as link-sources so their
links to renamed notes stay valid.

--mode kebab (default; full lowercase-hyphen slug) | dedash (light; only ' -- '/em-dash -> ' - ', keep case)
Usage: python scripts/vault-name-reconcile.py [--json] [dedash] [--apply] [--force]
"""
import os, re, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _vault_lib import (VAULT, md_files, folder_suffixes, kebabify, DASH,
                        safe_write, within_vault, VaultWriteError, in_forbidden_zone,
                        force_utf8_stdout)  # shared core
try:
    from _vault_guard import assert_obsidian_closed
except Exception:
    def assert_obsidian_closed(force=False): pass

EXCLUDE_RENAME = tuple(x for x in (os.environ.get("VAULT_NORENAME_ZONES") or "").split(",") if x)

def dedash(stem):
    return re.sub(r"\s+", " ", DASH.sub(" - ", stem)).strip()

def excluded(rel):
    return any(rel == e or rel.startswith(e + os.sep) for e in EXCLUDE_RENAME)

def build(mode, under=None):
    transform = kebabify if mode == "kebab" else dedash
    renames = []
    for path, rel in md_files():
        stem = os.path.splitext(os.path.basename(path))[0]
        if rel and (excluded(rel) or in_forbidden_zone(rel)): continue
        if under and not (rel == under or rel.startswith(under + os.sep)): continue   # pilot one folder
        if stem.startswith("."): continue                       # hidden dotfiles (Obsidian-ignored markers)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stem): continue   # daily notes
        new = transform(stem)
        if new and new != stem:
            renames.append((path, rel, stem, new))
    bydir = {}
    for path, rel, stem, new in renames:
        bydir.setdefault((rel, new), []).append(stem)
    collisions = {k: v for k, v in bydir.items() if len(v) > 1}
    return renames, collisions

def main():
    force_utf8_stdout()
    args = sys.argv[1:]
    mode = "dedash" if "dedash" in args else "kebab"
    under = args[args.index("--under") + 1] if "--under" in args and args.index("--under") + 1 < len(args) else None
    renames, collisions = build(mode, under)
    dash_n = sum(1 for _, _, stem, _ in renames if DASH.search(stem))
    if "--json" in args:
        print(json.dumps({"mode": mode, "rename_count": len(renames), "has_dash": dash_n,
                          "collisions": {f"{r}/{n}": v for (r, n), v in collisions.items()},
                          "sample": [{"from": s, "to": nw} for _, _, s, nw in renames[:30]]},
                         indent=2, ensure_ascii=False)); return
    if "--apply" not in args:
        print(f"=== NAME RECONCILE (proposal, mode={mode}) ===")
        print(f"renameable notes: {len(renames)}  (of which contain '--'/em-dash: {dash_n})")
        print(f"collisions (would clash -> skipped): {len(collisions)}")
        print("(read-only; --apply + Obsidian CLOSED to rename, link-aware; forbidden/legal zones excluded)\n")
        for _, _, s, nw in renames[:20]:
            print(f"  {s}\n    -> {nw}")
        if len(renames) > 20: print(f"  ... +{len(renames) - 20} more")
        if collisions:
            print("\nCOLLISIONS (resolve before apply):")
            for (r, n), v in list(collisions.items())[:10]: print(f"  {r}/{n}.md  <=  {v}")
        return
    # --apply : link-aware bulk rename
    assert_obsidian_closed("--force" in args)
    if not EXCLUDE_RENAME and "--no-exclusions" not in args:
        print("REFUSING --apply: VAULT_NORENAME_ZONES is unset -> EVERY zone (incl. legal/archive/source)\n"
              "would be renamed. Set VAULT_NORENAME_ZONES, or pass --no-exclusions to override.", file=sys.stderr)
        sys.exit(2)
    # Decide the FINAL rename set BEFORE rewriting any link. A stem whose target already exists as a
    # DIFFERENT file must NOT have its links repointed (the clobber gap -> misdirected/orphaned links).
    # Case-only renames (Foo->foo on a case-insensitive FS) are allowed via a two-step rename.
    rmap, plan = {}, []                                  # plan: (src_path, new_stem, two_step)
    for path, rel, stem, new in renames:
        if (rel, new) in collisions: continue
        dst = os.path.join(os.path.dirname(path), new + ".md")
        if os.path.exists(dst):
            if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(path)):
                plan.append((path, new, True))          # case-only rename of the SAME file
            else:
                continue                                 # real pre-existing target -> skip, do NOT rewrite links
        else:
            plan.append((path, new, False))
        rmap[stem] = new
    if not rmap: print("nothing to rename"); return
    # path-prefix may ONLY be a REAL vault folder (folder_suffixes), never arbitrary text-before-'/'
    # (which corrupted links whose TITLE contains '/', e.g. "TCP/IP" -- the 2026-06-27 bug).
    folders = folder_suffixes(VAULT)
    PATH = ("(?:" + "|".join(re.escape(f) for f in sorted(folders, key=len, reverse=True)) + ")?") if folders else ""
    # ONE combined regex (folder-suffix alt + all-stems alt, both longest-first) -> single pass per file.
    # Lookahead includes '\\' so escaped-pipe links [[stem\|alias]] (common in tables) are rewritten too.
    stems_alt = "|".join(re.escape(s) for s in sorted(rmap, key=len, reverse=True))
    big = re.compile(r"(!?\[\[" + PATH + r")(" + stems_alt + r")(?=[\]|#\\])")
    link_edits = 0
    for path, rel in md_files():
        if in_forbidden_zone(rel): continue          # VAULT_FORBIDDEN_ZONES: never write these files
        try: t = open(path, encoding="utf-8", newline="").read()     # newline='' preserves CRLF/LF
        except (UnicodeDecodeError, OSError): continue                # skip unreadable (no replace-then-write)
        nt = big.sub(lambda m: m.group(1) + rmap[m.group(2)], t)
        if nt != t:
            try:
                safe_write(path, nt); link_edits += 1     # symlink/out-of-vault writes refused
            except VaultWriteError as e:
                print(f"  skip (guard): {e}", file=sys.stderr)
    renamed = 0
    for path, new, two_step in plan:
        if os.path.islink(path): continue            # never rename through a symlink
        d = os.path.dirname(path); dst = os.path.join(d, new + ".md")
        if not within_vault(d): continue             # confine the destination within the vault
        if two_step:                                     # Foo.md -> Foo.tmp-rename~ -> foo.md (case-insensitive FS)
            tmp = os.path.join(d, new + ".tmp-rename~")
            os.rename(path, tmp); os.rename(tmp, dst); renamed += 1
        elif not os.path.exists(dst):
            os.rename(path, dst); renamed += 1
    print(f"renamed {renamed} files; rewrote links in {link_edits} files (git diff to review)")

if __name__ == "__main__":
    main()
