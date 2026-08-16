"""init: configure a collection, and be checkable about it.

Most of these assert what it must NOT do. A wizard's failures are all of the same kind - it did
something helpful that nobody asked for, to a collection whose shape was not its to decide.
"""
import json
import os
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "init.py")

NOTE = "---\nnote_type: {t}\nstatus: {s}\ntitle: {title}\n---\n\nbody\n"


@pytest.fixture
def collection(tmp_path):
    c = tmp_path / "coll"
    (c / "projects").mkdir(parents=True)
    (c / "projects" / "a.md").write_text(NOTE.format(t="project", s="active", title="A"),
                                         encoding="utf-8")
    (c / "projects" / "b.md").write_text(NOTE.format(t="project", s="draft", title="B"),
                                         encoding="utf-8")
    (c / "note.md").write_text(NOTE.format(t="note", s="active", title="C"), encoding="utf-8")
    return c


def _run(collection, *args, expect=None):
    env = dict(os.environ)
    for k in ("FRONTMATTER_SCHEMA", "IDENTIFIER_REGISTER", "CLAUDE_MEMORY_DIR"):
        env.pop(k, None)
    r = subprocess.run([sys.executable, ENGINE, "--collection", str(collection),
                        "--non-interactive", *args],
                       capture_output=True, text=True, env=env, timeout=300)
    if expect is not None:
        assert r.returncode == expect, r.stdout + r.stderr
    return r


def test_it_reports_the_note_count_it_can_see(collection):
    # Said out loud, before anything is written. A wizard that silently scopes to the wrong root
    # produces a config that reports clean forever and nobody can tell.
    r = _run(collection, "--dry-run")
    assert "3 markdown note(s)" in r.stdout


def test_the_count_is_the_real_count(collection):
    # Regression: an earlier version set VAULT_ROOT and called the walker with no argument, which
    # reads a module-level default captured at import. It confidently counted the working directory.
    (collection / "sub").mkdir()
    (collection / "sub" / "d.md").write_text(NOTE.format(t="note", s="active", title="D"),
                                             encoding="utf-8")
    r = _run(collection, "--dry-run")
    assert "4 markdown note(s)" in r.stdout


def test_dry_run_writes_nothing(collection):
    before = sorted(os.listdir(collection))
    _run(collection, "--schema", "derive", "--gates", "--baseline", "--dry-run")
    assert sorted(os.listdir(collection)) == before
    assert not (collection / ".neurokeeper").exists()


def test_it_never_writes_content(collection):
    """The load-bearing constraint. It configures; it does not decide the collection's shape.

    A tool that invents folders or notes on day one has chosen a structure before its owner has,
    which is exactly what the substrate-boundary ADR refuses.
    """
    before = {}
    for root, _dirs, files in os.walk(collection):
        for f in files:
            p = os.path.join(root, f)
            before[p] = open(p, encoding="utf-8").read()
    _run(collection, "--schema", "derive")
    after = {}
    for root, _dirs, files in os.walk(collection):
        for f in files:
            if ".neurokeeper" in root:
                continue                      # config is allowed; content is not
            p = os.path.join(root, f)
            after[p] = open(p, encoding="utf-8").read()
    assert after == before, "init modified or created content"


def test_a_derived_schema_is_marked_harvested(collection):
    """Never `decided`.

    A schema drafted from what a collection contains is harvested by definition. Promoting it
    silently would make the tool's reading of a collection into that collection's law.
    """
    _run(collection, "--schema", "derive")
    text = (collection / ".neurokeeper" / "frontmatter-schema.yaml").read_text(encoding="utf-8")
    # The FIELD, not a substring search: the prose legitimately contains the word "decided" while
    # saying that nothing here was.
    provenance = [ln for ln in text.splitlines() if ln.startswith("provenance:")]
    assert provenance == ['provenance: "harvested"'], provenance


def test_a_derived_schema_says_it_is_a_draft(collection):
    # In the file itself, as a field rather than a comment: the reader six months from now has no
    # memory of this run, and a comment survives no round-trip.
    _run(collection, "--schema", "derive")
    text = (collection / ".neurokeeper" / "frontmatter-schema.yaml").read_text(encoding="utf-8")
    assert "DRAFT" in text
    assert "CONTAINS" in text


