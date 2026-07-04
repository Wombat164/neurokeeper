# CI adapters: pre-commit hook + GitHub Action

neurokeeper ships two thin adapters so the same engines that run as a Claude Code plugin / CLI also
gate a vault repository in CI. Both are deliberately narrow: they run the **vault-graph-aware**,
deterministic checks neurokeeper uniquely owns and **compose with** the mature ecosystem for everything
else.

## What this gates (and what it does not)

**neurokeeper gates** (no other CI tool does these): broken `[[wikilink]]` resolution, orphans /
dead-ends, **broken `.canvas` / `.base` referential integrity**, name/stem collisions, controlled-vocab
frontmatter (when you supply a schema), and - via `doctor` - an honest aggregate roll-up.

**Compose with the ecosystem** for the commoditized checks (do NOT expect neurokeeper to do them):

| Check | Use |
|---|---|
| Markdown style | [markdownlint-cli2](https://github.com/DavidAnson/markdownlint-cli2-action) |
| External link existence | [lychee](https://github.com/lycheeverse/lychee-action) |
| Frontmatter against JSON Schema | [check-jsonschema](https://github.com/python-jsonschema/check-jsonschema) / [remark-lint-frontmatter-schema](https://github.com/JulianCataldo/remark-lint-frontmatter-schema) |
| `.canvas` structural validity | the [JSON Canvas schema](https://github.com/obsidianmd/jsoncanvas) via check-jsonschema |

## pre-commit hook

In your vault repo's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Wombat164/neurokeeper
    rev: v0.3.0
    hooks:
      - id: neurokeeper-doctor        # aggregate health gate (recommended)
      # - id: neurokeeper-ref-audit   # or just reference integrity
```

pre-commit builds an isolated venv, installs the package, and runs the `neurokeeper` CLI. The engines
scan the repo root (`VAULT_ROOT`). `doctor` **skips** engines whose config is absent - it never
false-fails on an unconfigured check.

## GitHub Action

```yaml
jobs:
  vault:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # commoditized checks - compose with the ecosystem (neurokeeper does not reimplement these):
      - uses: DavidAnson/markdownlint-cli2-action@v16
      - uses: lycheeverse/lychee-action@v2
      # the vault-graph-aware gate neurokeeper uniquely provides:
      - uses: Wombat164/neurokeeper@v0.3.0
        with:
          vault-path: "."
          engine: "doctor"          # or "ref-audit"
          strict: "false"           # "true" also fails on unresolved wikilinks
          frontmatter-schema: ""    # set to enable frontmatter-lint in the doctor run
          memory-dir: ""            # set to enable memory-consolidate in the doctor run
```

The exit code follows [ADR-0002](adr-0002-doctor-exit-semantics.md): it fails on broken `.canvas`/`.base`
refs or an engine error, **not** on advisory findings or skipped (unconfigured) engines. Set
`frontmatter-schema` / `memory-dir` to bring those engines into the gate; leave them empty to skip.
