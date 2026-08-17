#!/usr/bin/env python3
# @capability:  pii-detection
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/_pii.py
# @prompt:      (none)
# @adapters:    import (shared helper)
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         docs/adr-0005-attribute-based-read-gate.md
"""Personal data and secrets in free text: find it, and never quote it back.

Detection vocabulary MAY be published; permission vocabulary never may. These are shapes - an email
address, an IBAN, a private-key header - not a statement about what any site considers sensitive.
That distinction is why this module can live in a public collection while a read policy cannot.

Two properties are load-bearing, and both were learned by running an earlier version over a real
corpus rather than by reasoning about regexes.

VALIDATE, DO NOT JUST MATCH. `\\b[A-Z]{2}\\d{2}[A-Z0-9]{8,}` is a fine description of an IBAN and
also of a hex fragment, a GUID slice and a build identifier. On a real notebook it produced 26 IBAN
hits, of which every sampled one was a hex string; a loose phone pattern matched version strings like
`2024 09 16`. After mod-97 and Luhn checks: IBAN 26 -> 2, card 15 -> 1, and the one genuine
credential stayed visible. An almost-all-noise report teaches its reader to skim past the page that
mattered, so a false positive here is not a harmless extra - it is what makes the true positive
invisible.

SAMPLES COME BACK REDACTED. A report that quotes the personal data it found has moved the problem
into a second file rather than solved it, and that file is usually easier to circulate than the
corpus was. Enough survives to recognise a value; not enough to be it.
"""
import re

# Shapes, not judgements. A site decides what to DO about each class; this only says what is there.
PATTERNS = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b"),

    # Tightened after a real run. The loose international shape matched date ranges and version
    # strings ("2024 09 16") far more often than telephone numbers, so it REQUIRES either an explicit
    # country/trunk prefix or enough digits to be a real subscriber number, and refuses anything
    # sitting next to a date separator. A merely "tightened-looking" pattern is not enough: an
    # earlier draft of this line still matched `2024 09`, because three digit-groups separated by
    # spaces is exactly what a date looks like.
    "phone": re.compile(
        r"(?<![\w/.\-:])(?:\+\d{1,3}[\s.\-]?\(?0?\)?[\s.\-]?\d[\d\s.\-]{6,14}\d"
        r"|\b0\d{1,3}[\s.\-/]\d{2,3}[\s.\-]?\d{2}[\s.\-]?\d{2}\b)(?![\w/\-:])"),

    # PERMISSIVE pattern, strict validator. The division of labour matters and an earlier version
    # got it backwards: it required the body in groups of four, which does reduce false positives
    # and also refuses every IBAN whose length is not a multiple of four plus the prefix. A GB IBAN
    # is 22 characters, so the canonical test value `GB82WEST12345698765432` was not matched at all.
    #
    # Trading a false positive for a false negative is a bad trade HERE specifically: a spurious hit
    # costs a reader a glance, a missed one means personal data ships. So the pattern casts wide and
    # mod-97 below does the deciding.
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9][ ]?){10,30}\b"),
    "card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),

    # Secrets, as opposed to personal data. These are the classes that stop an unattended write.
    # Multilingual on purpose: a corpus is not obliged to label its secrets in English.
    "credential": re.compile(
        r"(?i)\b(?:pass(?:word|wd)|wachtwoord|mot\s*de\s*passe|api[_-]?key|secret|token|"
        r"private[_-]?key)\b\s*[:=]\s*\S{4,}"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
}

# Classes whose presence must stop an unattended write outright, independently of any policy. A
# credential is not a matter of degree: no marking, capability or site posture makes writing one out
# acceptable, so this is deliberately NOT expressed as policy - policy is for judgements, and this
# is not one.
BLOCKING = {"credential", "private_key_block"}


def _luhn_ok(digits: str) -> bool:
    n = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(n) <= 19:
        return False
    total, parity = 0, len(n) % 2
    for i, d in enumerate(n):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_ok(value: str) -> bool:
    """IBAN mod-97. See the module docstring for what happens without it."""
    s = re.sub(r"\s+", "", value).upper()
    if not 15 <= len(s) <= 34 or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    rearranged = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) if c.isalpha() else c for c in rearranged)
    if not digits.isdigit():
        return False
    return int(digits) % 97 == 1


VALIDATORS = {"iban": _iban_ok, "card": _luhn_ok}


def redact(value: str) -> str:
    """Keep enough to recognise the value, not enough to be it."""
    v = (value or "").strip()
    if len(v) <= 4:
        return "*" * len(v)
    return f"{v[:2]}{'*' * min(8, len(v) - 4)}{v[-2:]}"


def scan(text: str, extra=None, cap: int = 5) -> dict:
    """{class: [redacted samples]} for everything personal or secret in `text`.

    `extra` adds site-specific patterns without editing this file, which is how a site adds a
    national identifier shape that has no business in a published module.
    """
    out = {}
    if not text:
        return out
    for name, pat in {**PATTERNS, **(extra or {})}.items():
        validator = VALIDATORS.get(name)
        hits = []
        for m in pat.finditer(text):
            raw = m.group(0)
            if validator and not validator(raw):
                continue
            r = redact(raw)
            if r not in hits:
                hits.append(r)
            if len(hits) >= cap:
                break
        if hits:
            out[name] = hits
    return out


def blocking(found: dict) -> list:
    """Classes present that must stop an unattended write."""
    return sorted(set(found) & BLOCKING)
