#!/usr/bin/env python3
# @capability:  note-type-migration
# @compute:     deterministic
# @effect:      mutating
# @engine:      scripts/vault-set-note-type.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   scoped (folder-allowlist; optional VAULT_FORBIDDEN_ZONES)
# @audit:       git
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""vault-set-note-type.py -- additive, idempotent note_type setter (KOS typology).
Derives note_type from folder (see DERIVE), overrides to 'spec' if an x-as-code kind: is present.
ADDITIVE ONLY: inserts one frontmatter line; never rewrites content; preserves CRLF/LF; skips notes
without frontmatter and notes that already have note_type. Dry-run by default; pass --apply to write.

Scope: whatever folders the DERIVE map covers (set VAULT_NOTE_TYPE_MAP to your vault's folders).
Additive only -> safe even over curated/legal zones: it never alters existing content, it only inserts
a missing note_type line (deterministic, operator-watched, git-audited).
Usage: python scripts/vault-set-note-type.py [--apply]
"""
import os, re, sys, json
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _vault_guard import assert_obsidian_closed
except Exception:
    def assert_obsidian_closed(force=False): pass
from _vault_lib import VAULT, safe_write, VaultWriteError, in_forbidden_zone, force_utf8_stdout

# The folder -> note_type map (DERIVE) and the path-substring sub-overrides (SUBRULE) are vault-specific.
# They default to a small GENERIC example and are overridden from the environment (JSON) so the engine
# stays vault-agnostic:
#   VAULT_NOTE_TYPE_MAP       JSON object  {"<folder>": "<note_type>", ...}
#   VAULT_NOTE_TYPE_SUBRULES  JSON array   [["<path-substring>", "<note_type>"], ...]
_DEFAULT_DERIVE = {
    "01 - Daily": "daily",
    "02 - Projects": "project",
    "03 - Domains": "note",
    "04 - Meetings": "meeting",
    "templates": "template",
    "moc": "moc",
}
# path-substring sub-overrides (checked before the folder default)
_DEFAULT_SUBRULE = [["sent-mails", "outbox"], ["/actions/", "outbox"],
                    ["/deliverables/", "outbox"], ["/mail/", "outbox"]]
DERIVE = json.loads(os.environ["VAULT_NOTE_TYPE_MAP"]) if os.environ.get("VAULT_NOTE_TYPE_MAP") else _DEFAULT_DERIVE
SUBRULE = json.loads(os.environ["VAULT_NOTE_TYPE_SUBRULES"]) if os.environ.get("VAULT_NOTE_TYPE_SUBRULES") else _DEFAULT_SUBRULE

def main():
    force_utf8_stdout()
    apply = "--apply" in sys.argv
    if apply:
        assert_obsidian_closed("--force" in sys.argv)
    per = Counter(); skipped_nofm = Counter(); skipped_has = Counter(); spec = 0
    for top, nt in DERIVE.items():
        base = os.path.join(VAULT, top)
        if not os.path.isdir(base):
            print(f"WARN: missing {top}"); continue
        for root, dirs, files in os.walk(base):
            if in_forbidden_zone(os.path.relpath(root, VAULT)):   # VAULT_FORBIDDEN_ZONES: skip subtree
                dirs[:] = []; continue
            for f in files:
                if not f.endswith(".md"): continue
                p = os.path.join(root, f)
                try:
                    text = open(p, encoding="utf-8", newline="").read()   # newline='' preserves CRLF/LF (CRLF-detect below depends on it)
                except (UnicodeDecodeError, OSError):
                    continue
                if not text.startswith("---"):
                    skipped_nofm[top] += 1; continue
                end = text.find("\n---", 3)
                if end == -1:
                    skipped_nofm[top] += 1; continue
                fm = text[3:end]
                if re.search(r"(?m)^note_type:", fm):
                    skipped_has[top] += 1; continue
                val = nt
                pl = p.replace(os.sep, "/")
                for sub, sv in SUBRULE:
                    if sub in pl:
                        val = sv; break
                m = re.search(r"(?m)^kind:\s*([A-Za-z][\w-]*)", fm)
                if top != "11 - Outbox" and m and m.group(1)[0].isupper():
                    val = "spec"; spec += 1
                nl = "\r\n" if "\r\n" in text[:300] else "\n"
                new = text[:3] + nl + "note_type: " + val + text[3:]
                if apply:
                    try:
                        safe_write(p, new)   # symlink/out-of-vault writes refused
                    except VaultWriteError as e:
                        print(f"  skip (guard): {e}", file=sys.stderr); continue
                per[(top, val)] += 1

    mode = "APPLIED" if apply else "DRY-RUN (no writes; pass --apply)"
    print(f"=== note_type migration [{mode}] ===")
    total = sum(per.values())
    for (top, val), c in sorted(per.items()):
        print(f"  {top:18} -> note_type: {val:8} : {c}")
    print(f"  (spec overrides from x-as-code kind: {spec})")
    print(f"TOTAL would-set/set: {total}")
    print(f"skipped (already has note_type): {dict(skipped_has)}")
    print(f"skipped (no frontmatter, manual): {dict(skipped_nofm)}")

if __name__ == "__main__":
    main()
