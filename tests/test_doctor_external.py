"""An external engine may join the doctor roll-up, by opting in and only by opting in.

Being dispatchable must not mean "run this whenever someone asks about the health of my collection".
An engine that is slow, or that talks to a network, or that answers an entirely different question,
would otherwise be conscripted into a report the operator reads as a health summary.
"""
import json
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(HARNESS, "scripts", "vault-doctor.py")

# A well-behaved participant: accepts the invocation doctor documents, emits counts, exits per ADR-0002.
ENGINE = '''#!/usr/bin/env python3
# @capability:  {name}
# @compute:     deterministic
# @effect:      read-only
{doctor}import argparse, json, sys
p = argparse.ArgumentParser()
p.add_argument("--check", action="store_true")
p.add_argument("--json", action="store_true")
a = p.parse_args()
if a.json:
    print(json.dumps({{"counts": {{"widgets": 3}}}}))
sys.exit({rc})
'''

# One that ignored the contract: it exits 2 for an unrecognised flag, which collides with the
# NOT CONFIGURED skip.
STRICT_ENGINE = '''#!/usr/bin/env python3
# @capability:  {name}
# @compute:     deterministic
# @effect:      read-only
{doctor}import argparse, sys
argparse.ArgumentParser().parse_args()
sys.exit({rc})
'''


def _ext(tmp_path, name="acme-check", rc=0, doctor="gate", template=ENGINE):
    d = tmp_path / "ext"
    d.mkdir(exist_ok=True)
    hdr = f"# @doctor:      {doctor}\n" if doctor else ""
    (d / f"{name}.py").write_text(template.format(name=name, rc=rc, doctor=hdr), encoding="utf-8")
    return d


def _doctor(tmp_path, path=None, *args):
    env = dict(os.environ)
    env.pop("NEUROKEEPER_ENGINE_PATH", None)
    env.pop("CLAUDE_MEMORY_DIR", None)
    env.pop("FRONTMATTER_SCHEMA", None)
    env["VAULT_ROOT"] = str(tmp_path / "vault")
    os.makedirs(env["VAULT_ROOT"], exist_ok=True)
    if path is not None:
        env["NEUROKEEPER_ENGINE_PATH"] = str(path)
    r = subprocess.run([sys.executable, DOCTOR, "--json", *args],
                       capture_output=True, text=True, env=env, timeout=180)
    try:
        return r, json.loads(r.stdout)
    except Exception:
        return r, None


def _engines(data):
    return {e["engine"]: e for e in data["engines"]}


def test_an_opted_in_engine_appears_in_the_report(tmp_path):
    r, data = _doctor(tmp_path, _ext(tmp_path))
    assert data, r.stdout[:400] + r.stderr[:400]
    assert "acme-check" in _engines(data)


def test_its_origin_is_visible(tmp_path):
    # An operator reading a health summary is entitled to know which findings came from this
    # project's engines and which came from someone else's.
    _, data = _doctor(tmp_path, _ext(tmp_path))
    assert _engines(data)["acme-check"]["origin"] == "external"
    assert _engines(data)["ref-audit"]["origin"] == "built-in"


def test_an_engine_without_the_header_is_not_composed(tmp_path):
    # Dispatchable != conscripted.
    _, data = _doctor(tmp_path, _ext(tmp_path, doctor=""))
    assert "acme-check" not in _engines(data)


def test_doctor_no_header_opt_out_is_honoured(tmp_path):
    _, data = _doctor(tmp_path, _ext(tmp_path, doctor="no"))
    assert "acme-check" not in _engines(data)


def test_a_gate_engine_can_fail_the_rollup(tmp_path):
    r, data = _doctor(tmp_path, _ext(tmp_path, rc=1, doctor="gate"), "--check")
    assert _engines(data)["acme-check"]["state"] == "fail"
    assert r.returncode == 1


def test_an_advisory_engine_reports_but_cannot_fail_the_rollup(tmp_path):
    r, data = _doctor(tmp_path, _ext(tmp_path, rc=0, doctor="advisory"), "--check")
    assert _engines(data)["acme-check"]["state"] == "ok"
    assert r.returncode == 0


def test_an_advisory_engine_exiting_one_is_a_loud_contract_breach(tmp_path):
    # Not quietly downgraded to ok: that would let an engine's only way of saying something is
    # wrong be swallowed by the level it declared for itself.
    r, data = _doctor(tmp_path, _ext(tmp_path, rc=1, doctor="advisory"), "--check")
    assert _engines(data)["acme-check"]["state"] == "error"
    assert r.returncode != 0


