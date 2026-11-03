# Workstation Toolkit

A **cross-platform workstation operations toolkit** for Windows, Linux, and macOS. It audits and maintains the developer workstation, repositories, worktrees, Docker, project state, and Hermes Agent. Hermes is one module — not the toolkit's only purpose.

## Contents

- [Safety model](#safety-model)
- [Requirements](#requirements)
- [Install](#install)
  - [Windows](#windows)
  - [Linux and macOS](#linux-and-macos)
- [Quick start](#quick-start)
- [Commands](#commands)
  - [Process guard limitations](#process-guard-limitations)
  - [Guarded operations in detail](#guarded-operations-in-detail)
- [Configuration](#configuration)
- [Environment variables](#environment-variables)
- [Cross-platform design](#cross-platform-design)
- [Backup and restore](#backup-and-restore)
- [Project commands](#project-commands)
- [Git identity remediation](#git-identity-remediation)
- [Releases](#releases)
- [Development](#development)
  - [Documentation standards](#documentation-standards)
- [Further documentation](#further-documentation)

## Safety model

The toolkit is read-only by default. Every operation that changes state says so
explicitly in its command name, its flags, or both.

- **Read-only is the default.** Mutating operations require an explicit flag
  such as `--fix`, `--prune`, `--execute` or `--create`.
- **Dry-run is the default for guarded operations.** `git-worktrees`,
  `kanban --archive-plan`, `project` and `guard kill` all preview the action
  they would take and perform nothing until the matching execution flag is
  supplied.
- **Git worktree deletion refuses Git-registered worktrees.** A worktree that
  Git still tracks is never removed by the toolkit.
- **Git worktree deletion also refuses paths with a confirmed operating-system
  lock.**
- **The worktree audit never mutates the filesystem while probing**, and
  reports lock state as `locked`, `unlocked` or `unknown` rather than
  guessing. `unknown` means the platform offers no reliable read-only
  evidence — for example POSIX, where an open file can still be unlinked.
- **Git identity remediation only unsets known unsafe local identities**, such
  as `hermes@agent.local`; it never writes a local identity.
- **Large Hermes SQLite databases are not integrity-scanned in the fast health
  check.** The command reports that this work is deferred rather than blocking
  for minutes.
- **Configured project commands are executable code.** `--execute` runs the
  configured command with the current user's privileges, exactly as if it had
  been typed into a terminal. Only the person running the toolkit can approve
  that.
- **Backup payloads are named so that same-named sources never share one
  payload file.** Every manifest entry records its own payload path and
  digest.
- **Backup manifests keep the same schema**, so manifests written by earlier
  versions still restore.
- **Restore fails closed rather than degrading.** On platforms without
  descriptor-relative destination operations — Windows, for example —
  `restore --execute` refuses instead of falling back to path-based
  replacement.

## Requirements

- Python 3.10 or later
- [`uv`](https://docs.astral.sh/uv/) recommended, or `venv` with `pip`
- `git`, for the repository, identity and worktree commands
- Docker CLI, for the Docker commands

Optional:

- `icacls`, on Windows, for backup permission enforcement. Without it the
  outcome is reported as `unsupported` rather than `enforced` — see
  [Backup permissions](docs/backup-permissions.md).

## Install

### Windows

```powershell
cd D:\workstation-toolkit
uv venv
uv pip install -e ".[dev]"
uv run python -m workstation diagnose
```

### Linux and macOS

```bash
cd workstation-toolkit
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python -m workstation diagnose
```

Convenience scripts are also available:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
```

```bash
bash scripts/install.sh
```

Installing the package also provides a `workstation` console script, so
`workstation diagnose` is equivalent to `python -m workstation diagnose`.

## Quick start

```bash
# Overall system health: disk, RAM, firewall, Docker, Git, Hermes
python -m workstation diagnose

# Heavy process audit (default threshold: 500 MB)
python -m workstation process --threshold 1000

# Read-only process triage
python -m workstation guard scan --no-network

# Repository and worktree hygiene
python -m workstation repos --stale-branches
python -m workstation git-worktrees

# Kanban board health (read-only)
python -m workstation kanban
```

Every command also accepts the two global flags:

| Flag | Effect |
|---|---|
| `--json` | Also print the machine-readable result to stdout |
| `--save-report` | Write timestamped JSON and Markdown reports under `reports/` |

## Commands

The authoritative reference is [docs/command-reference.md](docs/command-reference.md).
This table is a summary of every command the toolkit exposes.

| Command | Purpose | Mutating |
|---|---|---|
| `diagnose` | Full system diagnostic | No |
| `storage` | Mounted drive capacity audit | No |
| `process` | Heavy process audit | No |
| `guard scan` | Read-only process risk triage | No |
| `guard kill` | Preview or request termination of exactly one PID | Only with `--execute` |
| `git-identity` | Git identity audit across configured repositories | No |
| `git-identity --fix` | Unset known-bad local identities | Yes |
| `git-worktrees` | Git worktree audit and deletion plan | Only with `--execute --yes` |
| `docker` | Docker audit and explicit cleanup | Only with `--prune --yes` |
| `docker-health` | Running Docker services and recent logs | No |
| `docker-logs` | Tail a Docker container log | No |
| `hermes` | Hermes health check | No |
| `hermes-maintain` | Backup, checkpoint and optimize the Hermes database | Only with `--execute --yes` |
| `android-cleanup-plan` | Read-only Android SDK cleanup plan | No |
| `repos` | Repository status audit | No |
| `toolchain` | Developer toolchain audit | No |
| `forecast` | Disk pressure and managed-artefact forecast | No |
| `kanban` | Kanban board health and archive planning | Only with `--archive-plan ... --execute --yes` |
| `project` | Config-driven project status and commands | Only with `--execute` |
| `loc` | Source line-count audit | No |
| `backup` | Create a versioned backup of local config and Hermes state | Yes |
| `backup verify` | Read-only verification of a backup manifest | No |
| `restore` | Restore files from a backup manifest | Only with `--execute --yes` |
| `schedule` | Preview or create a daily health-report schedule | Only with `--create --yes` |

### Process guard limitations

`guard scan` reports point-in-time process evidence and weak name and
command-line heuristics. It is **not** malware detection, and it can produce
false positives or miss threats. Names such as AnyDesk and TeamViewer are not
treated as suspicious solely because they are remote-support tools.

By default, scanning inspects available network connections; permissions may
limit this evidence. `--no-network` skips network inspection entirely.
Scanning never terminates processes. `guard kill <PID>` is a dry-run unless
`--execute` is supplied, and then it requests termination of only that PID.
Review the evidence and verify the target before opting in.

### Guarded operations in detail

```bash
# Worktree deletion: preview by default
python -m workstation git-worktrees
python -m workstation git-worktrees --execute --yes

# Kanban archiving: preview the candidates first
python -m workstation kanban --archive-plan 30
python -m workstation kanban --archive-plan 30 --execute --yes

# Hermes database maintenance: disk-gated and explicit
python -m workstation hermes-maintain
python -m workstation hermes-maintain --execute --yes --min-free-gb 5

# Daily health report schedule: preview, then create
python -m workstation schedule --hour 9
python -m workstation schedule --hour 9 --create --yes
```

## Configuration

The toolkit loads **JSON only**. `config/repos.json` and `config/projects.json`
are deliberately gitignored: they describe the current machine and must not be
committed. Copy the matching `.example` file and adjust the paths.

| File | Read by | Purpose |
|---|---|---|
| `config/local.json` | the toolkit | Device-local settings |
| `config/repos.json` | `repos`, `toolchain`, `git-identity`, `git-worktrees`, `android-cleanup-plan` | Repository roots and exclusion patterns |
| `config/projects.json` | `project`, and `loc --project` | Configured project commands |
| `config/repos.toml.example` | nothing | Illustrative only |
| `config/projects.toml.example` | nothing | Illustrative only |
| `config/toolkit.toml.example` | nothing | Illustrative only |

The `*.toml.example` files are commented reference material. They are not
parsed, not merged, and not read by any command. See
[docs/configuration.md](docs/configuration.md) for the full reference.

A minimal `config/repos.json`:

```json
{
  "repos": [
    "D:/android/mcp-java-sdk",
    "D:/Nodejs/AMS_DNTU"
  ],
  "exclude_patterns": [".brv", ".venv", "vendor"]
}
```

A minimal `config/projects.json`:

```json
{
  "projects": [
    {
      "name": "example-project",
      "path": "/absolute/path/to/project",
      "commands": {
        "test": {"argv": ["python", "-m", "pytest"]}
      }
    }
  ]
}
```

## Environment variables

| Variable | Meaning |
|---|---|
| `WORKSTATION_CONFIG` | Configuration directory. Defaults to the `config/` directory beside the package root. |
| `HERMES_HOME` | Hermes installation root, or the active profile directory. |
| `HERMES_PROFILE_DIR` | Exact Hermes profile directory. Overrides the `HERMES_HOME` derivation. |
| `HERMES_KANBAN_HOME` | Exact Kanban boards directory. |
| `WORKSTATION_ALLOW_SHELL` | Set to `1` to permit shell-mode project commands. Required in addition to `--allow-shell` for unattended runs. |

`HERMES_PROFILE_DIR` takes precedence over `HERMES_HOME`. When `HERMES_HOME`
already points at a `profiles/<name>` directory it is used directly rather than
having `profiles/coordinator` appended.

Local config, reports and backups remain gitignored.

## Cross-platform design

The Python core contains portable operations:

- Disk capacity and bounded storage inspection (`shutil`)
- RAM and process inspection (`psutil`)
- Git identity, repository and worktree inspection (real `git` CLI)
- Docker inspection and cleanup (real `docker` CLI)
- SQLite health checks and read-only Kanban archive planning
- JSON-compatible command output with timestamped Markdown and JSON reports
- Config-driven, explicit project test, lint and clean commands

Platform adapters implement non-portable operations and must report an
explicit status rather than fake a result:

| Area | Windows | Linux | macOS |
|---|---|---|---|
| Firewall | `Get-NetFirewallProfile` | UFW/firewalld detection | Application Firewall query |
| Startup | Startup-command inventory | systemd user units / crontab | launchd inventory |
| Logs | Event Log | `journalctl` | `log show` |
| Package manager | winget | apt/dnf/pacman/zypper | Homebrew |

## Backup and restore

Create a versioned backup, then verify it without mutating anything:

```bash
python -m workstation backup --label workstation
python -m workstation backup verify D:/backups/<backup-id>/manifest.json
```

Preflight a restore before executing it:

```bash
python -m workstation restore D:/backups/manifest.json --plan --allowed-root D:/projects
```

Execute a restore only into explicitly authorised destination roots:

```bash
python -m workstation restore /srv/backups/manifest.json --execute --yes --allowed-root /srv/projects
```

> **Restore is POSIX-only.** Destination writes are bound to a directory
> descriptor opened from the allowed root, so a swapped parent cannot redirect
> them. On platforms without descriptor-relative operations — Windows, for
> example — restore refuses instead of falling back to path-based
> replacement. `--plan` remains available everywhere.

Keep backup directories trusted and do not modify them concurrently.

New manifests use schema version 1 and record each source's size, modification
time and SHA-256. The verifier accepts legacy manifests without a version
(treated as version 0) as well as version 1; unknown or malformed versions are
rejected. A source that changes while being copied is marked failed and its
incomplete payload is removed. `backup verify` is read-only and reports
source-missing, failed, missing-payload and digest-mismatch entries.

For recovery, verify the trusted backup, inspect the plan, then execute the
restore with `--execute --yes` and the same authorised roots.

Backup artefacts are restricted to their owner. The policy, its verification
rules and its platform limitations are documented in
[docs/backup-permissions.md](docs/backup-permissions.md).

## Project commands

`config/projects.json` holds the commands the toolkit runs on your behalf.
Those entries are **executable code**, not data. `python -m workstation
project <name> <action> --execute` runs the configured command with the
privileges of the current user, exactly as if you had typed it into a terminal
yourself. Review the dry-run output before using `--execute`.

Commands are configured in one of two explicit forms:

```json
{
  "projects": [
    {
      "name": "example-project",
      "path": "/absolute/path/to/project",
      "commands": {
        "test": {"argv": ["python", "-m", "pytest"]},
        "lint": {"argv": ["python", "-m", "ruff", "check", "."]}
      }
    }
  ]
}
```

**`argv` (recommended)** — the command is an argument list and is executed
*without* a shell. Every element is passed literally to the operating system,
so a value such as `"release && rm -rf build"` is data, never syntax.

**`shell`** — the command is a shell string and is interpreted by the platform
shell. This mode requires an explicit trusted-shell opt-in that is deliberately
*not* part of the configuration file, so that somebody able to edit the
configuration cannot grant themselves the right to run arbitrary shell code:

```bash
python -m workstation project example-project lint --execute --allow-shell
# or, for automation:
WORKSTATION_ALLOW_SHELL=1 python -m workstation project example-project lint --execute
```

Without that opt-in a shell-mode command is refused and nothing is executed.
The dry run always reports which mode a command uses (`"mode": "argv"` or
`"mode": "shell"`), so the mode is visible before anything runs.

**Migration path for existing string commands.** A legacy plain string is
accepted and classified automatically:

- a string with no shell syntax — for example `"python -m pytest"` — is split
  into an argument list and executed without a shell. The observable result is
  the same as before, but with no shell involved;
- a string that uses shell syntax — pipes, redirects, `&&`, globs, variable
  expansion, and so on — is treated as a shell command and needs the
  `--allow-shell` opt-in. Convert it to `{"argv": [...]}` to avoid the shell.

Command, environment and timeout values are validated before anything runs.
Malformed configuration is reported as an error rather than executed.

## Git identity remediation

`git-identity` audits the local identity configured in each repository under
the configured repository roots. It classifies the identity and reports what it
found.

`--fix` removes only identities that are known to be unsafe for shared
repositories — for example `hermes@agent.local`. It **never writes** a local
identity, so it cannot silently change who your commits are attributed to. Set
your own identity with the normal `git config` commands.

## Releases

The release workflow pins third-party actions to verified full commit SHAs and
includes the upstream version in a comment.

To update a pin, select the intended upstream release, verify its full commit
SHA from the official repository or tag — and review the tag's commit and
signature where available — update the SHA and version comment together, then
run the release-workflow policy test and inspect the workflow diff. Never
replace the SHA with a mutable version tag.

Release-tag creation must be protected by repository rulesets, or by tag
protection configured by a repository administrator. That setting is external
to this source tree; verify it in the GitHub repository settings before
enabling releases. The workflow policy test enforces immutable action
references and least-privilege permissions, but it cannot prove GitHub-side
tag protection.

## Development

```bash
uv run pytest -q
uv run python -m compileall -q src
```

The test suite covers disk inspection, Git identity classification, protected
worktree deletion, SQLite quick integrity, process orphan evidence, adapter
interfaces, backup permission enforcement, restore validation and fail-closed
behaviour, project command execution modes, guarded maintenance stage
reporting, and Kanban archive publication.

The documentation is a MkDocs site. Build it with a strict check, which fails
on a broken navigation entry or an unresolvable internal link:

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict
```

The site is written to `site/`, which is not tracked.

### Documentation standards

Documentation is written in English (UK). Every factual claim about the
toolkit's behaviour must be verified against the source or the command's own
`--help` output before it is written down, and the verification must be
repeatable. A claim that cannot be verified is not written as fact.

When a command, flag or configuration key changes, the change must include the
matching update to:

- this file,
- [docs/command-reference.md](docs/command-reference.md),
- [docs/configuration.md](docs/configuration.md), where it concerns
  configuration,
- the tests.

## Further documentation

The documentation index is [docs/index.md](docs/index.md). It explains which
document to read for a given task.

| Document | Contents |
|---|---|
| [docs/index.md](docs/index.md) | Documentation index and how the documents are organised |
| [docs/architecture.md](docs/architecture.md) | How the toolkit is built, and why the safety rules are shaped as they are |
| [docs/command-reference.md](docs/command-reference.md) | Every command, flag and default, verified against the CLI |
| [docs/configuration.md](docs/configuration.md) | Configuration files, precedence and environment variables |
| [docs/backup-permissions.md](docs/backup-permissions.md) | The backup permission policy, its verification and its platform limits |
| [docs/templates/index.md](docs/templates/index.md) | Template library for new documents |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Safety requirements and the review process |
| [CHANGELOG.md](CHANGELOG.md) | Released and unreleased changes |
