"""`neurokeeper.lib` is the surface external engines are TOLD to import. It must be documented.

The wiki-coverage gate checks CLI flags, which left this uncovered: the how-to lists the helpers an
external author may rely on, and when the library gained a frontmatter writer the page kept listing
the old set. A contract page that silently omits half a contract is worse than no page, because an
author reads it and concludes the capability does not exist.

This is the flag gate applied one level up, to the importable surface.
"""
import os
import re

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOWTO = os.path.join(HARNESS, "wiki", "content", "how-to", "extend-with-your-own-engine.md")


def _documented():
    if not os.path.isfile(HOWTO):
        pytest.skip("how-to page not present in this checkout")
    # Line-based, NOT a non-greedy regex to the first ")": the comments in that block contain
    # parentheses, so `(.*?)\)` truncated the capture at the first commented "(abspath, reldir)"
    # and reported every later name as undocumented. The gate then failed for a reason that had
    # nothing to do with the docs, which is how a gate gets disabled.
    lines = open(HOWTO, encoding="utf-8").read().splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if "from neurokeeper.lib import (" in ln)
    except StopIteration:
        raise AssertionError("the how-to no longer shows the import block it is built around")
    names = set()
    for ln in lines[start + 1:]:
        if ln.strip().startswith(")"):
            break
        # A line may carry several names before its comment: "Finding, to_sarif,   # ..."
        code = ln.split("#", 1)[0]
        names.update(re.findall(r"([A-Za-z_][\w]*)\s*,", code))
    return names


def test_every_exported_name_is_documented():
    from neurokeeper.lib import __all__
    missing = sorted(set(__all__) - _documented())
    assert not missing, (
        f"exported by neurokeeper.lib and absent from the how-to: {missing}. An external author "
        f"reads that page to learn what they may rely on; a name missing from it is a capability "
        f"they will re-implement.")


def test_nothing_documented_has_since_disappeared():
    """The other direction, which matters more.

    A name promised on the contract page and no longer exported is an ImportError in somebody
    else's repository, and they find out at runtime.
    """
    import neurokeeper.lib as lib
    phantom = sorted(n for n in _documented() if not hasattr(lib, n))
    assert not phantom, (
        f"promised by the how-to and NOT importable: {phantom}. This is an ImportError in a "
        f"consumer's repository, discovered at their runtime rather than in our tests.")


def test_the_documented_names_actually_import():
    # Belt and braces: hasattr passes for a name bound to None, which an optional import can leave.
    import neurokeeper.lib as lib
    for name in sorted(_documented()):
        assert getattr(lib, name, None) is not None, f"{name} is exported but bound to None"
