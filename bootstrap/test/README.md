# Bootstrap test suite

Cross-platform smoke/CI tests for the `neurokeeper` bootstrap kit. They run
`bootstrap.sh` (Linux/macOS) and `bootstrap.ps1` (Windows) end-to-end against a
**synthetic** repos file (one tiny public repo, `octocat/Hello-World`) and assert:

- the **required** toolchain is present afterwards and prints versions
  (`python3`/`python`, `git`, `node` -- hard fail if missing);
- the **optional** tools are reported but never fail the build
  (`gh`, `glab`, `gitleaks`, `pandoc`, `ripgrep`/`rg`, `uv`, `claude`);
- the synthetic repo was cloned into the target root;
- a **second** run exits 0 and takes the idempotent `ok` path (repo skipped, not
  re-cloned);
- `bootstrap.sh` has **LF** line endings (a CR byte would break it on Linux);
- a clear **PASS/FAIL table**, with a non-zero exit on any hard failure.

| File | Runs |
|---|---|
| `test-bootstrap.sh`  | POSIX bash, Linux + macOS |
| `test-bootstrap.ps1` | PowerShell 7, Windows |

## ⚠ Run only in a clean / disposable environment

These tests **install system packages** (via `sudo apt/dnf/pacman/zypper/brew` on
Linux/macOS, `winget` on Windows) and `npm i -g @anthropic-ai/claude-code`. That is
the whole point -- they prove the bootstrap actually provisions a fresh machine.

**Never run them on a daily-driver.** Use a container, a throwaway VM, or a
cloud instance you will destroy afterwards. Everything the tests create
themselves (the synthetic repos file, the clone root) lives under a temp dir
that is removed on exit; the package installs are **not** rolled back.

## Run locally (disposable box)

```bash
# Linux / macOS
bash bootstrap/test/test-bootstrap.sh
```

```powershell
# Windows (PowerShell 7)
pwsh -NoProfile -File bootstrap/test/test-bootstrap.ps1
```

Exit code `0` = all hard checks passed; `1` = at least one hard failure (details
in the table).

### Linux, fully isolated in a throwaway container

```bash
docker run --rm -it -v "$PWD":/work -w /work ubuntu:24.04 bash -c '
  apt-get update &&
  apt-get install -y sudo curl ca-certificates git &&
  bash bootstrap/test/test-bootstrap.sh
'
```

## GitLab CI

`.gitlab-ci.yml` defines `test:linux` on `image: ubuntu:24.04`. It installs the
test prerequisites (`sudo curl ca-certificates git`) in `before_script`, then runs
`bash bootstrap/test/test-bootstrap.sh`. Push the repo to GitLab; the job runs on
shared Linux runners.

An optional `test:macos` job is included **commented out** -- GitLab macOS SaaS
runners (`tags: [saas-macos-medium-m1]`) are paid and opt-in, so enable it only if
you have that entitlement.

## GitHub Actions

`.github/workflows/test.yml` runs a matrix over `ubuntu-latest`, `macos-latest`
and `windows-latest` on `push`, `pull_request` and manual `workflow_dispatch`.
Linux + macOS run the bash test; Windows runs the pwsh test. `fail-fast: false`
so one OS failing still lets the others report.

> Hosted-runner caveats:
> - On GitHub-hosted runners most of the toolchain is **pre-installed**, so the
>   bootstrap mostly takes its idempotent `ok` paths rather than installing.
> - `winget` is not reliably available on GitHub-hosted Windows runners. If a
>   genuinely-absent optional tool triggers a `winget` call, `bootstrap.ps1`
>   (which runs with `$ErrorActionPreference = 'Stop'`) may throw. The suite is
>   primarily intended for a disposable Windows **VM** where `winget` is present.

## Throwaway VM / cloud instance (mac + linux)

Spin up an instance you will **delete afterwards**, clone the harness, run the
matching test, then destroy the instance.

```bash
# Linux instance (e.g. a throwaway cloud VM, Ubuntu 24.04)
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/Wombat164/neurokeeper neurokeeper && cd neurokeeper
bash bootstrap/test/test-bootstrap.sh
# ... then DESTROY the instance.
```

```bash
# macOS instance (e.g. a disposable Apple-silicon macOS instance, or any throwaway Mac)
# Homebrew + git are the only prerequisites; the test drives the rest.
git clone https://github.com/Wombat164/neurokeeper neurokeeper && cd neurokeeper
bash bootstrap/test/test-bootstrap.sh
# ... then RELEASE / reset the mac instance.
```

```powershell
# Windows instance (throwaway VM with winget / App Installer available)
git clone https://github.com/Wombat164/neurokeeper neurokeeper; cd neurokeeper
pwsh -NoProfile -File bootstrap/test/test-bootstrap.ps1
# ... then DELETE the VM.
```

Because the package installs persist, treat every run as one-shot: provision,
test, capture the table, tear down.
