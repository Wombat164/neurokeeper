"""Validate the CI adapter manifests stay well-formed: .pre-commit-hooks.yaml + action.yml.

These are consumed by *other* repos, so a malformed manifest is a silent break for downstream users.
"""
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_precommit_hooks_valid():
    with open(os.path.join(ROOT, ".pre-commit-hooks.yaml"), encoding="utf-8") as fh:
        hooks = yaml.safe_load(fh)
    ids = {h["id"] for h in hooks}
    assert {"claude-harness-doctor", "claude-harness-ref-audit"} <= ids
    for h in hooks:
        assert h["language"] == "python"
        assert h["entry"].startswith("claude-harness ")
        assert h["pass_filenames"] is False


def test_action_yml_valid():
    with open(os.path.join(ROOT, "action.yml"), encoding="utf-8") as fh:
        action = yaml.safe_load(fh)
    assert action["runs"]["using"] == "composite"
    for inp in ("vault-path", "engine", "strict", "frontmatter-schema", "memory-dir"):
        assert inp in action["inputs"]
    # the action must actually invoke the CLI with --check
    run_steps = " ".join(s.get("run", "") for s in action["runs"]["steps"])
    assert "claude-harness" in run_steps and "--check" in run_steps
