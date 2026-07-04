# Security

## Reporting a vulnerability

Please report suspected security issues by opening a private security advisory on the
repository (GitHub: *Security > Advisories > Report a vulnerability*) rather than a public
issue. We aim to acknowledge reports promptly.

## Secret scanning

CI runs [gitleaks](https://github.com/gitleaks/gitleaks) with its **default rules** (API keys,
tokens, private keys) on every push, against the working tree - this scan is blocking. The
deterministic engines ship no secrets; the scan keeps it that way.

```
gitleaks detect --source . --no-git --redact --no-banner --exit-code 1
```

## Additional pre-publish OPSEC keyword scan (maintainers)

In addition to the public default-rules scan, maintainers run a **private keyword scan** before
publishing. It hunts for environment-specific names, codes, and infrastructure identifiers that
are not secrets in the credential sense but should not appear in a public tree. Because that
config necessarily enumerates the very terms it looks for, the config file is **kept out of the
public repository** (gitignored, local-only) and is not required to build, test, or use the
project. The public secret scan above is the one that runs in CI.

## Safety model of the mutating engines

The vault-mutating engines are **report-by-default**: they write nothing without an explicit
`--apply`. Bulk vault writes additionally refuse to run while a notes app (Obsidian) is open,
to avoid a linter racing the external write, and confine writes to the configured vault root
(symlinks and out-of-vault paths are refused). For mutating engines, git is the audit trail --
commit before, review the diff after. See the wiki how-to guides for details.
