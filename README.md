# Workstation Toolkit

A **cross-platform workstation operations toolkit** for Windows, Linux, and macOS. It audits and maintains the developer workstation, repositories, worktrees, Docker, project state, and Hermes Agent. Hermes is one module—not the toolkit's only purpose.

## Safety model

- Read-only commands are the default.
- Mutating operations require an explicit flag such as `--fix`, `--prune`, `--execute`, or `--kill`.
- Git worktree deletion refuses Git-registered worktrees.
- Git identity remediation only unsets known unsafe local identities, such as `hermes@agent.local`; it never writes a local identity.
- Large Hermes SQLite databases are not integrity-scanned in the fast health check; the command reports that this work is deferred rather than blocking for minutes.

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

# Audit Git worktrees; no deletion by default
python -m workstation git-worktrees --dry-run

# Docker inspection; no cleanup by default
python -m workstation docker

# Runtime health and bounded logs for running containers
python -m workstation docker-health --lines 50
python -m workstation docker-logs happy_feistel --lines 200

# Explicit Docker cleanup
python -m workstation docker --prune --images --volumes --yes

# Hermes profile/state database health
python -m workstation hermes

# Kanban is read-only: board health and archive candidates only
python -m workstation kanban
python -m workstation kanban --archive-plan 30

# JSON and timestamped Markdown/JSON reports for automation
python -m workstation --json --save-report forecast
```

## Cross-platform design

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

## Device-local configuration

`config/repos.json` and `config/projects.json` are deliberately gitignored. They describe the current machine and should not be committed.

```json
{
  "repos": [
    "D:/android/mcp-java-sdk",
    "D:/Nodejs/AMS_DNTU"
  ],
  "exclude_patterns": [".brv", ".venv", "vendor"]
}
```

Copy the `*.example` files on a new machine, adjust the paths, and run the same Python commands. You can also override paths through environment variables:

| Variable | Meaning |
|---|---|
| `WORKSTATION_CONFIG` | Config directory |
| `HERMES_HOME` | Hermes installation root or active profile path |
| `HERMES_PROFILE_DIR` | Exact Hermes profile directory |
| `HERMES_KANBAN_HOME` | Exact Kanban boards directory |

Reports are written under `reports/`; local config, reports, and backups remain gitignored.
## Development

```bash
uv run pytest -q
uv run python -m compileall -q src
```

Current tests cover disk inspection, Git identity classification, protected worktree deletion, SQLite quick integrity, process orphan evidence, and adapter interfaces.
