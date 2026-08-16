# Example vault (synthetic)

A tiny, **fully synthetic** Obsidian-style vault used to demo the engines and as the CI smoke-test
fixture. Nothing here is real content -- it exists only to exercise the tools. From this directory:

```bash
VAULT_ROOT="$(pwd)" neurokeeper doctor
VAULT_ROOT="$(pwd)" neurokeeper ref-audit --json
```

`doctor --check` exits 0 on this vault. The one unresolved link (`[[future-idea]]` in
`02 - Projects/sample-project.md`) is an intentional Obsidian forward-reference -- `ref-audit` reports it
but does not treat it as an error (see the docs on why unresolved wikilinks are informational).

## The plugin seam

`../engines/` holds a worked **external** engine, standing in for one that lives in somebody else's
repository. It is not part of the core and is not installed with it; the notes here carry an `owner`
field it checks against a roster, which is precisely the kind of local vocabulary the portable core
refuses to carry.

```bash
export VAULT_ROOT="$(pwd)"
export NEUROKEEPER_ENGINE_PATH="$(cd ../engines && pwd)"
export OWNER_ROSTER="$NEUROKEEPER_ENGINE_PATH/roster.txt"

neurokeeper --list                       # acme-owner-audit appears, with its source directory
neurokeeper acme-owner-audit --check     # exit 0: every owner here is on the roster
neurokeeper doctor --check --json        # and it appears in the roll-up, tagged origin: external
```

To watch it fire, comment out `grace.hopper` in `../engines/roster.txt` and run the `--check` again:
it exits 1 and names the note. CI runs both directions on every push, because a detector only ever
observed passing is not known to detect anything.
