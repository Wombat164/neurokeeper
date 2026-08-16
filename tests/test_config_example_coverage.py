"""Every file-shaped config an engine reads must ship an example.

An engine that needs a config file nobody can see the shape of is an engine nobody can adopt. The
docs describe the shapes in prose, which is useful and is not the same as a file you can copy.

This was not hypothetical: three engines shipped in one day with no example between them, so a
reader had to reverse-engineer the format from source. That is the same class as an undocumented
flag, which is why it gets the same treatment as the wiki-coverage gate.

Deliberately scoped to FILE-shaped config. Env vars carrying a path list or a boolean are
self-evident from the reference page; a manifest format is not.
"""
import json
import os
import re

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(HARNESS, "scripts")
EXAMPLES = os.path.join(HARNESS, "config.example")

# Suffixes that mean "this names a file with a structure". A _DIR or _ROOT is a path; a _MAP is a
# JSON blob documented inline; these are the ones a reader has to be shown.
FILE_SHAPED = ("_MANIFEST", "_SCHEMA", "_REGISTER", "_DENYLIST", "_CONFIG")

# Config read by an engine but supplied by the caller's environment rather than authored as a file.
NOT_AUTHORED = {"HARNESS_ROOT", "VAULT_BACKEND"}


def _declared_config():
    """Every env var the engines read, from the source rather than from a list someone maintains."""
    found = set()
    for fn in os.listdir(SCRIPTS):
        if not fn.endswith(".py"):
            continue
        src = open(os.path.join(SCRIPTS, fn), encoding="utf-8", errors="replace").read()
        found.update(re.findall(r'os\.environ\.get\(\s*["\']([A-Z][A-Z0-9_]+)["\']', src))
        found.update(re.findall(r'os\.environ\[\s*["\']([A-Z][A-Z0-9_]+)["\']', src))
    return found


def _example_blob():
    out = []
    for fn in os.listdir(EXAMPLES):
        out.append(fn)
        try:
            out.append(open(os.path.join(EXAMPLES, fn), encoding="utf-8", errors="replace").read())
        except OSError:
            pass
    return "\n".join(out).lower()


def test_every_file_shaped_config_has_an_example():
    blob = _example_blob()
    gaps = []
    for var in sorted(_declared_config()):
        if var in NOT_AUTHORED or not var.endswith(FILE_SHAPED):
            continue
        # An example counts if it names the variable, or if a file is named for it.
        stem = var.lower().replace("_", "-")
        if var.lower() in blob or stem in blob:
            continue
        gaps.append(var)
    assert not gaps, (
        f"config an engine reads with no shipped example: {gaps}. Add a file to config.example/ "
        f"naming the variable, or add it to NOT_AUTHORED if the caller supplies it rather than "
        f"authoring it. An engine needing a file nobody can see the shape of is one nobody adopts.")


def test_json_examples_parse():
    # An example that does not parse teaches the wrong shape, confidently.
    for fn in os.listdir(EXAMPLES):
        if fn.endswith(".json"):
            with open(os.path.join(EXAMPLES, fn), encoding="utf-8") as fh:
                json.load(fh)


def test_yaml_examples_parse():
    yaml = __import__("pytest").importorskip("yaml")
    for fn in os.listdir(EXAMPLES):
        if fn.endswith((".yaml", ".yml")):
            with open(os.path.join(EXAMPLES, fn), encoding="utf-8") as fh:
                yaml.safe_load(fh)


def test_the_denylist_example_passes_its_own_audit():
    """The example must be a good example, not merely a parsable one.

    denylist-audit reports entries that match nothing. An example file that would itself fail that
    check is teaching a shape which does not work.
    """
    import subprocess
    import sys
    p = os.path.join(EXAMPLES, "egress-denylist.example.txt")
    if not os.path.isfile(p):
        return
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "denylist-audit.py"),
                        "--denylist", p], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, f"the shipped denylist example fails its own audit:\n{r.stdout}"
