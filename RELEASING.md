# Releasing claude-harness

## Pre-publish checks

```
python scripts/check-release.py     # offline: versions synced + plugin/marketplace manifests valid
claude plugin validate . --strict   # richer manifest + skill/agent/hook frontmatter check (see note)
```
`check-release.py` runs in CI (`ci` -> `release manifests` job) on every push, so version drift or a
malformed `plugin.json`/`marketplace.json` fails the build. `claude plugin validate --strict` is a
**manual pre-publish step** (it may require a logged-in Claude CLI, so it is deliberately NOT in CI);
run it locally before tagging. Validate both scopes: the repo root (the marketplace) and the plugin dir.

## Cut a release (GitHub)

```
git tag vX.Y.Z && git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."
```
This publishes the GitHub Release. CI (`ci`) runs on the tag; the wiki redeploys on any `wiki/**` change.

## Publish to PyPI (one-time setup, then automatic)

PyPI publishing uses **Trusted Publishing (OIDC)** -- no API tokens are stored. It is **gated off by
default** so releases stay green until you opt in. To enable:

1. **Configure the Trusted Publisher on PyPI** (your PyPI account; one-time):
   - PyPI -> your project (or "pending publisher" if the project doesn't exist yet) -> Publishing ->
     Add a GitHub publisher: owner `Wombat164`, repo `claude-harness`, workflow `release.yml`,
     environment `pypi`.
   - Docs: https://docs.pypi.org/trusted-publishers/
2. **Create + protect the `pypi` environment FIRST (precondition, not optional):** Settings ->
   Environments -> new environment `pypi` -> require a reviewer. Do this BEFORE step 3, so the first
   PyPI publish cannot fire without a human approval (OIDC trusted-publishing is otherwise fully
   automatic on a published Release).
3. **Then opt in:** Settings -> Secrets and variables -> Actions -> Variables -> add `PYPI_ENABLE` = `true`.

Also recommended once, in this repo: protect `main` (Settings -> Rules/Branches: block force-push +
deletion, require the `ci` checks) and install the OPSEC pre-push guard:
`cp bootstrap/hooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push`.

After that, every published GitHub Release runs `release.yml`, builds the wheel/sdist, and publishes to
PyPI via OIDC. Until `PYPI_ENABLE=true`, the PyPI job is skipped (the release is GitHub-only).

## GitHub Pages (wiki)

Pages is served from the `deploy-wiki.yml` workflow (Settings -> Pages -> Source = GitHub Actions). It
redeploys automatically on pushes that touch `wiki/**`. Manual: `gh workflow run deploy-wiki.yml`.

## Versioning

Bump `version` in `pyproject.toml`, `.claude-plugin/plugin.json`, and `claude_harness/__init__.py`
together (they must match), then tag `vX.Y.Z`.
