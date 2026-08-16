"""The stable import surface for engines that live outside this repository.

An external engine must not import from `scripts/_vault_lib.py` and friends directly. Those are
private, they move, and a consumer pinned to them breaks on an ordinary refactor. Worse, the common
alternative is re-implementing the helpers, and divergent copies of frontmatter parsing or a
markdown walk are exactly how two tools come to disagree about the same note.

So this module re-exports a small, deliberately boring surface, and that surface is a promise: names
and signatures here change only with a major version. Everything else, in particular every module
whose name begins with an underscore, is internal and may change in a patch release.

    from neurokeeper.lib import md_files, parse_frontmatter, safe_write

See the how-to "Extend with your own engine" for the contract an external engine meets, and for why
its config never lives in this repository.
"""
import os
import sys

# The helpers live beside the engines: in a repo checkout that is ../scripts, and in a built wheel
# they are force-included under neurokeeper/_engines/ (see pyproject). Resolve the same way the
# dispatcher does rather than assuming a layout, so an editable install and a wheel behave alike.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(_HERE, "_engines"), os.path.join(os.path.dirname(_HERE), "scripts")):
    if os.path.isdir(_cand):
        if _cand not in sys.path:
            sys.path.insert(0, _cand)
        break
else:  # pragma: no cover
    raise ImportError(
        "neurokeeper.lib: cannot find the engine helpers (expected _engines/ or ../scripts/). "
        "An installed package should always have one; a source checkout needs scripts/ present.")

from _vault_lib import (  # noqa: E402
    VAULT,
    force_utf8_stdout,
    kebabify,
    md_files,
    parse_frontmatter,
    split_frontmatter,
)

# Guarded imports: these come from modules that exist in every supported layout, but an external
# engine importing a name that is absent should hear WHY rather than get an opaque ImportError.
try:  # noqa: SIM105
    from _vault_lib import in_forbidden_zone, safe_write, within_vault  # noqa: E402
except ImportError:  # pragma: no cover
    safe_write = within_vault = in_forbidden_zone = None

try:
    from _findings import Finding, to_sarif  # noqa: E402
except ImportError:  # pragma: no cover
    Finding = to_sarif = None

__all__ = [
    # walking and reading a collection
    "VAULT", "md_files", "split_frontmatter", "parse_frontmatter",
    # naming
    "kebabify",
    # writing safely, for engines that mutate on --apply
    "within_vault", "safe_write", "in_forbidden_zone",
    # reporting
    "Finding", "to_sarif",
    # platform
    "force_utf8_stdout",
]


def find_links(text):
    """Wikilinks in `text`, through the collection's configured backend.

    Exposed as a function rather than re-exporting the backend object, because the backend seam is
    still marked experimental: routing through here means a change there does not break every
    external engine that wanted to read links.
    """
    from _backend import get_backend
    return get_backend().find_links(text)
