"""Tests for vault-doctor.py -- aggregate health with an HONEST tri-state roll-up (ADR-0002).

Locks the anti-false-assurance contract: unconfigured engines are SKIPPED (never silently passed); skips
never fail --check; a real gate failure (broken canvas via ref-audit) DOES fail the roll-up; an engine
becomes applicable when its config is present.
"""
import json
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "vault-doctor.py")
EXAMPLE_SCHEMA = os.path.join(HARNESS, "config.example", "frontmatter-schema.example.yaml")


def _vault(root, files):
    root.mkdir(parents=True, exist_ok=True)
    for rel, txt in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return root


def _env(vault, **extra):
    e = dict(os.environ, VAULT_ROOT=str(vault))
    e.pop("FRONTMATTER_SCHEMA", None)          # deterministic regardless of the caller's real env
    e.pop("CLAUDE_MEMORY_DIR", None)
    e.update(extra)
    return e


def _run(vault, *args, **extra):
    return subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True,
                          env=_env(vault, **extra))


def _states(vault, *args, **extra):
    r = _run(vault, "--json", *args, **extra)
    assert r.returncode in (0, 1), r.stderr
    d = json.loads(r.stdout)
    return {e["engine"]: e["state"] for e in d["engines"]}, d, r.returncode


def test_clean_vault_skips_unconfigured(tmp_path):
    v = _vault(tmp_path / "v", {"a.md": "[[b]]\n", "b.md": "text\n"})
    states, d, _ = _states(v)
    assert states["ref-audit"] == "ok"
    assert states["taxonomy-inventory"] == "ok"
    assert states["frontmatter-lint"] == "skipped"      # no FRONTMATTER_SCHEMA
    assert states["memory-consolidate"] == "skipped"    # no CLAUDE_MEMORY_DIR
    assert d["failed"] == []
    assert _run(v, "--check").returncode == 0           # skips never fail the roll-up


def test_broken_canvas_fails_rollup(tmp_path):
    v = _vault(tmp_path / "v", {
        "a.md": "x\n",
        "c.canvas": json.dumps({"nodes": [{"type": "file", "file": "gone.md"}]})})
    states, d, rc = _states(v, "--check")
    assert states["ref-audit"] == "fail" and "ref-audit" in d["failed"]
    assert rc == 1
    assert _run(v, "--check").returncode == 1


def test_frontmatter_lint_applicable_with_schema(tmp_path):
    v = _vault(tmp_path / "v", {"a.md": "---\n---\ntext\n"})
    states, _, _ = _states(v, FRONTMATTER_SCHEMA=EXAMPLE_SCHEMA)
    assert states["frontmatter-lint"] != "skipped"      # config present -> runs (advisory, cannot fail)


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


def test_run_receipt_records_what_ran(tmp_path):
    v = _vault(tmp_path / "v", {"a.md": "[[b]]\n", "b.md": "x\n"})
    r = json.loads(_run(v, "--json").stdout)["receipt"]
    assert r["tool"] == "neurokeeper"
    assert r["files_scanned"] == 2                       # the actual scanned count
    assert _norm(r["root"]) == _norm(str(v))             # the actual root, absolute
    assert "taxonomy-inventory" in r["engines_run"] and "ref-audit" in r["engines_run"]
    assert isinstance(r["duration_ms"], int)


def test_run_receipt_zero_files_is_loud(tmp_path):
    # a wrong/empty root scans nothing; the receipt surfaces it instead of a silently-green run
    empty = _vault(tmp_path / "empty", {})
    assert json.loads(_run(empty, "--json").stdout)["receipt"]["files_scanned"] == 0
    assert "0 files: check VAULT_ROOT" in _run(empty).stdout
