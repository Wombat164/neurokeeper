"""Release-gate + shipped-fixture smoke tests.

- check-release.py must pass on the repo (versions synced, manifests valid).
- the shipped examples/vault/ must stay clean (doctor --check exits 0) -- it is the CI smoke fixture and
  the thing new users run first, so a regression here is a broken first impression.
"""
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_check_release_passes():
    r = subprocess.run([sys.executable, os.path.join(HARNESS, "scripts", "check-release.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_example_vault_passes_doctor():
    env = dict(os.environ, VAULT_ROOT=os.path.join(HARNESS, "examples", "vault"))
    env.pop("FRONTMATTER_SCHEMA", None)
    env.pop("CLAUDE_MEMORY_DIR", None)
    r = subprocess.run([sys.executable, os.path.join(HARNESS, "scripts", "vault-doctor.py"), "--check"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
