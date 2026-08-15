#!/usr/bin/env python3
# @capability:  title-backfill
# @compute:     deterministic
# @effect:      mutating (--apply only)
# @engine:      scripts/vault-title-backfill.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   attended-exempt (optional VAULT_FORBIDDEN_ZONES)
# @audit:       git
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""Backfill a human-facing `title:` onto slug-named notes, via an operator-reviewed proposal.

A vault that renames files to kebab-slugs loses its display name unless `title:` carries it. The name
almost always still exists as the note's H1, so this engine derives the proposal from that -- but it
does NOT write titles unreviewed, because deriving a title is a LANGUAGE judgement, not a mechanical
copy. Two phases:

  --propose  ->  writes a TSV: status <TAB> relpath <TAB> derived-H1 <TAB> proposed-title
                 The operator edits column 4 (and flips column 1 to SKIP to exclude a row), then:
  --apply F  ->  inserts `title:` into each OK row's frontmatter. Idempotent; rows whose note already
                 has a title are reported and skipped.

Separator rewriting: many H1s use a ` -- ` separator that a vault convention may ban in titles. The
proposal rewrites the FIRST occurrence to ": " and any later ones to ", ", which reads correctly for
`Topic -- Subtitle` but is a guess for anything else -- which is exactly why a human reads column 4
before anything is written. Configure with VAULT_TITLE_SEPARATOR (default " -- "); set it empty to
disable rewriting entirely.

Scope: notes whose FILENAME is a slug (no space, no separator). Notes already named readably do not
need a title. Excluded dirs come from VAULT_TITLE_EXCLUDE.

Usage:
  python scripts/vault-title-backfill.py --propose [-o proposal.tsv] [--json]
  python scripts/vault-title-backfill.py --apply proposal.tsv [--force] [--json]

Env:
  VAULT_TITLE_EXCLUDE    comma-separated reldir prefixes to skip (e.g. daily notes, raw sources)
  VAULT_TITLE_SEPARATOR  separator to rewrite out of derived titles (default " -- "; empty disables)
"""
import os, re, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _vault_guard import assert_obsidian_closed
except Exception:
    def assert_obsidian_closed(force=False): pass

from _vault_lib import (VAULT, md_files, safe_write, VaultWriteError,
                        in_forbidden_zone, force_utf8_stdout)

EXCLUDE = tuple(z.strip().replace(os.sep, "/").strip("/")
                for z in (os.environ.get("VAULT_TITLE_EXCLUDE") or "").split(",") if z.strip())
SEPARATOR = os.environ.get("VAULT_TITLE_SEPARATOR", " -- ")
# Files that live in the vault but are not notes -- never given a title.
NON_NOTES = {"CLAUDE.md", "README.md", "MEMORY.md"}


def is_slug_name(stem):
    """True iff the filename is a slug, i.e. it does NOT already read as a title."""
    if " " in stem:
        return False
    return not (SEPARATOR and SEPARATOR.strip() in stem)


def split_fm(text):
    """(frontmatter, body) or (None, None) when there is no parseable frontmatter block."""
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    return text[3:end], text[end + 4:]


def derive(h1):
    """Proposed title from an H1: strip the banned separator down to ordinary punctuation."""
    t = h1.strip()
    if not SEPARATOR:
        return t
    first, sep, rest = t.partition(SEPARATOR)
    if not sep:
        return t
    return first.rstrip() + ": " + rest.replace(SEPARATOR, ", ").lstrip()


def candidates():
    """Yield (relpath, h1_or_None, has_frontmatter) for every in-scope note missing a title."""
    for path, rel in md_files():
        base = os.path.basename(path)
        if base in NON_NOTES or not is_slug_name(base[:-3]):
            continue
        relnorm = (rel or "").replace(os.sep, "/").strip("/")
        if any(relnorm == z or relnorm.startswith(z + "/") for z in EXCLUDE):
            continue
        frel = (relnorm + "/" + base) if relnorm else base
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        fm, body = split_fm(text)
        if fm is not None and re.search(r"^title\s*:", fm, re.M):
            continue
        h1 = re.search(r"^#\s+(.+)$", body if fm is not None else text, re.M)
        yield frel, (h1.group(1).strip() if h1 else None), fm is not None


def cmd_propose(args):
    out_path = None
    if "-o" in args:
        out_path = args[args.index("-o") + 1]
    rows, stats = [], {"h1": 0, "no_h1": 0, "no_frontmatter": 0, "needs_separator_fix": 0}
    for frel, h1, has_fm in candidates():
        if not has_fm:
            stats["no_frontmatter"] += 1
            # No frontmatter block at all -> --apply cannot safely synthesise one. Reported, not proposed.
            rows.append(("NOFM", frel, h1 or "", ""))
            continue
        if not h1:
            stats["no_h1"] += 1
            rows.append(("NOH1", frel, "", ""))
            continue
        stats["h1"] += 1
        proposed = derive(h1)
        if proposed != h1:
            stats["needs_separator_fix"] += 1
        rows.append(("OK", frel, h1, proposed))

    lines = [
        "# title-backfill proposal. Edit column 4, then: vault-title-backfill.py --apply <this file>",
        "# col1 OK = apply | SKIP = leave alone | NOH1/NOFM = not applicable (needs a human, never applied)",
        "# columns are TAB separated: status <TAB> path <TAB> h1 <TAB> proposed-title",
    ]
    lines += ["\t".join(r) for r in rows]
    text = "\n".join(lines) + "\n"
    if out_path:
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    if "--json" in args:
        print(json.dumps(stats, indent=2), file=sys.stderr)
        return
    tgt = out_path or "(stdout)"
    print(f"=== TITLE BACKFILL PROPOSAL -> {tgt} ===", file=sys.stderr)
    for k, v in stats.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print(f"  proposed rows: {stats['h1']} (review column 4 before --apply)", file=sys.stderr)


def cmd_apply(args):
    path_arg = args[args.index("--apply") + 1]
    assert_obsidian_closed("--force" in args)
    stats = {"applied": 0, "skipped": 0, "already_titled": 0, "missing": 0, "not_applicable": 0}
    for raw in open(path_arg, encoding="utf-8"):
        line = raw.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        status, frel, _h1, proposed = parts[0].strip(), parts[1], parts[2], parts[3].strip()
        if status != "OK" or not proposed:
            stats["not_applicable" if status in ("NOH1", "NOFM") else "skipped"] += 1
            continue
        full = os.path.join(VAULT, frel.replace("/", os.sep))
        if not os.path.isfile(full):
            stats["missing"] += 1
            continue
        reldir = os.path.dirname(frel)
        if in_forbidden_zone(reldir):
            stats["skipped"] += 1
            continue
        text = open(full, encoding="utf-8").read()
        fm, body = split_fm(text)
        if fm is None:
            stats["not_applicable"] += 1
            continue
        if re.search(r"^title\s*:", fm, re.M):
            stats["already_titled"] += 1      # idempotent: a second run is a no-op
            continue
        # Quote when the value would otherwise break the YAML scalar (": " splits a plain scalar;
        # a leading [ / { / quote / # is a flow-collection or comment marker).
        needs_quote = (": " in proposed or proposed[:1] in "[{\"'#>|&*!%@`"
                       or proposed.rstrip().endswith(":"))
        value = '"%s"' % proposed.replace('"', '\\"') if needs_quote else proposed
        lines = fm.split("\n")
        # Insert after the opening blank produced by the leading '---', keeping title near the top
        # where a human looks for it, without disturbing any existing key order.
        at = 1 if lines and lines[0] == "" else 0
        lines.insert(at, f"title: {value}")
        try:
            safe_write(full, "---" + "\n".join(lines) + "\n---" + body)
            stats["applied"] += 1
        except VaultWriteError as e:
            print(f"  skip (guard): {e}", file=sys.stderr)
            stats["skipped"] += 1
    if "--json" in args:
        print(json.dumps(stats, indent=2))
        return
    print("=== TITLE BACKFILL (APPLIED) ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


def main():
    force_utf8_stdout()
    args = sys.argv[1:]
    if "--apply" in args:
        cmd_apply(args)
    elif "--propose" in args:
        cmd_propose(args)
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