def test_exit_two_from_an_external_engine_is_a_skip(tmp_path):
    # ADR-0002 applies to external engines too: 2 is NOT CONFIGURED, which is not ill health.
    r, data = _doctor(tmp_path, _ext(tmp_path, rc=2, doctor="gate"), "--check")
    assert _engines(data)["acme-check"]["state"] == "skipped"
    assert r.returncode == 0


def test_exit_three_from_an_external_engine_fails_even_when_advisory(tmp_path):
    # UNREACHABLE is a real defect: configured, and could not read its subject. Skipping it is how
    # a broken check stays invisible, so advisory does not excuse it.
    r, data = _doctor(tmp_path, _ext(tmp_path, rc=3, doctor="advisory"), "--check")
    assert _engines(data)["acme-check"]["state"] == "error"
    assert r.returncode != 0


def test_counts_from_an_external_engine_reach_the_report(tmp_path):
    # --json is why doctor passes flags at all: a participant that only returned an exit code would
    # be a pass/fail lamp in a report that is otherwise made of numbers.
    _, data = _doctor(tmp_path, _ext(tmp_path))
    assert _engines(data)["acme-check"]["summary"] == {"widgets": 3}


def test_an_engine_that_rejects_the_documented_flags_is_an_error_not_a_skip(tmp_path):
    # THE collision. argparse exits 2 for an unrecognised flag and 2 means NOT CONFIGURED, so
    # without this an engine that ignored the contract reports as a tidy skip, its whole subject
    # goes unchecked, and the roll-up stays green.
    r, data = _doctor(tmp_path, _ext(tmp_path, doctor="gate", template=STRICT_ENGINE), "--check")
    assert _engines(data)["acme-check"]["state"] == "error"
    assert r.returncode != 0


def test_a_genuine_not_configured_skip_is_still_a_skip(tmp_path):
    # The negative control for the rule above: a narrow matcher, so an engine that legitimately
    # exits 2 with a quiet stderr keeps being reported as skipped rather than as a failure.
    r, data = _doctor(tmp_path, _ext(tmp_path, rc=2, doctor="gate"), "--check")
    assert _engines(data)["acme-check"]["state"] == "skipped"
    assert r.returncode == 0


def test_an_unknown_participation_level_is_refused(tmp_path):
    # This header decides whether a failure is allowed to be invisible, so it is not guessed at.
    r, _ = _doctor(tmp_path, _ext(tmp_path, doctor="maybe"))
    assert r.returncode != 0
    assert "participation level" in r.stderr


def test_a_relative_engine_path_still_composes(tmp_path):
    """The regression. CI set NEUROKEEPER_ENGINE_PATH=examples/engines, a relative path.

    Discovery returned it unresolved, doctor joined it against its OWN directory, and the resulting
    file did not exist. The interpreter exits 2 when it cannot open a script, 2 already means NOT
    CONFIGURED, so the engine was reported as a tidy skip while nothing ran at all.
    """
    import json
    _ext(tmp_path)
    (tmp_path / "vault").mkdir(exist_ok=True)
    env = dict(os.environ)
    env["VAULT_ROOT"] = "vault"
    env["NEUROKEEPER_ENGINE_PATH"] = "ext"          # relative, resolved against cwd below
    env.pop("CLAUDE_MEMORY_DIR", None)
    env.pop("FRONTMATTER_SCHEMA", None)
    r = subprocess.run([sys.executable, DOCTOR, "--json", "--check"], cwd=str(tmp_path),
                       capture_output=True, text=True, env=env, timeout=180)
    entry = _engines(json.loads(r.stdout))["acme-check"]
    assert entry["state"] == "ok", entry


def test_a_missing_engine_file_is_an_error_not_a_skip(tmp_path):
    """The class of bug behind the regression above, closed at its source.

    Exit 2 from the interpreter ("can't open file") is indistinguishable from exit 2 from an engine
    ("not configured"), so the file is checked before it is run.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_doc", DOCTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rc, out, err = mod._run(str(tmp_path / "no-such-engine.py"), ["--check"])
    assert rc not in (0, 2, 3), f"a missing engine must not land on a skip/pass code, got {rc}"
    assert "not found" in err


def test_doctor_is_unchanged_when_no_engine_path_is_set(tmp_path):
    r, data = _doctor(tmp_path)
    assert data and r.returncode == 0
    assert all(e["origin"] == "built-in" for e in data["engines"] if "origin" in e)
