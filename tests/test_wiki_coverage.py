"""R20 wiki-coverage gate: the docs site cannot lag the tool.

Field receipt (2026-07-04): `memory-consolidate --lint` shipped but the Quartz wiki's
reference catalog did not gain the flag until a follow-up pass -- the exact "docs lag the
tool" drift the add-a-new-engine how-to warns against, with nothing enforcing it. This test
IS the enforcement: it derives the ground truth from code (the cli.py dispatch map + each
engine's declared flags) and fails when a user-facing engine or flag is absent from the
wiki reference. Same deterministic-gate doctrine as the engines themselves -- a machine
refuses the merge, rather than relying on someone remembering.

Two escape hatches, both deliberate and visible:
  - INTERNAL       -- subcommands that are plumbing, not knowledge-work capabilities, so they
                      are intentionally NOT in the user-facing catalog (each justified inline).
  - IGNORE_FLAGS   -- universal flags not worth a per-engine catalog mention.
A NEW engine or flag forces a choice: document it, or add it here with a reason. Silence is
not an option -- that is the whole point.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "neurokeeper" / "cli.py"
SCRIPTS = REPO_ROOT / "scripts"
WIKI_REF = REPO_ROOT / "wiki" / "content" / "reference" / "index.md"

# Subcommands that are plumbing, not user-facing knowledge-work capabilities. Kept out of the
# catalog on purpose; listed here (with a reason) so a NEW engine can never hide by omission.
INTERNAL = {
    "check-release": "release/CI version-sync helper, not a vault/memory capability",
}
# Universal flags not worth a per-engine catalog entry.
IGNORE_FLAGS = {"--help"}


def _engines_from_cli():
    """The authoritative {subcommand: engine_filename} map -- the ENGINES dict in cli.py."""
    src = CLI.read_text(encoding="utf-8")
    block = re.search(r"ENGINES\s*=\s*\{(.+?)\}", src, re.S)
    assert block, "could not find the ENGINES dispatch map in cli.py"
    pairs = re.findall(r'"([a-z0-9-]+)"\s*:\s*"([A-Za-z0-9_.-]+\.py)"', block.group(1))
    assert pairs, "ENGINES map parsed empty -- the regex or the map format changed"
    return dict(pairs)


def _declared_flags(engine_filename):
    """Every `--flag` literal in an engine's source -- catches argparse, `x in args`, and `== '--x'`."""
    src = (SCRIPTS / engine_filename).read_text(encoding="utf-8")
    return set(re.findall(r"""["'](--[a-z0-9][a-z0-9-]*)["']""", src)) - IGNORE_FLAGS


def _wiki():
    text = WIKI_REF.read_text(encoding="utf-8")
    headings = set(re.findall(r"^###\s+`([a-z0-9-]+)`", text, re.M))
    return text, headings


def test_every_user_facing_engine_is_in_the_wiki_catalog():
    _, headings = _wiki()
    engines = _engines_from_cli()
    missing = [name for name in engines if name not in INTERNAL and name not in headings]
    assert not missing, (
        f"engines missing a `### `<name>`` entry in wiki/content/reference/index.md: {missing}. "
        "Document each in the catalog, or add it to INTERNAL (with a reason) if it is plumbing. "
        "(R20 wiki-coverage gate)"
    )


def test_no_phantom_catalog_entries():
    """Every catalog heading maps to a real subcommand -- catches docs for a removed/renamed engine."""
    _, headings = _wiki()
    engines = set(_engines_from_cli())
    phantom = [h for h in headings if h not in engines]
    assert not phantom, (
        f"wiki catalog documents engines that are not in cli.py's ENGINES map: {phantom}. "
        "Remove the stale entry or fix the heading to the real subcommand name. (R20)"
    )


def test_every_declared_flag_is_documented_in_the_wiki():
    text, _ = _wiki()
    engines = _engines_from_cli()
    gaps = {}
    for name, fn in engines.items():
        if name in INTERNAL:
            continue
        undocumented = sorted(f for f in _declared_flags(fn) if f not in text)
        if undocumented:
            gaps[name] = undocumented
    assert not gaps, (
        f"engines with declared flags absent from the wiki reference: {gaps}. "
        "Add each flag to that engine's Contract line, or to IGNORE_FLAGS if universal. "
        "(R20 wiki-coverage gate -- this is the class that let `--lint` ship undocumented)"
    )
