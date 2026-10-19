"""A PowerShell function must not share its name with a command it calls.

PowerShell resolves functions before applications and ignores case, so `function Winget($id) { winget install ... }`
called itself until "call depth overflow" (GitHub CI, windows-latest bootstrap job, 2026-10-12). The Windows bootstrap
job only runs on GitHub; this check runs everywhere.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNC = re.compile(r"^\s*function\s+([A-Za-z_][\w-]*)\s*(?:\([^)]*\))?\s*\{(.*)$", re.IGNORECASE)
STRINGS = re.compile(r"'[^']*'|\"[^\"]*\"")   # a name inside a string literal is not a call


def _shadowing(text: str) -> list[str]:
    bad = []
    for line in text.splitlines():
        m = FUNC.match(line)
        if m and re.search(rf"(?<![\w$-]){re.escape(m.group(1))}(?![\w-])", STRINGS.sub('', m.group(2)), re.IGNORECASE):
            bad.append(m.group(1))
    return bad


def test_the_check_catches_the_original_bug():
    assert _shadowing("function Winget($id) { winget install --id $id -e }") == ["Winget"]
    assert _shadowing("function Install-WingetPackage($id) { winget install --id $id -e }") == []
    assert _shadowing("function Pass($n, $d) { Add-Row 'PASS' $n $d }") == []


def test_no_bootstrap_function_calls_a_command_of_its_own_name():
    scripts = sorted((ROOT / "bootstrap").rglob("*.ps1"))
    assert scripts, "no bootstrap scripts found"
    found = {str(p.relative_to(ROOT)): _shadowing(p.read_text(encoding="utf-8")) for p in scripts}
    assert not {k: v for k, v in found.items() if v}
