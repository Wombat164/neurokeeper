"""Layered configuration: engine defaults with a site config merged over them.

Every engine here ships defaults and lets a site override them, and each one had grown its own way
of doing it. This is the shared mechanism. It contains no vocabulary and knows nothing about what is
being configured; a caller passes its defaults, the parsed section, and a NAME for where that
section came from.

Two rules run through all of it.

ADDITIVE BY DEFAULT. A site config extends the built-ins rather than replacing them, because the
common intent is "also match this", and a merge that silently discarded the defaults would quietly
disable checks the engine advertises. Replacement is available and has to be asked for.

EVERY COMPLAINT NAMES ITS KEY. `where` is threaded through every function for one reason: a bad
regex or an unknown key reported without the config location sends the reader to search a file for
a value they cannot see. "bad regex" is a fact; "in people.members.vip: bad regex" is actionable.
That parameter, tedious as it is at every call site, is the whole design.

The failure this exists to prevent is a typo'd section that silently does nothing. A config that is
read, ignored and never mentioned is indistinguishable from a config that worked, and the operator
finds out when the rule they wrote never fires.
"""
import re
from pathlib import Path


class ConfigError(Exception):
    """A config the operator must fix. Always names the offending location."""


def compile_pattern(pattern, where):
    """Compile a regex with the config location named in the error.

    A bad regex must say WHICH key. Without it the operator gets a traceback quoting a pattern and
    has to find it themselves in a file that may hold dozens.
    """
    try:
        return re.compile(pattern, re.I)
    except re.error as exc:
        raise ConfigError(f"in {where}: bad regex {pattern!r} -> {exc}") from exc


def load_yaml(path, known_sections, strict=False):
    """Read and structurally validate a YAML config. Returns (raw, notes).

    An unknown section is REPORTED rather than ignored. A typo'd section that silently does nothing
    is the classic config failure: the file parses, the engine runs, the rule never fires, and
    nothing anywhere says why. `strict` promotes it from a note to a refusal.

    An absent config is not an error, and says so in the notes rather than in silence: "no site
    config" and "your config was ignored" look identical from the outside otherwise.
    """
    notes = []
    if path is None or not Path(path).exists():
        return {}, ["no site config; using built-in defaults only"]
    try:
        import yaml
    except ImportError as exc:
        raise ConfigError(
            "a config file exists but pyyaml is not installed. pip install pyyaml") from exc
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - any parse failure is the operator's to fix
        raise ConfigError(f"{path} is not valid YAML -> {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must be a YAML mapping at the top level")
    unknown = set(raw) - set(known_sections)
    if unknown:
        msg = f"unknown config section(s): {', '.join(sorted(unknown))}"
        if strict:
            raise ConfigError(msg)
        notes.append(f"WARNING: {msg} (ignored)")
    notes.append(f"loaded {path}")
    return raw, notes


def merge_named_patterns(defaults, section, where):
    """Merge a `{name: regex}` section over a list of `(name, pattern)` defaults.

    Returns (merged, note). A config entry whose name already exists OVERRIDES that default; a new
    name is added; `replace: true` discards the defaults entirely.

    Named rather than positional, so an override is explicit about which default it replaces. With a
    bare list a site adding one pattern would either append blindly or clobber everything, and
    neither is what "I want to also match this" means.
    """
    if not section:
        return defaults, ""
    extra = [(k, compile_pattern(v, f"{where}.{k}")) for k, v in section.items() if k != "replace"]
    if section.get("replace"):
        return extra, f"{where} REPLACED with {len(extra)} from config"
    names = {k for k, _ in extra}
    merged = extra + [p for p in defaults if p[0] not in names]
    known = {k for k, _ in defaults}
    return merged, (f"{where} extended (+{len([k for k in names if k not in known])} new, "
                    f"{len([k for k in names if k in known])} overridden)")


def merge_regex_union(default, patterns, replace, where):
    """Union extra alternatives onto one built-in pattern. Returns (pattern, note)."""
    if not patterns:
        return default, ""
    joined = "|".join(patterns)
    merged = compile_pattern(joined if replace else f"{default.pattern}|{joined}", where)
    return merged, f"{where} {'REPLACED' if replace else 'extended'} (+{len(patterns)})"


def merge_scalars(defaults, section, where, strict=False):
    """Override numeric defaults in place, reporting unknown keys. Returns notes.

    Unknown keys are reported for the same reason unknown sections are: a mistyped weight that is
    silently dropped leaves an operator convinced they have tuned something.
    """
    notes = []
    for key, val in (section or {}).items():
        if key not in defaults:
            msg = f"unknown {where} key {key!r}"
            if strict:
                raise ConfigError(msg)
            notes.append(f"WARNING: {msg} (ignored)")
            continue
        defaults[key] = int(val)
    return notes
