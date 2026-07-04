# SOURCES - external OSS, specs & prior art the harness relies on

Single attribution list (pattern doc section 13). Every external project the harness **borrows from**, **wraps**,
**recommends**, or **learned from** is cited here with author + licence + URL. The OSS wiki's reference
section is generated from this file. Add a row whenever you introduce a dependency or a borrowed idea.

## Borrowed / wrapped (the harness calls or defers to these)
| Project | Author / Org | Licence | Used for |
|---|---|---|---|
| [Tag Wrangler](https://github.com/pjeby/tag-wrangler) | pjeby | MIT | tag rename/merge APPLY (our `vault-tag-reconcile.py` only detects + proposes) |
| [gitleaks](https://github.com/gitleaks/gitleaks) | gitleaks | MIT | secret scanning (pre-commit gates on the memory + harness repos) |
| [Obsidian Linter](https://github.com/platers/obsidian-linter) | platers | MIT | frontmatter/format normalisation (configured, not fought - the linter-race lesson) |
| [pandoc](https://github.com/jgm/pandoc) + citeproc | jgm | GPL-2.0+ | document/render pipeline (document renders) |

## Recommended (Obsidian-native; the "don't reinvent the apply/query/input" division)
| Project | Author / Org | Licence | Recommended for |
|---|---|---|---|
| Obsidian Bases | Obsidian (core) | proprietary (core) | queries/dashboards over `note_type`/`sphere`/`status`/`domain` |
| Obsidian Properties | Obsidian (core) | proprietary (core) | typed frontmatter fields |
| [Frontmatter Smith](https://github.com/stroiman/obsidian-frontmatter-smith) | stroiman | MIT | controlled-vocab frontmatter INPUT (dropdowns for the axes) |

## Prior art / research (informed a design decision; not a dependency)
| Source | Relevance |
|---|---|
| [chezmoi](https://github.com/twpayne/chezmoi), [GNU stow](https://www.gnu.org/software/stow/), yadm | dotfiles "public base + private overlay" -> the L1a/L2 config-as-code split |
| [Quartz v4](https://github.com/jackyzha0/quartz) (MIT), [Diataxis](https://diataxis.fr/) | the OSS docs site - Obsidian-native static site + docs framework |
| [LiteLLM](https://github.com/BerriAI/litellm), [claude-code-router](https://github.com/musistudio/claude-code-router) | OSS-model handoff mechanisms (self-hosted open-model handoff, token-saving) |
| FSRS; Generative Agents (Park et al. 2023); Ebbinghaus forgetting curve | the memory-consolidate v2-H importance/decay curve |
| Mem0, Letta (MemGPT), A-MEM | agent-memory runtime prior art (confirmed: no fit for a markdown-file memory store -> custom justified) |

## Notes
- "Recommended" core Obsidian features are proprietary (the app), not OSS - flagged so a reader does
  not assume we ship them.
- What is OURS (do not attribute elsewhere): the deterministic detect/propose engines, the KOS axis
  vocabularies, the portable-core+adapters pattern, the @-header registry, the dream-log audit substrate.
