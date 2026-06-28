# Example vault (synthetic)

A tiny, **fully synthetic** Obsidian-style vault used to demo the engines and as the CI smoke-test
fixture. Nothing here is real content -- it exists only to exercise the tools. From this directory:

```bash
VAULT_ROOT="$(pwd)" claude-harness doctor
VAULT_ROOT="$(pwd)" claude-harness ref-audit --json
```

`doctor --check` exits 0 on this vault. The one unresolved link (`[[future-idea]]` in
`02 - Projects/sample-project.md`) is an intentional Obsidian forward-reference -- `ref-audit` reports it
but does not treat it as an error (see the docs on why unresolved wikilinks are informational).