def test_a_derived_schema_captures_the_real_vocabulary(collection):
    _run(collection, "--schema", "derive")
    text = (collection / ".neurokeeper" / "frontmatter-schema.yaml").read_text(encoding="utf-8")
    assert "note_type" in text and "project" in text and "active" in text


def test_high_cardinality_fields_become_open_not_enums(tmp_path):
    """A field with hundreds of values is free text.

    Enumerating it would produce a schema that fails on nearly every note, which is how a generated
    schema teaches its owner that the linter is wrong.
    """
    c = tmp_path / "many"
    c.mkdir()
    for i in range(40):
        (c / f"n{i}.md").write_text(f"---\nnote_type: note\nref: REF-{i}\n---\n", encoding="utf-8")
    _run(c, "--schema", "derive")
    text = (c / ".neurokeeper" / "frontmatter-schema.yaml").read_text(encoding="utf-8")
    assert "open" in text
    assert "REF-39" not in text                     # not enumerated


def test_title_is_not_proposed_as_an_axis(collection):
    # Structure, not subject matter. Every note has a distinct one and it classifies nothing.
    _run(collection, "--schema", "derive")
    text = (collection / ".neurokeeper" / "frontmatter-schema.yaml").read_text(encoding="utf-8")
    assert "\n  title:" not in text


def test_it_prints_every_file_it_wrote(collection):
    r = _run(collection, "--schema", "derive")
    assert "frontmatter-schema.yaml" in r.stdout
    assert "wrote:" in r.stdout


def test_it_ends_on_a_real_verification(collection):
    # Not a claim of success. A wizard whose output cannot be checked has produced configuration
    # nobody can audit.
    r = _run(collection, "--schema", "derive")
    assert "verifying" in r.stdout
    assert "doctor --check -> exit" in r.stdout


def test_it_names_the_env_vars_the_config_needs(collection):
    # Writing config that nothing reads is the same silent-nothing this engine exists to end.
    r = _run(collection, "--schema", "derive")
    assert "FRONTMATTER_SCHEMA" in r.stdout


def test_an_empty_collection_says_so_rather_than_configuring_it(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(empty, "--dry-run")
    assert "0 markdown note(s)" in r.stdout
    assert "the root above is wrong" in r.stdout


def test_a_missing_collection_is_exit_3(tmp_path):
    r = subprocess.run([sys.executable, ENGINE, "--collection", str(tmp_path / "nope"),
                        "--non-interactive"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 3


def test_skip_is_honoured(collection):
    r = _run(collection, "--schema", "skip", "--register", "skip")
    assert "wrote: nothing" in r.stdout
    assert not (collection / ".neurokeeper" / "frontmatter-schema.yaml").exists()


def test_json_mode_reports_what_happened(collection):
    r = _run(collection, "--schema", "derive", "--json")
    blob = r.stdout[r.stdout.index("{"):]
    data = json.loads(blob)
    assert data["notes"] == 3
    assert data["counts"]["written"] == 1
    assert "FRONTMATTER_SCHEMA" in data["env"]


def test_the_derived_schema_is_valid_yaml(collection):
    yaml = pytest.importorskip("yaml")
    _run(collection, "--schema", "derive")
    with open(collection / ".neurokeeper" / "frontmatter-schema.yaml", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert doc["provenance"] == "harvested"
    assert "note_type" in doc["axes"]


def test_the_derived_schema_is_usable_by_the_engine_that_reads_it(collection):
    """The end-to-end claim: config this wrote must work in the engine it was written for.

    A wizard that emits a plausible file the real consumer rejects has produced a document, not
    configuration.
    """
    _run(collection, "--schema", "derive")
    env = dict(os.environ)
    env["FRONTMATTER_SCHEMA"] = str(collection / ".neurokeeper" / "frontmatter-schema.yaml")
    env["VAULT_ROOT"] = str(collection)
    r = subprocess.run([sys.executable, os.path.join(HARNESS, "scripts", "vault-frontmatter-lint.py"),
                        "--json"], capture_output=True, text=True, env=env, timeout=180)
    assert r.returncode in (0, 1), r.stdout + r.stderr
    json.loads(r.stdout)          # it produced a real report, not a traceback
