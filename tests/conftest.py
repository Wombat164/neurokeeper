"""Shared fixtures for the deterministic vault-engine test suite.

The engines live in ``scripts/``. Importable helpers (``_vault_lib`` / ``_vault_guard``)
are exercised in-process; the CLI engines are exercised via subprocess with an
env-driven config (VAULT_ROOT / FRONTMATTER_SCHEMA / VAULT_NORENAME_ZONES).

These tests LOCK the red-team hardening fixes as regressions; they never modify the
engines. ``mini_vault`` builds a throwaway ~27-file vault under ``tmp_path`` covering
every behaviour under test.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMA_PATH = REPO_ROOT / "config.example" / "frontmatter-schema.example.yaml"

# Make the importable helpers reachable for the in-process tests.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# The no-rename (forbidden / legal / write-once) zones the engines must never rename.
NORENAME_ZONES = ("06 - Procurement,Sources,08 - Archive,Framework,Backbone,"
                  "05 - Knowledge,07 - HR,09 - Templates")

# Folder -> note_type map for vault-set-note-type.py (the engine reads it from VAULT_NOTE_TYPE_MAP).
# Matches the generic fixture folders below so the note_type-derivation test is vault-agnostic.
NOTE_TYPE_MAP = {
    "01 - Daily": "daily",
    "02 - Projects": "project",
    "03 - Domains": "note",
    "04 - Meetings": "meeting",
    "11 - Outbox": "outbox",
    "MOC": "moc",
}


def _write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` (parents created), forcing LF so hashes are stable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# mini_vault file matrix
# ---------------------------------------------------------------------------
# Hub body uses a raw string so the escaped pipe ``\|`` is written literally.
_LINKS_HUB = r"""# Links Hub

- [[Foo Bar -- Baz]]
- [[Foo Bar -- Baz|alias]]
- [[Foo Bar -- Baz\|tbl]]
- [[Foo Bar -- Baz#h]]
- ![[Foo Bar -- Baz]]
- [[02 - Projects/Foo Bar -- Baz]]
- [[TCP/IP]]
- [[Clob Target]]
"""

_FA = "---\nstatus: active\n---\nbody\n"

_FILES = {
    # --- naming / link-aware rename cases ---
    "02 - Projects/Foo Bar -- Baz.md": _FA,                # non-kebab -> foo-bar-baz
    "02 - Projects/AB12 Dossier.md": _FA,                  # dossier code -> AB12-dossier (preserved)
    "03 - Domains/Alpha — Beta.md": _FA,                   # em-dash variant -> alpha-beta
    "02 - Projects/Clob Target.md": "---\nstatus: active\n---\nclob source\n",
    "02 - Projects/clob-target.md": "---\nstatus: active\n---\npre-existing different\n",
    "01 - Daily/2026-06-27.md": "---\nstatus: active\n---\nday\n",   # daily -> skipped
    ".hidden.md": "---\nstatus: active\n---\nhidden\n",                  # dotfile -> skipped
    "06 - Procurement/Legal File.md": "---\nstatus: active\n---\nlegal\n",   # no-rename zone
    "Sources/Raw.md": "---\nstatus: active\n---\nraw\n",                 # no-rename zone
    "00 - Inbox/links-hub.md": _LINKS_HUB,                  # link matrix + slash decoy + clob link

    # --- frontmatter cases ---
    "02 - Projects/status-open.md": "---\nstatus: open\nhorizon: past\n---\nb\n",
    "02 - Projects/status-in-review.md": "---\nstatus: in-review\n---\nb\n",
    "02 - Projects/status-approved.md": "---\nstatus: approved\n---\nb\n",
    "00 - Inbox/outbox-typed.md": "---\nnote_type: outbox\nstatus: pending\n---\nb\n",
    "11 - Outbox/mail/x.md": "---\nstatus: pending\n---\nb\n",          # outbox-by-path
    "02 - Projects/date-equal.md": "---\nstatus: active\ncreated: 2026-06-01\ndate: 2026-06-01\n---\nb\n",
    "02 - Projects/date-diff.md": "---\nstatus: active\ncreated: 2026-06-01\ndate: 2026-05-15\n---\nb\n",
    "02 - Projects/malformed.md": "---\nstatus: active\ntags: [unclosed\n---\nb\n",
    "02 - Projects/missing-axes.md": "---\ntitle: x\n---\nb\n",

    # --- tag cases ---
    "03 - Domains/tags-canon.md": "---\ntags: [source, red-team, SIAM]\n---\nb\n",
    "03 - Domains/tags-variant.md":
        "---\ntags: [sources, redteam, siam]\n---\nbody #project here\n\n```\n#ignored\n```\n",
    "03 - Domains/tags-pac.md": "---\ntags: [pac, pacs]\n---\nb\n",
    "03 - Domains/tags-cis.md": "---\ntags: [CIS, CI]\n---\nb\n",

    # --- note_type derivation cases ---
    "02 - Projects/already-typed.md": "---\nnote_type: project\ntitle: t\n---\nb\n",
    "04 - Meetings/meeting-note.md": "---\ntitle: m\n---\nb\n",
    "MOC/some-moc.md": "---\ntitle: o\n---\nb\n",
    "03 - Domains/kind-spec.md": "---\nkind: Strategy\nsphere: shared\n---\nb\n",
}


@pytest.fixture
def mini_vault(tmp_path):
    """Build a throwaway vault and return {'root': Path, 'env': dict, 'norename': str}."""
    root = tmp_path / "vault"
    for rel, content in _FILES.items():
        _write(root / rel, content)
    env = os.environ.copy()
    env["VAULT_ROOT"] = str(root)
    env["FRONTMATTER_SCHEMA"] = str(SCHEMA_PATH)
    env["VAULT_NORENAME_ZONES"] = NORENAME_ZONES
    env["VAULT_NOTE_TYPE_MAP"] = json.dumps(NOTE_TYPE_MAP)
    env.pop("VAULT_SCAN_EXCLUDE", None)         # let the engine use its default exclude set
    env.pop("VAULT_NOTE_TYPE_SUBRULES", None)   # let the engine use its default sub-overrides
    return {"root": root, "env": env, "norename": NORENAME_ZONES}


@pytest.fixture
def hash_tree():
    """Return a callable(root) -> {relpath: sha256} over every file (for dry-run/idempotency)."""
    def _hash(root):
        root = Path(root)
        out = {}
        for p in sorted(root.rglob("*")):
            if p.is_file():
                key = str(p.relative_to(root)).replace(os.sep, "/")
                out[key] = hashlib.sha256(p.read_bytes()).hexdigest()
        return out
    return _hash


@pytest.fixture
def run_engine():
    """Return a callable(script_name, *args, env=None) -> CompletedProcess for the CLI engines."""
    def _run(script_name, *args, env=None):
        cmd = [sys.executable, str(SCRIPTS_DIR / script_name), *args]
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)
    return _run
