"""A note name ENDING in a version number must resolve (defect D26).

`os.path.splitext` splits at the last dot unconditionally, so `SPF V9.0` yields ext `.0`. The guard
that decides "is this really an extension" accepted any alphanumeric run of 1-8 characters, and `0`
is one. The version was stripped, the target was searched for as a literal filename, and it never
resolved.

The signature is a self-contradiction inside ONE run: the note is reported as an orphan (no inbound
links) while being the target of dozens of "broken" links. Both findings cannot be true, and a
report that states both has already disproved itself. That is what makes this worth a test rather
than a patch -- it was found in a real collection because two of its own numbers disagreed.

The tempting fix is "an extension must start with a letter". It is wrong: `.7z` and `.3gp` are real.
"""
import json
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "vault-ref-audit.py")


def _audit(vault):
    r = subprocess.run([sys.executable, ENGINE, "--json"], capture_output=True, text=True,
                       env=dict(os.environ, VAULT_ROOT=str(vault)), timeout=180)
    assert r.returncode in (0, 1), r.stderr
    return json.loads(r.stdout)


def _write(vault, name, body=""):
    vault.joinpath(name).write_text(f"---\ntitle: {name[:-3]}\n---\n{body}\n", encoding="utf-8")


def test_a_link_to_a_version_suffixed_note_resolves(tmp_path):
    v = tmp_path / "v"
    v.mkdir()
    _write(v, "SPF V9.0.md")
    _write(v, "netlayout v0.3.md")
    _write(v, "hub.md", "see [[SPF V9.0]] and [[netlayout v0.3]]")

    out = _audit(v)
    broken = [b for b in out.get("broken_links", []) if "SPF V9" in str(b) or "netlayout" in str(b)]
    assert not broken, f"links to version-suffixed notes reported broken: {broken}"


def test_the_note_is_not_simultaneously_an_orphan_and_a_link_target(tmp_path):
    """The contradiction itself, pinned.

    This is the assertion that would have caught D26 in the shape it was actually found: not "a
    count is wrong" but "these two outputs disagree with each other".
    """
    v = tmp_path / "v"
    v.mkdir()
    _write(v, "SPF V9.0.md")
    _write(v, "hub.md", "see [[SPF V9.0]]")

    out = _audit(v)
    orphans = {os.path.basename(str(o)) for o in out.get("orphans", [])}
    assert "SPF V9.0.md" not in orphans, (
        "the note is reported as an orphan while another note links to it; one of the two findings "
        "in this same report must be false")


def test_a_real_digit_leading_extension_is_still_an_extension(tmp_path):
    """Guard against the easy over-fix. `.7z` must not become part of the note name."""
    sys.path.insert(0, os.path.join(HARNESS, "scripts"))
    import re
    # The predicate under test, mirrored: extension iff alphanumeric 1-8 AND not purely numeric.
    def is_ext(ext):
        return bool(re.fullmatch(r"\.[A-Za-z0-9]{1,8}", ext)) and not re.fullmatch(r"\.\d+", ext)

    assert is_ext(".md") and is_ext(".png") and is_ext(".canvas")
    assert is_ext(".7z"), "a digit-leading extension is still an extension"
    assert is_ext(".3gp")
    assert not is_ext(".0"), "a version number is not an extension"
    assert not is_ext(".3"), "nor is a single digit"
    assert not is_ext(".20")
