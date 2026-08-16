# ADR-0005: one identifier register, and provenance as the limit on enforcement

Status: accepted, 2026-08-16. Supersedes nothing; scopes issues #21, #22, #23 and #25 into one
artifact and three consumers.

## Context

Identifiers in a knowledge base carry categories that live only in people's heads. The same code
appears under four different field names across years of notes, aliases proliferate, two identifiers
get packed into one value, and nothing detects any of it, because structural validation asks whether
a field is KNOWN and never whether its value is THE RIGHT KIND OF THING.

Four issues arrived at this from different directions: correlate losing signal because identifiers
are treated as flat tokens (#21), a conformance lint that structural validation cannot express
(#22), provenance weighting (#23), and the register artifact itself (#25).

Building them separately would produce four config formats for one idea, and the fourth author
would inherit three incompatible ones. So the shape is decided once, here, before any of it is
written.

## Decision 1: one register, three consumers

A single optional file, declared through `IDENTIFIER_REGISTER`, holding entities, their aliases,
their provenance, and typed edges between them.

```yaml
entities:
  ALPHA:      {tier: vehicle,   source: decided,   aliases: [alpha-programme]}
  ALPHA-REQ:  {tier: request,   source: harvested}
  2026-AG-4:  {tier: agreement, source: harvested}
  ACME-DATA:  {tier: platform,  source: inferred}
edges:
  - {from: ALPHA-REQ, type: parent, to: ALPHA}
  - {from: 2026-AG-4, type: parent, to: ALPHA-REQ}
```

Three consumers read it and each owns exactly one job:

| consumer | job | may it enforce? |
|---|---|---|
| `register-lint` | whole-collection conformance report | no, report only |
| the author-time guard | the document being written, diff-scoped | yes, on changed lines |
| `correlate` | inherit a parent's matches down an edge | not applicable, it scores |

The split matters because the lint and the guard answer different questions. The lint asks "what is
the state of this collection", which is an inventory and must never block. The guard asks "does what
you just wrote conform", which can block, because it concerns a change in flight rather than
inherited history.

## Decision 2: the tiers are the collection's, not ours

`tier` values are arbitrary strings the collection defines. Shipping a fixed vocabulary would encode
one organisation's shape into a domain-neutral tool, which ADR-0004 rules out. The register declares
its own tiers and the engines only check consistency against them.

## Decision 3: provenance is the limit on enforcement, not metadata

Every entry carries a `source` of `decided`, `harvested` or `inferred`, and this is the load-bearing
decision of the whole design.

A register is always authored three ways at once: partly from explicit decisions, partly by rule
from what the collection already contains, and partly by a tool inferring a name that looked right.
Once tooling ENFORCES the register, those three become indistinguishable, and an entry nobody ever
confirmed gates writes with exactly the authority of one a person stated.

So consumers weight by it:

- **`decided`**: a human stated it. A conformance failure is a real finding, reported plainly.
- **`harvested`**: read from existing metadata and typed by rule. A failure may mean the REGISTER is
  wrong rather than the document, and the message says so instead of asserting.
- **`inferred`**: a tool named it, unconfirmed. **Never enforced.** Reported, never blocking, and
  never used by the fixer.

The measured distribution on a real register of about 140 entries was 36 decided, 74 harvested, 2
inferred. The harvested majority is simultaneously the weakest class and the one enforcement would
hit hardest, which is the entire argument for not treating them alike.

The failure this prevents is specific and bad: a name a tool invented becomes canonical purely by
being the only spelling that passes a check. At that point the tool has started writing reality
rather than describing it, and the register has become a source of truth about nothing.

This is the second half of the project invariant, applied to a data structure: no enforcement
stronger than its mandate.

## Decision 4: the fixer only touches `decided`

A gated fixer may rewrite a value to the canonical spelling only where the register entry is
`decided`. Rewriting toward a `harvested` or `inferred` entry would launder a guess into the
collection's text, where the next harvest reads it back as evidence and the loop closes with nobody
having decided anything.

## Decision 5: the guard is diff-aware, and that is not a nicety

Applying a new register to a mature collection produces hundreds of findings on day one. A reader
ignores three hundred stale ones to reach the one that is theirs, then stops reading, and the
documented outcome is that the check gets switched off. The guard reports findings on changed lines
in full and collapses untouched ones to a count, exactly as `--staged` does for references.

## Consequences

The register is optional. Without `IDENTIFIER_REGISTER` every consumer skips, and nothing about the
existing engines changes.

`inferred` entries are close to inert by design: reported, never enforced, never fixed. That is
correct rather than wasteful. They exist so that a tool's guess is VISIBLE as a guess instead of
being quietly promoted by the only mechanism that ever looks at it.

The hardest part to keep honest over time is the boundary between `harvested` and `decided`.
Anything that promotes an entry between them has to be a deliberate human act with a record, or the
distinction decays into decoration and the enforcement limit decays with it.
