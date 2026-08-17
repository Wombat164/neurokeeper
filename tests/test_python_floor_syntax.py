"""The advertised Python floor must be checkable on the interpreter you happen to be running.

`X | None` in a signature is evaluated at import time and raises TypeError below Python 3.10. This
package advertises 3.9. The break is invisible on a newer local interpreter, so it passed the local
suite, passed the reviewer, and was caught only by the 3.9 row of the CI matrix -- after a release
had been cut from it.

A rule that only one machine in the fleet can check is not a rule anyone can follow. These tests run
the check as an AST walk, so they fail on 3.14 exactly as they would on 3.9.
"""
import ast
import os
import re

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR = (3, 9)


def _floor_from_pyproject():
    """The floor is read, never hard-coded: raise requires-python and this test follows."""
    path = os.path.join(HARNESS, "pyproject.toml")
    if not os.path.isfile(path):
        return FLOOR
    m = re.search(r'requires-python\s*=\s*"[^0-9]*(\d+)\.(\d+)', open(path, encoding="utf-8").read())
    return (int(m.group(1)), int(m.group(2))) if m else FLOOR


def _sources():
    for root, dirs, files in os.walk(HARNESS):
        dirs[:] = [d for d in dirs
                   if d not in {".git", ".venv", "node_modules", "__pycache__", "build", "dist"}]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def _pep604_offenders(path):
    """Runtime-evaluated `X | Y` annotations in a module without `from __future__ import annotations`.

    Only ANNOTATIONS are reported. `a | b` on values is ordinary set/int arithmetic and is fine on
    every version; flagging it would make the gate noisy and therefore ignorable.
    """
    src = open(path, encoding="utf-8", errors="replace").read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []                       # a deliberately-broken fixture; not this test's subject
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(a.name == "annotations" for a in node.names):
                return []
    hits = []

    def scan(annotation, lineno):
        if annotation is None:
            return
        for sub in ast.walk(annotation):
            if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                hits.append(lineno)
                return

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scan(node.returns, node.lineno)
            a = node.args
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]:
                if arg is not None:
                    scan(arg.annotation, arg.lineno)
        elif isinstance(node, ast.AnnAssign):
            scan(node.annotation, node.lineno)
    return sorted(set(hits))


def test_no_pep604_annotations_without_the_future_import():
    floor = _floor_from_pyproject()
    if floor >= (3, 10):
        pytest.skip(f"floor is {floor[0]}.{floor[1]}; PEP 604 is native there")
    bad = {}
    for path in _sources():
        lines = _pep604_offenders(path)
        if lines:
            bad[os.path.relpath(path, HARNESS)] = lines
    assert not bad, (
        f"`X | Y` annotations evaluated at import, in modules without `from __future__ import "
        f"annotations`, on a package whose floor is {floor[0]}.{floor[1]}: {bad}. These raise "
        f"TypeError on import below 3.10 and are invisible on a newer interpreter.")


def test_the_check_can_actually_fail(tmp_path):
    """A gate never observed to fire is indistinguishable from one that cannot."""
    offender = tmp_path / "offender.py"
    offender.write_text("def f(x: int | None = None) -> str | None:\n    return None\n",
                        encoding="utf-8")
    assert _pep604_offenders(str(offender)) == [1]

    excused = tmp_path / "excused.py"
    excused.write_text("from __future__ import annotations\n"
                       "def f(x: int | None = None) -> str | None:\n    return None\n",
                       encoding="utf-8")
    assert _pep604_offenders(str(excused)) == []

    # Value-level `|` is not an annotation and must not be reported, or the gate becomes noise.
    values = tmp_path / "values.py"
    values.write_text("def f(a, b):\n    return a | b\n", encoding="utf-8")
    assert _pep604_offenders(str(values)) == []


def test_every_source_file_compiles():
    """Cheap backstop: a syntax error anywhere is caught here rather than at someone's import."""
    broken = []
    for path in _sources():
        src = open(path, encoding="utf-8", errors="replace").read()
        try:
            compile(src, path, "exec")
        except SyntaxError as e:
            broken.append(f"{os.path.relpath(path, HARNESS)}:{e.lineno}: {e.msg}")
    assert not broken, f"files that do not compile: {broken}"
