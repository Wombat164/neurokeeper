# Releasing neurokeeper

## Pre-publish checks

```
python scripts/check-release.py     # offline: versions synced + plugin/marketplace manifests valid
claude plugin validate . --strict   # richer manifest + skill/agent/hook frontmatter check (see note)
```
`check-release.py` also checks the version refs a READER copies (a pre-commit `rev:`, a workflow
`uses:` ref, a status line) across `README.md`, `docs/` and `wiki/content/`, and fails on a stale
one. This exists because the gate once reported "version synced" while seven such refs pointed two
minor versions back: the manifests are read by tooling that fails loudly, the prose is read by
people who copy it and get a silently old toolchain. Prose that merely MENTIONS a version ("fixed
in 0.3.2") is not checked, changelog/ADR/roadmap files are skipped by name, and a single
deliberate line can be exempted with `<!-- pin-ok -->`.

Bump those refs in the same change as the version, and cut the tag before publishing: a ref pinned
to a tag that does not exist yet resolves to nothing, which is a harder failure than an old
release. `check-release.py` prints a NOTE when the docs pin a version with no tag, and does not
fail on it, because bumping docs before tagging is the normal order.

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

> [!note] Distribution name: `neurokeeper` (verified free on PyPI)
> The distribution publishes under its natural name `neurokeeper` (`pyproject.toml` `[project] name`);
> the name is unregistered on PyPI, so no rename is needed. Import package, console command, GitHub
> repo, and plugin name are all `neurokeeper` too. The first published Release claims the name on PyPI,
> so publishing is worthwhile sooner rather than later (an unclaimed name can be squatted).

PyPI publishing uses **Trusted Publishing (OIDC)** - no API tokens are stored. It is **gated off by
default** so releases stay green until you opt in. To enable:

1. **Configure the Trusted Publisher on PyPI** (your PyPI account; one-time):
   - PyPI -> your project (or "pending publisher" if the project doesn't exist yet) -> Publishing ->
     Add a GitHub publisher: owner `Wombat164`, repo `neurokeeper`, workflow `release.yml`,
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

Bump `version` in `pyproject.toml`, `.claude-plugin/plugin.json`, and `neurokeeper/__init__.py`
together (they must match), then tag `vX.Y.Z`.
