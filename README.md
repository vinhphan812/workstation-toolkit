# Workstation Toolkit

A **cross-platform workstation operations toolkit** for Windows, Linux, and macOS. It audits and maintains the developer workstation, repositories, worktrees, Docker, project state, and Hermes Agent. Hermes is one module—not the toolkit's only purpose.

## Safety model

- Read-only commands are the default.
- Mutating operations require an explicit flag such as `--fix`, `--prune`, or `--execute`.
- Git worktree deletion refuses Git-registered worktrees.
- Git worktree deletion also refuses paths with a confirmed operating-system lock.
- The worktree audit never mutates the filesystem while probing, and reports lock state as `locked`, `unlocked`, or `unknown` rather than guessing. `unknown` means the platform offers no reliable read-only evidence (for example POSIX, where an open file can still be unlinked).
- Git identity remediation only unsets known unsafe local identities, such as `hermes@agent.local`; it never writes a local identity.
- Large Hermes SQLite databases are not integrity-scanned in the fast health check; the command reports that this work is deferred rather than blocking for minutes.
- Configured project commands are **executable code**. `--execute` runs the configured command with the current user's privileges, exactly as if it had been typed into a terminal. Only the person running the toolkit can approve that.
- Backup payloads are named so that same-named sources never share one payload file; every manifest entry records its own payload path and digest.
- Backup manifests keep the same schema, so manifests written by earlier versions still restore.

## Requirements

- Python 3.10+
- `uv` recommended (or Python `venv` + pip)
- `git` for repository commands
- Docker CLI for Docker commands

## Install

### Windows

```powershell
cd D:\workstation-toolkit
uv venv
uv pip install -e ".[dev]"
uv run python -m workstation diagnose
```

### Linux / macOS

```bash
cd workstation-toolkit
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python -m workstation diagnose
```

The convenience scripts are also available:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
```

```bash
bash scripts/install.sh
```

## Commands

```bash
# System health: disk, RAM, firewall adapter, Docker, Git, Hermes
python -m workstation diagnose

# Disk capacity and managed-artifact forecast; never deletes data
python -m workstation storage
python -m workstation forecast

# Heavy process audit (default: >=500 MB)
python -m workstation process --threshold 1000

# Guard scan is read-only; --no-network explicitly skips network inspection
python -m workstation guard scan --no-network

# Preview termination of one explicitly selected PID (dry-run by default)
python -m workstation guard kill 1234

# Request termination of exactly that PID only with explicit opt-in
python -m workstation guard kill 1234 --execute

# Repository hygiene
python -m workstation repos
python -m workstation repos --stale-branches

# Developer toolchains
python -m workstation toolchain
python -m workstation toolchain --java
python -m workstation toolchain --android

# Config-driven project commands; preview by default
python -m workstation project
python -m workstation project mcp-java-sdk test
python -m workstation project mcp-java-sdk test --execute

# Source LOC audit; reports physical/code/blank/comment-only lines
python -m workstation loc --project mcp-java-sdk --top 30
python -m workstation --save-report loc --path D:/android/mcp-java-sdk

# Git identity audit across configured repos
python -m workstation git-identity

# Remove only known-bad local identities, with explicit opt-in
python -m workstation git-identity --fix

# Git worktree audit; no deletion by default (read-only plan)
python -m workstation git-worktrees

# Docker inspection; no cleanup by default
python -m workstation docker

# Runtime health and bounded logs for running containers
python -m workstation docker-health --lines 50
python -m workstation docker-logs happy_feistel --lines 200

# Explicit Docker cleanup
python -m workstation docker --prune --images --volumes --yes

# Hermes profile/state database health
python -m workstation hermes

# Create a versioned backup; verify all stored payload digests without mutation
python -m workstation backup --label workstation
python -m workstation backup verify D:/backups/<backup-id>/manifest.json

# Preflight every restore entry and authorized path without mutation
python -m workstation restore D:/backups/manifest.json --plan --allowed-root D:/projects

# Restore a manifest only into explicitly authorized destination roots
# Manifest backup directories must be trusted and not concurrently modified.
# Restore is POSIX-only: destination writes are bound to a directory descriptor
# opened from the allowed root, so a swapped parent cannot redirect them. On
# platforms without descriptor-relative operations (for example Windows) restore
# refuses instead of falling back to path-based replacement.
python -m workstation restore /srv/backups/manifest.json --execute --yes --allowed-root /srv/projects

# Kanban is read-only: board health and archive candidates only
python -m workstation kanban
python -m workstation kanban --archive-plan 30

