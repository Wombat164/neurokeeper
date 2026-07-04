# What this changes

<!-- One or two sentences: the problem and the shape of the fix. Link the issue if one exists. -->

## Checklist

- [ ] Tests land with the change (see CONTRIBUTING.md)
- [ ] `pytest -q` green locally
- [ ] The portable core stays domain-neutral: no organisation-, locale-, or consumer-specific content in code, comments, or example config
- [ ] Docs updated where behaviour changed: a new engine or flag is documented in the wiki reference (tests/test_wiki_coverage.py enforces this)
- [ ] Honest scoping: anything intentionally NOT done is stated in the PR description
