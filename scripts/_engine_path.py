"""Discovery of engines that live outside this repository.

ONE implementation, imported by both callers. The dispatcher needs it to resolve a name, and doctor
needs it to compose the roll-up; two copies of a search path is the shape where one caller learns
about an engine and the other does not, and the disagreement is silent.

The directory IS the manifest. A separate index file would be a second surface that drifts, and a
stale name-to-path entry is precisely the failure P9 exists to catch.
"""
import os

ENGINE_PATH_VAR = "NEUROKEEPER_ENGINE_PATH"
HEADER_BYTES = 2048          # headers are a preamble; do not read whole files to find them


def header(path, key):
    """The value of a `# @<key>:` header line, or None. Cheap, tolerant of encoding damage."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(HEADER_BYTES)
    except OSError:
        return None
    for line in head.splitlines():
        s = line.strip()
        if s.startswith("#") and f"@{key}:" in s:
            return s.split(f"@{key}:", 1)[1].strip() or None
    return None


def discover():
    """{name: (script_path, source_dir)} for every engine on the search path.

    Only files carrying an @capability header register, so a helper module sitting beside an engine
    is not mistaken for one, and a directory of ordinary Python is not silently turned into a CLI.
    """
    raw = os.environ.get(ENGINE_PATH_VAR, "")
    found = {}
    if not raw:
        return found
    for raw_entry in raw.split(os.pathsep):
        raw_entry = raw_entry.strip()
        if not raw_entry:
            continue
        # Resolved ONCE, here. A relative entry is legitimate (CI writes `examples/engines`), but a
        # relative RESULT is not: every consumer joins it against its own directory, and doctor did
        # exactly that, producing a path under scripts/ that did not exist.
        entry = os.path.abspath(raw_entry)
        if not os.path.isdir(entry):
            # Loud, not skipped. A path that does not resolve would otherwise mean "your engines
            # silently vanished", and an empty result reads as "you have none" rather than "your
            # configuration is wrong" (P1).
            resolved = f" (resolved to {entry})" if entry != raw_entry else ""
            raise SystemExit(
                f"neurokeeper: {ENGINE_PATH_VAR} names a directory that does not exist: "
                f"{raw_entry}{resolved}\n"
                f"  Fix the path or unset the variable. Continuing would report your external "
                f"engines as absent rather than as misconfigured.")
        for fn in sorted(os.listdir(entry)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            p = os.path.join(entry, fn)
            if header(p, "capability") is None:
                continue
            found[os.path.splitext(fn)[0]] = (p, entry)
    return found


def doctor_participants():
    """External engines that opted into the doctor roll-up, as (name, path, gates).

    Opt-IN, never automatic. Being on the search path means "dispatchable", not "run this whenever
    someone asks about the health of my collection": an engine that is slow, or that talks to a
    network, or that answers a different question entirely, must not be conscripted into a report
    the operator reads as a health summary.

    `# @doctor: gate` may fail the roll-up. `# @doctor: advisory` contributes its state and cannot.
    Anything else in that header is refused rather than guessed at, because guessing here decides
    whether a failure is allowed to be invisible.
    """
    out = []
    for name, (path, _src) in sorted(discover().items()):
        raw = header(path, "doctor")
        if raw is None:
            continue
        value = raw.split("#", 1)[0].strip().lower()
        if value in ("no", "none", "off"):
            continue
        if value not in ("gate", "advisory"):
            raise SystemExit(
                f"neurokeeper: engine '{name}' declares '@doctor: {raw}', which is not a known "
                f"participation level.\n  Use 'gate' (may fail the roll-up), 'advisory' (reports "
                f"only), or 'no'. Refusing rather than guessing: this header decides whether a "
                f"failure in your engine is allowed to be invisible.\n  {path}")
        out.append((name, path, value == "gate"))
    return out
