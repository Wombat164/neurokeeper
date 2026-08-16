# ADR-0004: the substrate boundary, and what this project refuses to absorb

Status: accepted, 2026-08-16.

## Context

The engines here keep growing into adjacent ground. Each step is individually reasonable: an engine
needs to know whether its input was backed up, so it learns about remotes; it learns about remotes,
so it wants to know whether the backup job ran; it wants to know about jobs, so it starts reading
schedulers. Three defensible steps and the project is now a machine-management tool competing with
mature ones, badly.

Research makes this worse rather than better, because it surfaces genuine gaps. A survey of the
landscape found several underserved areas, all real. **A named market gap is not a mandate.**
Identifying three things nobody does well is a reason to pick one, not permission to take all three.

So the edge has to be written down, including the refusals, because the next enthusiastic session
will otherwise re-derive each of them as a good idea.

## Decision

**The boundary is the knowledge substrate, not the machine.**

In scope, because it is the substrate:

- the collection's content, and its structure, naming and references;
- its configuration, treated as code with a declared schema;
- the agent memory store beside it;
- the contracts these declare (schemas, registers, vocabularies, manifests);
- their **durability channels**: tracked or deliberately ignored, backed up, pushed, and which copy
  is canonical.

Out of scope, and each is a refusal rather than an omission:

**No OS or machine provisioning.** Installing tools, managing packages, configuring a host. Solved
by chezmoi, Ansible, Nix, winget and their peers, all of which are better at it than anything that
could be added here.

**No generic developer-machine drift detection.** Tempting because `custody-audit` looks adjacent to
it, and it is a different product with no nouns in common. Custody asks whether a DECLARED artifact
of the substrate is kept. It does not ask whether your machine matches a fleet baseline.

**No network fetch inside an engine.** This one is structural rather than a matter of taste. The
CI-gate positioning depends on engines being deterministic and offline: same input, same verdict,
no third party's availability in the loop. An engine that fetches can fail for reasons that have
nothing to do with the collection, and a gate that fails for unrelated reasons is a gate that gets
bypassed. Link liveness is genuinely useful and belongs to a tool that already does it well, run
beside these rather than inside them.

**No scheduler introspection.** Jobs report by writing a receipt; engines check receipt freshness.
Reading systemd, cron and Task Scheduler means three platforms, three failure modes and no
determinism, in exchange for information a receipt carries better. It also sidesteps a specific
trap: a unit that reports failed every night while the half that mattered succeeds throughout, at
which point a permanently red signal is indistinguishable from a real one.

**No embedding or model-scored similarity in the core.** Where a task genuinely needs judgment, the
deterministic part narrows the input and states what it narrowed, and the judgment happens behind a
gate with the evidence attached. The core stays reproducible.

## Consequences

The refusals are the useful half. Anyone can list what a tool does; the list of what it will not do
is what keeps its verdicts trustworthy, because every one of the refusals above protects either
determinism or scope.

`custody-audit` sits closest to the edge and stays inside it by asking only about declared
artifacts. If it ever grows a question that is true of a machine rather than of a collection, that
is the signal it has crossed.

The boundary is a claim about identity, not about difficulty. Everything refused here is
straightforward to build. That is precisely why the line has to be written down.
