#!/usr/bin/env python3
# @capability:  register-lib
# @portability: L1a-generic
# @status:      library
"""Shared loader for the identifier register (ADR-0005).

One file, three consumers: the conformance lint, the author-time guard, and correlate's parent
inheritance. This module owns loading, validation and the provenance rules, so the three cannot
drift into disagreeing about what an entry means.

The provenance rules are here rather than in each consumer on purpose. `source` is the LIMIT ON
ENFORCEMENT, and a limit re-implemented three times is a limit that will be applied twice.
"""
import os

try:
    import yaml
except ImportError:                                     # pragma: no cover
    yaml = None

SOURCES = ("decided", "harvested", "inferred")

# What each provenance class permits. Read these as a single table rather than as scattered ifs:
#   enforce  may a guard BLOCK on it
#   fix      may a fixer rewrite a document toward it
#   assert_  may a message state the document is wrong, rather than hedging toward the register
ENFORCEMENT = {
    "decided":   {"enforce": True,  "fix": True,  "assert_": True},
    "harvested": {"enforce": True,  "fix": False, "assert_": False},
    "inferred":  {"enforce": False, "fix": False, "assert_": False},
}


class RegisterError(Exception):
    """The register was named and could not be used. Never swallowed into an empty register."""


def register_path():
    return os.environ.get("IDENTIFIER_REGISTER", "")


class Register:
    def __init__(self, data, path):
        self.path = path
        self.tiers = list(data.get("tiers") or [])
        self.tier_fields = dict(data.get("tier_fields") or {})
        self.entities = {}
        self.alias_to_id = {}
        raw = data.get("entities") or {}
        if not isinstance(raw, dict):
            raise RegisterError("entities: must be a mapping of identifier -> {tier, source, ...}")
        for ident, body in raw.items():
            body = body or {}
            src = body.get("source")
            if src not in SOURCES:
                raise RegisterError(
                    f"entity {ident!r}: source must be one of {', '.join(SOURCES)}, got {src!r}. "
                    f"Provenance is the limit on enforcement (ADR-0005), so an entry without it "
                    f"cannot be weighted and is refused rather than assumed decided.")
            tier = body.get("tier")
            if self.tiers and tier not in self.tiers:
                raise RegisterError(f"entity {ident!r}: tier {tier!r} is not in the declared tiers "
                                    f"{self.tiers}")
            self.entities[str(ident)] = {"tier": tier, "source": src,
                                         "aliases": list(body.get("aliases") or [])}
            for a in self.entities[str(ident)]["aliases"]:
                self.alias_to_id[str(a).lower()] = str(ident)
        self.edges = []
        for e in data.get("edges") or []:
            if not all(k in e for k in ("from", "type", "to")):
                raise RegisterError(f"edge {e!r}: needs from, type and to")
            self.edges.append({"from": str(e["from"]), "type": str(e["type"]), "to": str(e["to"])})

    # --- lookup ---------------------------------------------------------------------------------

    def resolve(self, value):
        """Return (identifier, how) for a raw value: exact, alias, or (None, None)."""
        v = str(value).strip()
        if v in self.entities:
            return v, "exact"
        hit = self.alias_to_id.get(v.lower())
        if hit:
            return hit, "alias"
        return None, None

    def parents(self, ident):
        """Ancestors of `ident` following `parent` edges, nearest first. Cycle-safe."""
        out, seen, cur = [], {ident}, ident
        while True:
            nxt = next((e["to"] for e in self.edges
                        if e["type"] == "parent" and e["from"] == cur), None)
            if not nxt or nxt in seen:
                return out
            out.append(nxt)
            seen.add(nxt)
            cur = nxt

    # --- provenance -----------------------------------------------------------------------------

    def rules(self, ident):
        ent = self.entities.get(ident)
        return ENFORCEMENT.get((ent or {}).get("source", "inferred"), ENFORCEMENT["inferred"])

    def phrase(self, ident):
        """How a message about this entry should be worded.

        A `harvested` entry may be wrong about the world: it was typed by rule from what the
        collection already contained. Asserting that the DOCUMENT is wrong, when the register is the
        weaker party, is how a register stops being questioned and starts being obeyed.
        """
        src = (self.entities.get(ident) or {}).get("source", "inferred")
        if src == "decided":
            return "the register says"
        if src == "harvested":
            return "the register (harvested, so possibly wrong here) suggests"
        return "the register (inferred by a tool, never enforced) guesses"


def load(path=None):
    """Load the register, or raise. Absent config is the caller's business, not a silent empty one."""
    p = path or register_path()
    if not p:
        raise RegisterError("IDENTIFIER_REGISTER is not set")
    if yaml is None:
        raise RegisterError("pyyaml is required to read an identifier register")
    if not os.path.isfile(p):
        raise RegisterError(
            f"register named but not found at {p}. This is an error rather than an empty register: "
            f"a scan against nothing reports zero findings, and zero findings reads as conformant.")
    try:
        data = yaml.safe_load(open(p, encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise RegisterError(f"register at {p} could not be read: {e}")
    return Register(data, p)
