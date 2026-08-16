"""Tests for check-release.py prose version pins (issue #33).

The gate reported "version synced" and exited 0 while seven copyable refs in README, wiki and docs
still pointed at releases two minor versions back. It validated the manifests, which tooling reads
and would have failed loudly on, and never looked at the refs a HUMAN copies into their own
pre-commit config and workflow. The stale ones are the failure nobody reports, because from the
outside it just works.

These lock both directions: the check must fire on a stale copyable ref, and must stay quiet on
prose that legitimately names an old version.
"""
import importlib.util
import os
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "check-release.py")

_spec = importlib.util.spec_from_file_location("check_release", ENGINE)
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)


def _docs(tmp_path, readme="", wiki=None, docs=None):
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    for rel, text in (wiki or {}).items():
        p = tmp_path / "wiki" / "content" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    for rel, text in (docs or {}).items():
        p = tmp_path / "docs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _versions(pins):
    return sorted(v for _, _, v, _, _ in pins)


def test_finds_the_three_copyable_ref_shapes(tmp_path):
    root = _docs(tmp_path, readme=(
        "# x\n"
        "> Status: **0.4.0 (alpha).** MIT.\n"
        "```yaml\n"
        "    rev: v0.4.0\n"
        "```\n"
        "- uses: Owner/repo@v0.4.0\n"))
    kinds = sorted(k for _, _, _, k, _ in cr._prose_pins(root))
    assert kinds == ["pre-commit rev", "status line", "workflow uses ref"], kinds


def test_catches_a_stale_pin(tmp_path):
    # The whole point. A gate that cannot fire is not a gate.
    root = _docs(tmp_path, readme="    rev: v0.3.2\n")
    assert _versions(cr._prose_pins(root)) == ["0.3.2"]


def test_scans_wiki_and_docs_not_just_readme(tmp_path):
    # The original miss was spread across three trees; checking only the README would have found
    # three of the seven refs and reported success.
    root = _docs(tmp_path,
                 readme="    rev: v0.4.0\n",
                 wiki={"how-to/index.md": "- uses: Owner/repo@v0.3.2\n"},
                 docs={"ci-adapters.md": "    rev: v0.3.0\n"})
    assert _versions(cr._prose_pins(root)) == ["0.3.0", "0.3.2", "0.4.0"]


def test_ignores_prose_that_merely_mentions_a_version(tmp_path):
    # NEGATIVE case, and the one that decides whether anyone leaves this check switched on. A
    # changelog entry or an upgrade note is correct while looking stale.
    root = _docs(tmp_path, readme=(
        "Broken in 0.3.1, fixed in 0.3.2.\n"
        "Upgrading from 0.2.x requires a re-index.\n"
        "See the v0.3.5 release notes for details.\n"))
    assert cr._prose_pins(root) == []


def test_skips_historical_files_by_name(tmp_path):
    # A changelog exists to record what WAS true; pinning it to the current version is nonsense.
    root = _docs(tmp_path, docs={"CHANGELOG.md": "    rev: v0.1.0\n",
                                 "adr-0002-thing.md": "    rev: v0.2.0\n",
                                 "roadmap.md": "    rev: v0.3.0\n"})
    assert cr._prose_pins(root) == []


def test_opt_out_marker_exempts_one_line(tmp_path):
    # Escape hatch for a deliberately pinned example, so the fix for a false positive is one
    # comment rather than switching the whole check off.
    root = _docs(tmp_path, readme="    rev: v0.1.0  <!-- pin-ok -->\n    rev: v0.4.0\n")
    assert _versions(cr._prose_pins(root)) == ["0.4.0"]


def test_tag_existence_is_advisory_and_fails_open(tmp_path):
    # A pin can be correct and its tag not cut yet, which is the normal release order. That must
    # never block, and an environment without git must not produce a false warning either.
    assert cr._tag_exists("0.4.0") in (True, False)
    assert cr._tag_exists("99.99.99") is False