# JSON and timestamped Markdown/JSON reports for automation
python -m workstation --json --save-report forecast
```

## Cross-platform design

### Process guard limitations

`guard scan` reports point-in-time process evidence and weak name/command-line heuristics; it is not malware detection and can produce false positives or miss threats. Names such as AnyDesk and TeamViewer are not treated as suspicious solely because they are remote-support tools. By default, scanning inspects available network connections; permissions may limit this evidence. `--no-network` skips network inspection entirely. Scanning never terminates processes. `guard kill <PID>` is a dry-run unless `--execute` is supplied, and then requests termination of only that PID. Review evidence and verify the target before opting in.


The Python core contains portable operations:

- Disk capacity and bounded storage inspection (`shutil`)
- RAM/process inspection (`psutil`)
- Git identity, repository and worktree inspection (real `git` CLI)
- Docker inspection/cleanup (real `docker` CLI)
- SQLite health checks and read-only Kanban archive planning
- JSON-compatible command output with timestamped Markdown/JSON reports
- Config-driven, explicit project test/lint/clean commands

Platform adapters implement non-portable operations and must report an explicit status rather than fake a result:

| Area | Windows | Linux | macOS |
|---|---|---|---|
| Firewall | `Get-NetFirewallProfile` | UFW/firewalld detection | Application Firewall query |
| Startup | Startup-command inventory | systemd user units / crontab | launchd inventory |
| Logs | Event Log | `journalctl` | `log show` |
| Package manager | winget | apt/dnf/pacman/zypper | Homebrew |

### Publish with immutable action pins

The release workflow pins third-party actions to verified full commit SHAs and includes the upstream version in a comment. To update a pin, select the intended upstream release, verify its full commit SHA from the official repository/tag (and review the tag's commit/signature where available), update the SHA and version comment together, then run the release-workflow policy test and inspect the workflow diff. Never replace the SHA with a mutable version tag.

Release-tag creation must be protected by repository rulesets or tag protection configured by a repository administrator. That setting is external to this source tree; verify it in GitHub repository settings before enabling releases. The workflow policy test enforces immutable action references and least-privilege permissions, but cannot prove GitHub-side tag protection.


`config/repos.json` and `config/projects.json` are deliberately gitignored. They describe the current machine and should not be committed.

JSON is the only configuration format currently loaded by the toolkit. The `*.toml.example` files are commented, illustrative references only; they are not parsed or merged. Use the JSON examples and `config/local.json` for device-local settings.

```json
{
  "repos": [
    "D:/android/mcp-java-sdk",
    "D:/Nodejs/AMS_DNTU"
  ],
  "exclude_patterns": [".brv", ".venv", "vendor"]
}
```

Copy the JSON `*.example` files on a new machine, adjust the paths, and run the same Python commands. You can also override paths through environment variables:

| Variable | Meaning |
|---|---|
| `WORKSTATION_CONFIG` | Config directory |
| `HERMES_HOME` | Hermes installation root or active profile path |
| `HERMES_PROFILE_DIR` | Exact Hermes profile directory |
| `HERMES_KANBAN_HOME` | Exact Kanban boards directory |

Reports are written under `reports/`; local config, reports, and backups remain gitignored.

### Project commands are executable code

`config/projects.json` holds the commands the toolkit runs on your behalf. Those
entries are **executable code**, not data. `python -m workstation project <name>
<action> --execute` runs the configured command with the privileges of the
current user, exactly as if you had typed it into a terminal yourself. Review
the dry-run output before using `--execute`.

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

- a string with no shell syntax (for example `"python -m pytest"`) is split
  into an argument list and executed without a shell — the same observable
  result as before, but with no shell involved;
- a string that uses shell syntax (pipes, redirects, `&&`, globs, variable
  expansion, and so on) is treated as a shell command and needs the
  `--allow-shell` opt-in. Convert it to `{"argv": [...]}` to avoid the shell.

Command, environment and timeout values are validated before anything runs.
Malformed configuration is reported as an error rather than executed.

## Development

```bash
uv run pytest -q
uv run python -m compileall -q src
```

Current tests cover disk inspection, Git identity classification, protected worktree deletion, SQLite quick integrity, process orphan evidence, and adapter interfaces.


### Backup manifest compatibility and recovery

New manifests use schema version 1 and record each source's size, modification time, and SHA-256. The verifier accepts legacy manifests without a version (treated as version 0), as well as version 1; unknown or malformed versions are rejected. A source that changes while being copied is marked failed and its incomplete payload is removed. `backup verify` is read-only and reports source-missing, failed, missing-payload, and digest-mismatch entries.

Use `restore --plan` before execution. It validates the complete manifest, each payload digest, and every destination against one of the explicitly supplied `--allowed-root` paths; it creates no directories or files. For recovery, first verify the trusted backup, inspect the plan, then execute restore with `--execute --yes` and the same authorized roots. Keep backup directories trusted and do not modify them concurrently. Execution requires POSIX descriptor-relative destination operations; on other platforms `restore --execute` fails closed and `--plan` remains available for read-only preflight.
