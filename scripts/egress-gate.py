#!/usr/bin/env python3
"""egress-gate: block sensitive content at the moment it would leave the machine.

## Why this exists next to the gitleaks pre-push guard

`bootstrap/hooks/pre-push` already refuses a push to a PUBLIC github remote when gitleaks
finds a match or when a commit carries a non-neutral author identity. That guard is kept.
This engine covers three things it structurally cannot:

  1. DIACRITICS. gitleaks matches raw bytes, so an ASCII pattern misses the accented form of
     the same word: a term written `evenement` never matches `événement`. NL and FR
     vocabulary is exactly where this bites. This engine folds both sides.
  2. NON-GIT SURFACES. Text about to be pasted into an issue, a staged-but-uncommitted
     change, a working tree. gitleaks is git-shaped; leaks are not.
  3. PUBLIC-REPO SELF-PROTECTION. A hashed term list lets a public repo carry its own gate
     without the gate disclosing what it guards.

The two compose: gitleaks owns secrets and the identity guard, this owns the trilingual
vocabulary. Neither is a substitute for the other, and the pre-push hook runs both.

## Design rules, all load-bearing

  ONE ENGINE, MANY CALL SITES. pre-commit, pre-push, CI, a harness hook and ad-hoc all run
  this. A second implementation is a second set of bugs and a second thing to forget.

  FAIL CLOSED. If no term source loads, or a git call fails, this BLOCKS and says why. A
  gate that could not scan must never conclude "clean".

  TERSE OUTPUT. Findings are capped per unit and summarised. A gate that dumps whole files
  burns context on every run and gets muted, and a muted gate catches nothing.

  CONFIG IS DATA, MATCHING IS CODE. Sources, caps, severities and modes come from YAML.
  The fold table and the match loop do not: a misconfigured fold silently weakens the gate
  while still reporting clean.

## Modes

  --staged              staged blobs + prepared commit message        (pre-commit)
  --push-stdin          git's pre-push refs on stdin: the whole outgoing range, commit
                        messages AND patches AND author identities    (pre-push)
  --range A..B          an explicit range, same treatment
  --tree                every tracked text file                       (CI)
  --file/--text/--stdin ad-hoc

Exit: 0 clean, 1 findings at block severity, 2 environment error (which also means BLOCKED).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

TOKEN_RE = re.compile(r"[a-z0-9]+")
ZERO_OID = "0" * 40

DEFAULTS = {
    "sources": [
        {"path": "${EGRESS_DENYLIST}", "kind": "text", "required": False},
        {"path": "tools/lexicon.deny.txt", "relative_to": "repo",
         "kind": "text", "required": False},
        {"path": "tools/lexicon.deny.hashes", "relative_to": "repo",
         "kind": "hashes", "required": False},
    ],
    "require_at_least_one_source": True,
    "limits": {"max_findings_per_unit": 5, "max_blob_bytes": 2_000_000},
    "severity": {"default": "block", "by_source": {}},
    "modes": {
        "staged": {"enabled": True, "scan_commit_message": True},
        "push": {"enabled": True, "scan_commit_messages": True,
                 "scan_patches": True, "scan_identities": True},
        "tree": {"enabled": True},
    },
    "baseline": {"path": ".egress-gate-baseline"},
}

# Diacritic folding for NL/FR/EN. A static translate table over the Latin-1 range that
# actually occurs in these three languages, deliberately NOT a unicodedata.normalize
# round-trip: no Unicode database, no per-call allocation, and it covers every accent
# NL/FR/EN produce. Both the term and the scanned text are folded, which is why term
# files can stay ASCII and still match accented prose.
_FOLD = str.maketrans({
    **{c: "a" for c in "àáâãäå"}, **{c: "A" for c in "ÀÁÂÃÄÅ"},
    "ç": "c", "Ç": "C",
    **{c: "e" for c in "èéêë"}, **{c: "E" for c in "ÈÉÊË"},
    **{c: "i" for c in "ìíîï"}, **{c: "I" for c in "ÌÍÎÏ"},
    "ñ": "n", "Ñ": "N",
    **{c: "o" for c in "òóôõö"}, **{c: "O" for c in "ÒÓÔÕÖ"},
    **{c: "u" for c in "ùúûü"}, **{c: "U" for c in "ÙÚÛÜ"},
    "ý": "y", "ÿ": "y", "Ý": "Y",
    "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ß": "ss",
    "’": "'", "‘": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ",
})


def fold(s: str) -> str:
    return s.translate(_FOLD)


def die(msg: str) -> None:
    raise SystemExit(f"egress-gate: BLOCKED - {msg}")


# ----------------------------------------------------------------------------- config


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(base[k], v) if isinstance(v, dict) and isinstance(
            base.get(k), dict) else v
    return out


def load_config(repo: Path | None) -> dict:
    for cand in (os.environ.get("EGRESS_GATE_CONFIG"),
                 str(repo / ".egress-gate.yaml") if repo else None):
        if not cand:
            continue
        p = Path(cand)
        if not p.is_file():
            if cand == os.environ.get("EGRESS_GATE_CONFIG"):
                die(f"EGRESS_GATE_CONFIG set but not found: {p}")
            continue
        if yaml is None:
            die("pyyaml is required to read a config file but is not installed")
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            die(f"cannot parse {p}: {exc}")
        if not isinstance(data, dict):
            die(f"{p} must contain a mapping")
        return deep_merge(DEFAULTS, data)
    return dict(DEFAULTS)


# --------------------------------------------------------------------------- denylist


class Denylist:
    def __init__(self) -> None:
        self.patterns: list[tuple[re.Pattern[str], str, str]] = []   # pat, label, severity
        self.hashes: dict[str, str] = {}                             # digest -> severity
        self.sources: list[str] = []

    def load_text(self, path: Path, severity: str) -> None:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("regex:"):
                expr = line[len("regex:"):]
                try:
                    self.patterns.append((re.compile(expr, re.IGNORECASE), expr, severity))
                except re.error as exc:
                    die(f"bad regex in {path}: {expr}: {exc}")
            else:
                folded = fold(line)
                lb = r"\b" if folded[:1].isalnum() else ""
                rb = r"\b" if folded[-1:].isalnum() else ""
                self.patterns.append(
                    (re.compile(lb + re.escape(folded) + rb, re.IGNORECASE), line, severity))
        self.sources.append(str(path))

    def load_hashes(self, path: Path, severity: str) -> None:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip().lower()
            if line and not line.startswith("#") and len(line) == 64 \
                    and all(c in "0123456789abcdef" for c in line):
                self.hashes[line] = severity
        self.sources.append(str(path))

    def empty(self) -> bool:
        return not self.patterns and not self.hashes

    def scan_line(self, line: str) -> list[tuple[str, str]]:
        folded = fold(line)
        hits: list[tuple[str, str]] = []
        for pat, label, sev in self.patterns:
            m = pat.search(folded)
            if m:
                hits.append((f"[{label}] -> {m.group(0)!r}", sev))
        if self.hashes:
            for tok in set(TOKEN_RE.findall(folded.lower())):
                sev = self.hashes.get(hashlib.sha256(tok.encode()).hexdigest())
                if sev:
                    # Never echo the token: it is guarded precisely because naming it leaks.
                    hits.append(("[hashed-term] -> <redacted>", sev))
        return hits


def build_denylist(cfg: dict, repo: Path | None) -> Denylist:
    dl = Denylist()
    default_sev = cfg["severity"].get("default", "block")
    by_source = cfg["severity"].get("by_source") or {}
    seen: set[Path] = set()

    for src in cfg.get("sources") or []:
        raw = os.path.expandvars(str(src.get("path", "")))
        if not raw or "${" in raw:          # unexpanded env var -> source simply absent
            if src.get("required"):
                die(f"required source is unset: {src.get('path')}")
            continue
        p = Path(raw)
        if src.get("relative_to") == "repo":
            if not repo:
                continue
            p = repo / p
        if not p.is_file():
            if src.get("required"):
                die(f"required source not found: {p}")
            continue
        real = p.resolve()
        if real in seen:
            # Two slots routinely point at one file (an env var set to the same list the
            # repo-relative slot finds). Loading twice doubles every pattern, so each hit
            # is reported twice and the count is wrong. A gate with wrong counts stops
            # being believed.
            continue
        seen.add(real)
        sev = by_source.get(str(src.get("path")), default_sev)
        dl.load_hashes(p, sev) if src.get("kind") == "hashes" else dl.load_text(p, sev)

    if dl.empty() and cfg.get("require_at_least_one_source", True):
        die("no term source could be loaded.\n"
            "  Set EGRESS_DENYLIST, add tools/lexicon.deny.txt, or point EGRESS_GATE_CONFIG\n"
            "  at a config naming a real source. A gate that cannot scan must not report clean.")
    return dl


# -------------------------------------------------------------------------------- git


def git(*args: str, cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, errors="replace", check=False)
    except OSError as exc:
        die(f"cannot run git: {exc}")
    if r.returncode != 0:
        die(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout


def repo_root() -> Path | None:
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, check=False)
    except OSError:
        return None
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def _textual(raw: bytes, cap: int) -> str | None:
    if b"\0" in raw[:8000] or len(raw) > cap:
        return None
    return raw.decode("utf-8", errors="replace")


def units_staged(root: Path, cfg: dict) -> list[tuple[str, str]]:
    cap = cfg["limits"]["max_blob_bytes"]
    out: list[tuple[str, str]] = []
    for name in [n for n in git("diff", "--cached", "--name-only",
                                "--diff-filter=ACMR", "-z", cwd=root).split("\0") if n]:
        raw = subprocess.run(["git", "show", f":{name}"], cwd=root,
                             capture_output=True, check=False).stdout
        text = _textual(raw, cap)
        if text is not None:
            out.append((name, text))
    if cfg["modes"]["staged"].get("scan_commit_message", True):
        msg = root / ".git" / "COMMIT_EDITMSG"
        if msg.is_file():
            out.append(("<commit message>",
                        msg.read_text(encoding="utf-8", errors="replace")))
    return out


def units_range(root: Path, rev_args: list[str], cfg: dict) -> list[tuple[str, str]]:
    mode = cfg["modes"]["push"]
    cap = cfg["limits"]["max_blob_bytes"]
    out: list[tuple[str, str]] = []
    for rev in [r for r in git("rev-list", *rev_args, cwd=root).split() if r]:
        if mode.get("scan_commit_messages", True):
            out.append((f"{rev[:10]} <message>", git("log", "-1", "--format=%B", rev, cwd=root)))
        if mode.get("scan_identities", True):
            out.append((f"{rev[:10]} <identity>",
                        git("log", "-1", "--format=%an%n%ae%n%cn%n%ce", rev, cwd=root)))
        if mode.get("scan_patches", True):
            patch = git("show", "--format=", "--no-color", "--unified=0", rev, cwd=root)
            label = f"{rev[:10]} <patch>" if len(patch) <= cap else f"{rev[:10]} <patch:truncated>"
            out.append((label, patch[:cap]))
    return out


def push_rev_args(stdin_text: str) -> list[str] | None:
    ranges: list[str] = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _lref, loid, _rref, roid = parts
        if loid == ZERO_OID:
            continue                                   # branch deletion, nothing leaves
        ranges.append(loid if roid == ZERO_OID else f"{roid}..{loid}")
    if not ranges:
        return None
    if any(".." not in r for r in ranges):
        # New branch: exclude what is already on a remote so we scan what is genuinely
        # new rather than the entire history of the repository.
        return [*ranges, "--not", "--remotes"]
    return ranges


def units_tree(root: Path, cfg: dict) -> list[tuple[str, str]]:
    cap = cfg["limits"]["max_blob_bytes"]
    out: list[tuple[str, str]] = []
    for name in [n for n in git("ls-files", "-z", cwd=root).split("\0") if n]:
        try:
            raw = (root / name).read_bytes()
        except OSError:
            continue
        text = _textual(raw, cap)
        if text is not None:
            out.append((name, text))
    return out


# ------------------------------------------------------------------------------ scan


def fingerprint(label: str, hit: str) -> str:
    # Strip a leading commit sha so a finding keeps its identity across a rebase.
    base = label.split(" ", 1)[-1] if re.match(r"^[0-9a-f]{7,40} ", label) else label
    return hashlib.sha256(f"{base}|{hit}".encode()).hexdigest()[:16]


def run(units, dl: Denylist, baseline: set[str], cap: int):
    findings, suppressed = [], 0
    for label, text in units:
        n = 0
        for lineno, line in enumerate(text.splitlines(), start=1):
            for hit, sev in dl.scan_line(line):
                fp = fingerprint(label, hit)
                if fp in baseline:
                    suppressed += 1
                    continue
                n += 1
                if n <= cap:
                    findings.append({"unit": label, "line": lineno, "hit": hit,
                                     "severity": sev, "fingerprint": fp})
                elif n == cap + 1:
                    findings.append({"unit": label, "line": lineno,
                                     "hit": "... further hits in this unit suppressed",
                                     "severity": sev, "fingerprint": ""})
    return findings, suppressed


STOPWORDS = {
    # Function words that appear inside multiword terms. Hashing these would match nearly
    # every line of NL/FR/EN prose ever written.
    "de", "het", "een", "van", "der", "den", "en", "op", "in", "te", "tot",
    "le", "la", "les", "du", "des", "un", "une", "et", "aux", "sur", "par", "pour",
    "the", "a", "an", "of", "and", "to", "on", "in", "for", "at", "by",
}

# Ordinary technical English that must never enter a hashed list.
#
# Found by running this gate against neurokeeper's own tree: `Framework/` is a legitimate
# path entry in a private plaintext list, where the trailing slash and the surrounding
# context carry the meaning. Hashing reduces it to the bare token `framework`, which fired
# nine times in the project's own wiki. The hashed form cannot express "this word, as a
# path" -- it only expresses "this word, anywhere" -- so a term whose specificity lives in
# its context must not be hashed at all.
#
# Several of these are also the generic vocabulary a public engine is SUPPOSED to use, so
# denying them would break the thing the gate is protecting.
COMMON = {
    "framework", "backbone", "source", "sources", "template", "templates", "archive",
    "inbox", "project", "projects", "knowledge", "meeting", "meetings", "budget",
    "contract", "contracts", "supplier", "tender", "award", "renewal", "request",
    "commitment", "settlement", "ceiling", "allocation", "portfolio", "service",
    "services", "catalog", "catalogue", "policy", "gate", "vault", "engine", "network",
    "cloud", "security", "defence", "defense", "annex", "annexes", "evaluation",
}
MIN_HASH_TOKEN = 4


def emit_hashes(src: Path) -> int:
    """Turn a plaintext term list into a hashed one.

    ONLY single-word terms are emitted, and only tokens of >= MIN_HASH_TOKEN characters that
    are not function words. The hashed form matches per word-token, so a multiword entry like
    "credit de liquidation" would decompose into "credit", "de", "liquidation" and the "de"
    hash alone would fire on essentially every Dutch and French sentence in existence. A
    hashed list is therefore strictly weaker than the plaintext one it is derived from: it
    protects the distinctive single words and silently drops the phrases. That is the price
    of a list that can live in public, and it is why the private plaintext list stays the
    primary source wherever one is available.
    """
    if not src.is_file():
        print(f"egress-gate: --emit-hashes source not found: {src}", file=sys.stderr)
        return 2
    emitted, dropped = set(), 0
    for raw in src.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("regex:"):
            continue
        if line.endswith("/"):
            # A path marker. Its specificity is the path shape, which a token hash discards.
            dropped += 1
            continue
        toks = TOKEN_RE.findall(fold(line).lower())
        if len(toks) != 1:
            dropped += 1
            continue
        tok = toks[0]
        if len(tok) < MIN_HASH_TOKEN or tok in STOPWORDS or tok in COMMON:
            dropped += 1
            continue
        emitted.add(hashlib.sha256(tok.encode()).hexdigest())
    print("# egress-gate hashed term list. Generated with --emit-hashes; do not hand-edit.")
    print("# One sha256 of a lowercase, diacritic-folded word-token per line. Multiword and")
    print(f"# short terms cannot be represented and were dropped ({dropped} of them).")
    for h in sorted(emitted):
        print(h)
    print(f"egress-gate: emitted {len(emitted)} hash(es), dropped {dropped}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--push-stdin", action="store_true")
    ap.add_argument("--range")
    ap.add_argument("--tree", action="store_true")
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--text", action="append", default=[])
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--baseline")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--print-fingerprints", action="store_true")
    ap.add_argument("--emit-hashes", metavar="TEXTLIST",
                    help="read a plaintext term list and emit a hashed list on stdout, so a "
                         "PUBLIC repo can carry a gate without carrying the terms")
    args = ap.parse_args(argv)

    if args.emit_hashes:
        return emit_hashes(Path(args.emit_hashes))

    root = repo_root()
    try:
        cfg = load_config(root)
        dl = build_denylist(cfg, root)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    bl_path = args.baseline or (cfg.get("baseline") or {}).get("path")
    baseline: set[str] = set()
    if bl_path:
        p = Path(bl_path) if Path(bl_path).is_absolute() or not root else root / bl_path
        if p.is_file():
            baseline = {l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                        if l.strip() and not l.startswith("#")}

    units: list[tuple[str, str]] = []
    try:
        if args.staged or args.push_stdin or args.range or args.tree:
            if not root:
                print("egress-gate: BLOCKED - not inside a git repository", file=sys.stderr)
                return 2
            if args.staged:
                units += units_staged(root, cfg)
            if args.push_stdin:
                rev_args = push_rev_args(sys.stdin.read())
                if rev_args is None:
                    print("egress-gate OK: nothing to push")
                    return 0
                units += units_range(root, rev_args, cfg)
            if args.range:
                units += units_range(root, [args.range], cfg)
            if args.tree:
                units += units_tree(root, cfg)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    for f in args.file:
        p = Path(f)
        if not p.is_file():
            print(f"egress-gate: BLOCKED - --file not found: {f}", file=sys.stderr)
            return 2
        units.append((f, p.read_text(encoding="utf-8", errors="replace")))
    for i, t in enumerate(args.text):
        units.append((f"--text[{i}]", t))
    if args.stdin and not args.push_stdin:
        units.append(("<stdin>", sys.stdin.read()))

    if not units:
        print("egress-gate: BLOCKED - nothing to scan (pass a mode)", file=sys.stderr)
        return 2

    findings, suppressed = run(units, dl, baseline, cfg["limits"]["max_findings_per_unit"])
    blocking = [f for f in findings if f["severity"] == "block"]

    if args.json:
        print(json.dumps({"findings": findings, "blocking": len(blocking),
                          "suppressed": suppressed, "units": len(units),
                          "sources": dl.sources}, indent=2))
        return 1 if blocking else 0

    if args.print_fingerprints:
        for f in findings:
            if f["fingerprint"]:
                print(f["fingerprint"])
        return 0

    if not findings:
        extra = f" ({suppressed} baselined)" if suppressed else ""
        print(f"egress-gate OK: {len(units)} unit(s) scanned, no hits{extra}")
        return 0

    print(f"EGRESS-GATE: {len(findings)} finding(s) across {len(units)} unit(s) "
          f"[{len(blocking)} blocking]:")
    for f in findings:
        mark = "BLOCK" if f["severity"] == "block" else " warn"
        print(f"  {mark}  {f['unit']}:{f['line']}: {f['hit']}")

    if blocking:
        print("\nBLOCKED before egress. Scrub the flagged content. If a finding is a genuine\n"
              "false positive, add its fingerprint to the baseline (never weaken a term).\n"
              "Fingerprints: rerun with --print-fingerprints.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
