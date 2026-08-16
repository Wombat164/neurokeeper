"""Theme-aware quickstart card: the real doctor run on the shipped example vault.

Replaces a single-background GIF that sat as a dark slab on light GitHub. Two SVGs, swapped by a
<picture> element, so the card follows the reader's theme.

The content is the canonical demo from .github/workflows/example-vault.yml, verbatim, with the one
over-long line WRAPPED rather than elided: a real terminal wraps it too, and trimming counters out
of a health report to make a nicer picture would be a lie about what the tool prints.

Monospace makes layout exact: every glyph advances 0.6em, so a column index is a position. Text is
outlined afterwards, so nothing depends on the reader having the font.
"""
import pathlib
import re
import sys

# Derived, never written down. This card read "neurokeeper 0.4.0" while the package was already at
# 0.6.0, because check-release inspects prose pins and cannot see inside a rendered image. The only
# safe version in a demo is one taken from the package at render time.
def _version():
    root = pathlib.Path(__file__).resolve().parents[3]
    m = re.search(r'(?m)^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"))
    return m.group(1) if m else "unknown"


OUT, BG, FG, MUTED, ACCENT, DIM = sys.argv[1:7]

FS = 14.0
CW = FS * 0.6          # true monospace: 600/1000 upm
LEAD = 21.0
PAD_X, PAD_TOP = 26.0, 34.0

# (column, text, role). role: fg | muted | accent | dim
#
# The card shows adoption on a MESSY collection, not a clean one. A clean-vault demo cannot answer
# the objection every prospective user actually has: "I have a decade of mess and this thing will
# shout at me about all of it." The last line is the whole posture in one frame, which is that the
# tool does not punish you for the past and will not let the present get worse.
#
# Every number here is from a real run over a generated 120-note collection with realistic decay,
# not an illustration. Re-run the flow before changing them.
LINES = [
    [(0, "$", "accent"), (2, "neurokeeper ref-audit --check", "fg"),
     (32, "# a collection you inherited", "dim")],
    [(0, "=== VAULT REF AUDIT (120 notes, 120 files) ===", "fg")],
    [(0, "ref-audit OK: 0 broken canvas/base refs (120 notes;", "muted")],
    [(2, "28 unresolved links, orphans 97, dead-ends 75)", "muted")],
    [],
    [(0, "$", "accent"), (2, "neurokeeper ref-audit --write-baseline .nk-baseline.json", "fg")],
    [(0, "ref-audit: wrote", "muted"), (17, "255", "fg"),
     (21, "accepted findings to baseline", "muted")],
    [],
    [(0, "$", "accent"), (2, "neurokeeper ref-audit --baseline .nk-baseline.json --check", "fg")],
    [(2, "adoption:", "fg"), (12, "2 new", "accent"),
     (17, ", 255 baselined, 0 resolved", "muted")],
    [],
    [(0, "# the backlog is visible and yours to clear.", "dim")],
    [(0, "# only the 2 you just introduced gate the commit.", "dim")],
]

ROLE = {"fg": FG, "muted": MUTED, "accent": ACCENT, "dim": DIM}

cols = max((c + len(t) for line in LINES for c, t, _ in line), default=0)
W = round(PAD_X * 2 + cols * CW)
H = round(PAD_TOP + len(LINES) * LEAD + PAD_TOP - 10)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" '
    f'aria-label="Terminal: neurokeeper doctor --check on the example vault, roll-up OK">',
    "  <title>neurokeeper doctor --check</title>",
    f'  <rect width="{W}" height="{H}" rx="12" fill="{BG}"/>',
]
for i, line in enumerate(LINES):
    y = PAD_TOP + (i + 1) * LEAD - 6
    for col, text, role in line:
        x = PAD_X + col * CW
        parts.append(
            f'  <text x="{x:.1f}" y="{y:.1f}" font-family="mono" font-size="{FS:g}" '
            f'fill="{ROLE[role]}" xml:space="preserve">{esc(text)}</text>')
parts.append("</svg>")

open(OUT, "w", encoding="utf-8").write("\n".join(parts) + "\n")
print(f"  wrote {OUT}  ({W}x{H}, {cols} columns, {len(LINES)} lines)")
