"""Tests for --staged, the third member of the enforcement-scoping family (issue #26).

Applying a new rule to a mature collection produces hundreds of findings on day one. A reader
ignores three hundred stale ones to reach the one that is theirs, then stops reading, and the
documented outcome across the linting-UX literature is that the check gets switched off. Scoping to
the change in hand is what decides whether a rule is adoptable at all.

The half that is easy to get wrong, and which most of these tests are about: out-of-scope findings
must be COUNTED, not discarded. A scoped run that silently prints nothing reads as a clean
collection, and whoever runs unscoped later is ambushed by a backlog nobody mentioned.
"""
import json
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "vault-ref-audit.py")


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _vault(tmp_path):
    """A repo with one committed broken link, and nothing staged yet."""
    v = tmp_path / "v"
    v.mkdir()
    _git(v, "init", "-q")
    _git(v, "config", "user.email", "t@example.com")
    _git(v, "config", "user.name", "t")
    (v / "pre-existing.md").write_text("links to [[gone-a]]\n", encoding="utf-8")
    (v / "hub.md").write_text("see [[pre-existing]]\n", encoding="utf-8")
    _git(v, "add", "-A")
    _git(v, "commit", "-qm", "init")
    return v


def _run(v, *args):
    env = dict(os.environ, VAULT_ROOT=str(v))
    return subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True, env=env,
                          timeout=120)


def _json(v, *args):
    r = _run(v, "--json", *args)
    assert r.returncode in (0, 1), r.stderr
    return json.loads(r.stdout)


def test_unscoped_reports_the_pre_existing_finding(tmp_path):
    v = _vault(tmp_path)
    assert "pre-existing.md" in [x["note"] for x in _json(v)["broken_links"]]


def test_staged_with_nothing_staged_reports_nothing(tmp_path):
    # The day-one experience: adopting the rule on a mature collection must not dump the backlog.
    v = _vault(tmp_path)
    d = _json(v, "--staged")
    assert d["broken_links"] == []
    assert d["scope"]["staged"] is True


def test_staged_reports_only_what_this_change_introduces(tmp_path):
    v = _vault(tmp_path)
    (v / "new-note.md").write_text("links to [[gone-b]]\n", encoding="utf-8")
    _git(v, "add", "new-note.md")
    notes = [x["note"] for x in _json(v, "--staged")["broken_links"]]
    assert notes == ["new-note.md"], notes


def test_out_of_scope_findings_are_counted_not_discarded(tmp_path):
    # The load-bearing assertion. Silence about the backlog is how a scoped check becomes a lie.
    v = _vault(tmp_path)
    (v / "new-note.md").write_text("links to [[gone-b]]\n", encoding="utf-8")
    _git(v, "add", "new-note.md")
    scope = _json(v, "--staged")["scope"]
    assert scope["pre_existing_out_of_scope"] > 0, scope


def test_the_human_report_says_what_it_set_aside(tmp_path):
    v = _vault(tmp_path)
    (v / "new-note.md").write_text("links to [[gone-b]]\n", encoding="utf-8")
    _git(v, "add", "new-note.md")
    out = _run(v, "--staged").stdout
    assert "staged for commit" in out
    assert "pre-existing finding(s) outside this scope" in out


def test_staged_outside_a_git_repo_exits_2_not_0(tmp_path):
    # An empty scope from a failed git call would read as "nothing staged is broken", which is the
    # unreachable-is-not-empty principle applied to a scoping flag.
    v = tmp_path / "plain"
    v.mkdir()
    (v / "a.md").write_text("links to [[gone]]\n", encoding="utf-8")
    assert _run(v, "--staged", "--json").returncode == 2


def test_unstaged_edits_are_not_in_scope(tmp_path):
    # --staged means the index, not the working tree: it answers "what would this COMMIT introduce".
    v = _vault(tmp_path)
    (v / "unstaged.md").write_text("links to [[gone-c]]\n", encoding="utf-8")
    notes = [x["note"] for x in _json(v, "--staged")["broken_links"]]
    assert notes == [], notes


# --- the adoption line (issue #29) -------------------------------------------------------------

def test_adoption_line_carries_the_whole_posture(tmp_path):
    """new / baselined / resolved, on one line.

    Someone adopting on a mature collection sees a large number first and concludes the tool is not
    for them. This line is the answer to that, so it has to be present and correct rather than
    inferable from three other lines.
    """
    v = _vault(tmp_path)
    base = tmp_path / "baseline.json"
    r = _run(v, "--write-baseline", str(base))
    assert r.returncode == 0, r.stderr

    # nothing new yet
    out = _run(v, "--baseline", str(base)).stdout
    assert "adoption: 0 new," in out, out

    # introduce one break: it, and only it, is new
    (v / "today.md").write_text("links to [[not-a-note]]\n", encoding="utf-8")
    out = _run(v, "--baseline", str(base)).stdout
    assert "adoption:" in out
    assert "0 new" not in out.split("adoption:")[1].splitlines()[0]


def test_resolved_count_moves_when_a_baselined_finding_is_fixed(tmp_path):
    # The progress metric. It has to move, or step 5 of the adoption how-to is a lie.
    v = _vault(tmp_path)
    base = tmp_path / "baseline.json"
    _run(v, "--write-baseline", str(base))
    before = _run(v, "--baseline", str(base)).stdout
    assert "0 resolved" in before

    (v / "pre-existing.md").write_text("links to [[hub]]\n", encoding="utf-8")
    after = _run(v, "--baseline", str(base)).stdout
    assert "0 resolved" not in after.split("adoption:")[1].splitlines()[0], after
