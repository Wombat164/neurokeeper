"""`--list-records` must read the register from the SAME places the rest of the engine does.

Correlation honours `IDENTIFIER_REGISTER`; `--list-records` accepted only the `--register` flag and
exited with an error when the env var alone was set. A correctly-configured site therefore got
record-number scoring during correlation and "needs --register with `identifier_patterns`" from the
index dump, which reads as "my register is broken" rather than "pass the same thing twice".

Found by running every engine against a real collection rather than by reading the code, and no test
covered this flag at all - which is why it survived.
"""
import json
import os
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "vault-correlate.py")
yaml = pytest.importorskip("yaml")

REGISTER = {
    "identifier_patterns": {
        # The key is `match`. Writing `regex:` here is how the skip-do-not-crash path below was
        # found: it leaves the pattern None and re.compile raises TypeError, not re.error.
        "ticket": {"match": r"TKT\d{4}", "min_digits": 4},
    },
}


def _setup(tmp_path):
    v = tmp_path / "v"
    v.mkdir()
    v.joinpath("a.md").write_text("---\ntitle: A\n---\nsee TKT1234 and TKT5678\n", encoding="utf-8")
    v.joinpath("b.md").write_text("---\ntitle: B\n---\nalso TKT1234\n", encoding="utf-8")
    reg = tmp_path / "register.yaml"
    reg.write_text(yaml.safe_dump(REGISTER), encoding="utf-8")
    return v, reg


def _list_records(v, cache, *, env_register=None, flag_register=None):
    env = dict(os.environ, VAULT_ROOT=str(v))
    env.pop("IDENTIFIER_REGISTER", None)
    if env_register:
        env["IDENTIFIER_REGISTER"] = str(env_register)
    cmd = [sys.executable, ENGINE, "--list-records", "--cache", str(cache)]
    if flag_register:
        cmd += ["--register", str(flag_register)]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)


def _records(out):
    return {r["value"]: r["count"] for r in json.loads(out)["records"]}


def test_the_env_var_alone_is_enough(tmp_path):
    v, reg = _setup(tmp_path)
    r = _list_records(v, tmp_path / "c1.json", env_register=reg)
    assert r.returncode == 0, r.stderr
    assert _records(r.stdout) == {"TKT1234": 2, "TKT5678": 1}


def test_the_flag_still_works_and_wins(tmp_path):
    """The flag is the explicit override; env-only must not have made it inert."""
    v, reg = _setup(tmp_path)
    empty = tmp_path / "empty.yaml"
    empty.write_text(yaml.safe_dump({"identifier_patterns": {}}), encoding="utf-8")
    r = _list_records(v, tmp_path / "c2.json", flag_register=reg)
    assert r.returncode == 0, r.stderr
    assert _records(r.stdout) == {"TKT1234": 2, "TKT5678": 1}

    # Flag beats env: pointing the flag at a pattern-less register must refuse, not fall back to
    # the env var and quietly report the env register's results as though the flag were honoured.
    r = _list_records(v, tmp_path / "c3.json", env_register=reg, flag_register=empty)
    assert r.returncode != 0


def test_a_malformed_pattern_is_skipped_not_fatal(tmp_path):
    """`compile_patterns` documents this and only half-did it.

    It caught re.error but not TypeError, so a misspelled key (`regex:` for `match:`) left the
    pattern None and crashed the engine with a traceback from inside `re`. One unusable entry must
    cost you that entry, not the run.
    """
    v, reg = _setup(tmp_path)
    mixed = tmp_path / "mixed.yaml"
    mixed.write_text(yaml.safe_dump({"identifier_patterns": {
        "typo": {"regex": r"TKT\d{4}"},               # wrong key -> pattern is None
        "ticket": {"match": r"TKT\d{4}", "min_digits": 4},
    }}), encoding="utf-8")
    r = _list_records(v, tmp_path / "c5.json", env_register=mixed)
    assert r.returncode == 0, r.stderr
    assert _records(r.stdout) == {"TKT1234": 2, "TKT5678": 1}, "the good pattern must survive"
    assert "typo" in r.stderr, "the skipped entry must be NAMED, or it is a silent loss"


def test_with_no_register_at_all_it_refuses_rather_than_reporting_nothing(tmp_path):
    """The dangerous outcome is an empty index, not an error.

    "0 record identifiers" from an unconfigured run is indistinguishable from "this collection
    genuinely has none", and the second is a conclusion someone would act on.
    """
    v, _reg = _setup(tmp_path)
    r = _list_records(v, tmp_path / "c4.json")
    assert r.returncode != 0
    assert "identifier_patterns" in (r.stdout + r.stderr)
