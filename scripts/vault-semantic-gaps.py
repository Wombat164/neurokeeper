#!/usr/bin/env python3
# @capability:  semantic-gaps
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/vault-semantic-gaps.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         docs/adr-0004-substrate-boundary.md
"""vault-semantic-gaps.py -- which EXISTING notes should link to the one you just wrote?

ref-audit answers a structural question: does every link resolve, is anything orphaned. It says
nothing about the gap that actually costs a collection its value -- a new note about a subject the
collection already covers, sitting unconnected to the notes covering it, because nobody remembered
they existed. Structurally that vault is perfect. Every link resolves. There are no orphans, because
the new note links somewhere. The knowledge is still split in two.

This engine reports candidates for a human or an agent to accept or reject. It NEVER writes a link.
Automatic link insertion would put a machine's guess about meaning into the record, and a wrong link
is worse than a missing one: a missing link is a gap someone may still find, a wrong one is an
assertion the collection now makes.

## Why this reuses correlate rather than counting shared terms

The obvious implementation is to grep each of the note's terms across the collection and rank by
overlap count. That ranks by how COMMON a word is, so the note sharing "project" and "meeting" with
everything outranks the one sharing a single identifier that appears twice in ten years. correlate
already solved this -- IDF weighting, a code channel, an anchor floor, an evidence trail -- and it
already builds and caches the index. A second scorer here would be a second set of answers to the
same question, and the day they disagree neither is trustworthy.

So the note itself becomes the item, and the existing engine scores it against everything else.

Exit: 0 reported (with or without gaps -- this is ADVISORY, a candidate list is not a defect)
      2 no target notes could be resolved (NOT CONFIGURED / nothing to do)
      3 the collection could not be read
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _vault_lib import VAULT, force_utf8_stdout  # noqa: E402


def _correlate_module():
    """The correlate engine, imported as a module.

    Its filename carries a hyphen, so it cannot be imported by name. Loading it by path is still
    strictly better than copying its scoring here: there is exactly one implementation of what
    counts as evidence, and it stays that way.
    """
    path = os.path.join(HERE, "vault-correlate.py")
    if not os.path.isfile(path):
        sys.exit(f"vault-semantic-gaps: the correlate engine is missing: {path}")
    spec = importlib.util.spec_from_file_location("_vault_correlate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def changed_since(ref, vault):
    """Note paths changed since a git ref, so an agent can ask about the work it just did."""
    r = subprocess.run(["git", "-C", vault, "diff", "--name-only", "--diff-filter=d", ref],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"vault-semantic-gaps: git diff against '{ref}' failed: {r.stderr.strip()}")
    return [os.path.join(vault, p) for p in r.stdout.split("\n")
            if p.strip().endswith(".md")]


def linked_ids(card, idx):
    """Note ids the target already links to, resolved from raw link text.

    A link is written as a stem, a title or an alias, so all three are matched. Over-matching here
    is the safe direction: the cost is a candidate suppressed as already-linked, which is a missed
    suggestion. Under-matching reports a link that plainly exists as a gap, and an engine that
    reports what you already did teaches you to ignore it.
    """
    wanted = {link.lower().split("#")[0].split("|")[0].strip() for link in card["links_out"]}
    wanted.discard("")
    out = set()
    for nid, other in idx.cards.items():
        names = {other["stem"].lower(), other["title"].lower()}
        names |= {a.lower() for a in other["aliases"]}
        if names & wanted:
            out.add(nid)
    return out


def inbound_ids(nid, card, idx):
    """Note ids that already link TO the target. The gap is symmetric; the report should be too."""
    names = {card["stem"].lower(), card["title"].lower()} | {a.lower() for a in card["aliases"]}
    out = set()
    for other_id, other in idx.cards.items():
        if other_id == nid:
            continue
        for link in other["links_out"]:
            if link.lower().split("#")[0].split("|")[0].strip() in names:
                out.add(other_id)
                break
    return out


def main(argv=None):
    force_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Report existing notes that discuss the same subject as a target note "
                    "but are not linked to it. Read-only; never writes a link.")
    ap.add_argument("--vault", default=VAULT)
    ap.add_argument("--note", action="append", default=[],
                    help="Target note path (repeatable).")
    ap.add_argument("--since", help="Use every .md changed since this git ref as a target.")
    ap.add_argument("--top", type=int, default=5, help="Candidates reported per note (default 5).")
    ap.add_argument("--min-score", type=int, default=None,
                    help="Only report candidates at or above this score. Default: correlate's own "
                         "CORRELATED threshold, so a gap has to rest on real evidence.")
    ap.add_argument("--config")
    ap.add_argument("--register")
    ap.add_argument("--schema")
    ap.add_argument("--no-schema", action="store_true")
    ap.add_argument("--include", action="append", default=[])
    ap.add_argument("--cache", default=".vault-correlate-cache.json")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.vault):
        # Configured and unreadable is a defect, not a skip (ADR-0002).
        print(f"vault-semantic-gaps: collection not readable: {args.vault}", file=sys.stderr)
        sys.exit(3)

    c = _correlate_module()

    targets = list(args.note)
    if args.since:
        targets += changed_since(args.since, args.vault)
    targets = [t for t in dict.fromkeys(targets) if os.path.isfile(t)]
    if not targets:
        print("vault-semantic-gaps: no target notes. Pass --note <path> or --since <git-ref>.",
              file=sys.stderr)
        sys.exit(2)

    # Same resolution order as correlate, because a different index here would answer a different
    # question than the tool the operator already trusts.
    include, cfg_map = c.load_config(args.config)
    fm_map = dict(c.DEFAULT_FM_MAP)
    topical = []
    if not args.no_schema:
        schema_path = args.schema or os.environ.get("FRONTMATTER_SCHEMA") or \
            os.path.join(args.vault, ".claude", "data", "frontmatter-schema.yaml")
        roles, topical = c.load_schema(schema_path)
        fm_map.update(roles)
    fm_map.update({k: v for k, v in cfg_map.items() if v != c.DEFAULT_FM_MAP.get(k)})
    fm_map["_topical"] = topical
    if args.include:
        include = args.include

    patterns = c.load_register(args.register)
    idx, _stats = c.load_index(args.vault, include, fm_map, args.cache,
                               refresh=args.refresh, patterns=patterns)
    if not len(idx):
        print(f"vault-semantic-gaps: index is empty for {args.vault}", file=sys.stderr)
        sys.exit(3)

    floor = args.min_score if args.min_score is not None else c.CORRELATED
    results = []
    for path in targets:
        rel = os.path.relpath(path, args.vault).replace(os.sep, "/")
        reldir = os.path.dirname(rel)
        card = c.build_card(path, reldir, fm_map, args.vault, patterns=patterns)
        if card is None:
            continue

        # The note IS the item. Its own body carries the subject; passing it means the phrase and
        # token channels see what the note actually says, not a summary of it.
        text = open(path, encoding="utf-8", errors="replace").read()
        _fm, body = c.split_frontmatter(text)
        item = {"id": rel, "title": card["title"], "body": body or "",
                "codes": card["codes"], "participants": card["people"]}

        # Asked for more candidates than we report: the exclusions below remove the note itself and
        # everything already linked, and those come off the TOP of the list. Requesting exactly
        # --top would return a short list whenever the note is well connected, which is precisely
        # the note where the one remaining gap matters most.
        verdict = c.correlate(item, idx, top=max(args.top * 4, 20))

        # Exclusions, in order of how badly a miss would read: the note itself (it always wins
        # against itself), then anything already connected in EITHER direction.
        already = {card["note"]} | linked_ids(card, idx) | inbound_ids(card["note"], card, idx)
        gaps = [cand for cand in verdict["candidates"]
                if cand["note"] not in already and cand["score"] >= floor][:args.top]

        results.append({
            "note": rel,
            "linked_already": len(already) - 1,
            # The evidence travels with the candidate. A suggestion a reader cannot check is one
            # they have to take on faith, and this engine is asking them to judge, not to comply.
            "gaps": [{"note": g["note"], "score": g["score"], "evidence": g["evidence"]}
                     for g in gaps],
        })

    total = sum(len(r["gaps"]) for r in results)
    if args.json:
        print(json.dumps({"engine": "semantic-gaps", "vault": os.path.abspath(args.vault),
                          "counts": {"notes": len(results), "gaps": total},
                          "results": results}, indent=2))
    else:
        for r in results:
            print(f"\n{r['note']}  ({r['linked_already']} already linked)")
            if not r["gaps"]:
                print("  no unlinked notes above the evidence floor")
            for g in r["gaps"]:
                print(f"  [{g['score']:>4}] {g['note']}")
                if g["evidence"]:
                    print(f"         {', '.join(g['evidence'])}")
        print(f"\nsemantic-gaps: {total} candidate link(s) across {len(results)} note(s). "
              f"Candidates, not defects -- accept or reject them yourself.")
    # Always 0. A candidate list is advisory by construction, and a suggestion engine that can fail
    # a gate would get the gate switched off.
    return 0


if __name__ == "__main__":
    sys.exit(main())
