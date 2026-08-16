"""Tests for the external engine seam.

ADR-0004 refuses domain-specific content in the portable core, so "add it here" is the wrong answer
for most real needs, and forking or vendoring is worse. NEUROKEEPER_ENGINE_PATH lets an engine live
in its owner's repository and still be a first-class citizen.

Most of these are about failing LOUDLY. A discovery mechanism that quietly finds nothing is the
worst possible shape: the engines appear to have vanished, and an empty result reads as "you have
none" rather than "your configuration is wrong".
"""
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENGINE = '''#!/usr/bin/env python3
# @capability:  {name}
# @compute:     deterministic
# @effect:      read-only
import sys
print("{name} ran")
sys.exit({rc})
'''


def _dir(tmp_path, name="ext", engines=(("acme-thing", 0),), extras=()):
    d = tmp_path / name
    d.mkdir()
    for engine_name, rc in engines:
        (d / f"{engine_name}.py").write_text(ENGINE.format(name=engine_name, rc=rc),
                                             encoding="utf-8")
    for fn, body in extras:
        (d / fn).write_text(body, encoding="utf-8")
    return d


def _run(*args, path=None):
    env = dict(os.environ)
    env.pop("NEUROKEEPER_ENGINE_PATH", None)
    if path is not None:
        env["NEUROKEEPER_ENGINE_PATH"] = str(path)
    return subprocess.run([sys.executable, "-m", "neurokeeper.cli", *args],
                          capture_output=True, text=True, cwd=HARNESS, env=env, timeout=90)


def test_builtins_still_work_with_no_engine_path():
    # The seam must be invisible when unused.
    r = _run("--list")
    assert r.returncode == 0
    assert "ref-audit" in r.stdout


def test_an_external_engine_dispatches(tmp_path):
    d = _dir(tmp_path)
    r = _run("acme-thing", path=d)
    assert r.returncode == 0, r.stderr
    assert "acme-thing ran" in r.stdout


def test_an_external_engine_keeps_its_own_exit_code(tmp_path):
    # The exit contract is the engine's, not the dispatcher's: a gate that fails must still fail.
    d = _dir(tmp_path, engines=(("acme-gate", 1),))
    assert _run("acme-gate", path=d).returncode == 1


def test_external_engines_are_listed_with_their_source(tmp_path):
    # Where an engine came from is part of trusting its output.
    r = _run("--list", path=_dir(tmp_path))
    assert "acme-thing" in r.stdout
    assert str(tmp_path) in r.stdout


def test_a_file_without_a_capability_header_is_not_an_engine(tmp_path):
    # A helper module sitting beside an engine must not be dispatchable.
    d = _dir(tmp_path, extras=(("plain.py", "print(1)\n"),))
    r = _run("plain", path=d)
    assert r.returncode == 2
    # ...and the likeliest cause is named, because "unknown engine" about a file you just wrote and
    # can see in the directory is a confusing thing to be told.
    assert "no '# @capability:' header" in r.stderr


def test_underscore_files_are_never_engines(tmp_path):
    d = _dir(tmp_path, extras=(("_private.py", "# @capability: _private\n"),))
    assert _run("_private", path=d).returncode == 2


def test_a_nonexistent_path_entry_is_loud(tmp_path):
    # THE important one. Skipping a bad path would report the owner's engines as absent rather than
    # as misconfigured, and absent reads as "you have none".
    r = _run("--list", path=tmp_path / "does-not-exist")
    assert r.returncode != 0
    assert "does not exist" in r.stderr


def test_an_external_engine_may_not_shadow_a_builtin(tmp_path):
    # Refusing rather than choosing: a core engine quietly replaced makes every report from this
    # tool untrustworthy, and the replacement would be invisible.
    d = _dir(tmp_path, engines=(("ref-audit", 0),))
    r = _run("ref-audit", path=d)
    assert r.returncode != 0
    assert "shadow" in r.stderr


def test_unknown_engine_names_where_it_looked(tmp_path):
    # A useful failure says where it searched, so a misconfigured path is diagnosable.
    r = _run("no-such-engine", path=_dir(tmp_path))
    assert r.returncode == 2
    assert "looked in" in r.stderr


def test_unknown_engine_mentions_the_variable_when_unset():
    r = _run("no-such-engine")
    assert "NEUROKEEPER_ENGINE_PATH is not set" in r.stderr


def test_multiple_directories_are_searched(tmp_path):
    a = _dir(tmp_path, name="a", engines=(("acme-one", 0),))
    b = _dir(tmp_path, name="b", engines=(("acme-two", 0),))
    both = f"{a}{os.pathsep}{b}"
    assert _run("acme-one", path=both).returncode == 0
    assert _run("acme-two", path=both).returncode == 0


def test_discovery_resolves_relative_entries_to_absolute_paths(tmp_path):
    # A relative entry is legitimate; a relative RESULT is not, because every consumer joins it
    # against its own directory. doctor did exactly that and ran nothing at all.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ep", os.path.join(HARNESS, "scripts", "_engine_path.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _dir(tmp_path, name="rel")
    old = os.getcwd()
    try:
        os.chdir(tmp_path)
        os.environ["NEUROKEEPER_ENGINE_PATH"] = "rel"
        found = mod.discover()
    finally:
        os.environ.pop("NEUROKEEPER_ENGINE_PATH", None)
        os.chdir(old)
    path, src = found["acme-thing"]
    assert os.path.isabs(path) and os.path.isabs(src)
    assert os.path.isfile(path)


def test_the_stable_helper_surface_imports():
    # The worked example in the how-to imports from neurokeeper.lib. If that surface does not exist,
    # the documentation is a claim the code does not honour.
    r = subprocess.run(
        [sys.executable, "-c",
         "from neurokeeper.lib import md_files, parse_frontmatter, split_frontmatter, kebabify, "
         "force_utf8_stdout, find_links; print('ok')"],
        capture_output=True, text=True, cwd=HARNESS, timeout=90)
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout
