# Third-party licenses

neurokeeper itself is released under the MIT License (see [LICENSE](LICENSE)).
This file lists the licenses of the third-party components that neurokeeper
depends on or uses.

## Runtime dependencies

- **PyYAML** (>=6.0), MIT License. Used to parse and emit note frontmatter.

## Development dependencies

These are needed only to develop and test neurokeeper, not to run it.

- **pytest** (>=8.0), MIT License. Test runner.
- **ruff** (>=0.6), MIT License. Linter.

## Documentation site

The documentation site (published at
https://wombat164.github.io/neurokeeper/) is built with **Quartz**
(jackyzha0/quartz), MIT License. Quartz is fetched at build time from a pinned
commit and is not vendored in this repository.
