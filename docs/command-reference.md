# Command reference

Every command the toolkit exposes, with its flags, defaults and effect. This
document was generated from the CLI's own `--help` output and the command
dispatch in `src/workstation/cli.py`; when the two disagree, the source is
authoritative and this document is the file that must be corrected.

All commands accept the two global flags:

| Flag | Effect |
|---|---|
| `--json` | Also print the machine-readable result to stdout |
| `--save-report` | Write timestamped JSON and Markdown reports under `reports/` |

---

## Read-only commands

These commands never write to the filesystem, the Git state or any external
system. They are safe to run at any time.

### `diagnose`

Full system diagnostic. Aggregates disk, RAM, firewall adapter, Docker, Git
and Hermes findings into a single report.

```bash
python -m workstation diagnose
```

### `storage`

Mounted drive capacity audit.

```bash
python -m workstation storage
```

### `process`

Heavy process audit. Lists processes whose resident memory exceeds the
threshold, together with their command line, working directory, parent and
status.

| Flag | Default | Effect |
|---|---|---|
| `-t`, `--threshold` | `500` | Resident memory threshold in MB |

```bash
python -m workstation process --threshold 1000
```

### `guard scan`

Read-only process risk triage. Collects per-process evidence and reports
advisory heuristics. It is **not** malware detection; see the limitations
section of the [README](../README.md#process-guard-limitations).

| Flag | Default | Effect |
|---|---|---|
| `--no-network` | off | Skip all network inspection |

```bash
python -m workstation guard scan
python -m workstation guard scan --no-network
```

### `git-identity`

Git identity audit across the configured repository roots. Reports the
identity configured in each repository and classifies it.

```bash
python -m workstation git-identity
```

### `git-worktrees`

Git worktree audit. Lists the worktrees Git knows about, probes each one for
an operating-system lock without mutating the filesystem, and reports a
deletion plan.

```bash
python -m workstation git-worktrees
```

### `docker`

Docker audit. Reports images, containers and volumes. Performs no cleanup
without `--prune`.

| Flag | Effect |
|---|---|
| `--prune` | Enable cleanup |
| `--images` | Include images in the cleanup |
| `--volumes` | Include volumes in the cleanup |
| `-y`, `--yes` | Confirm the cleanup |

```bash
python -m workstation docker
python -m workstation docker --prune --images --volumes --yes
```

### `docker-health`

Running Docker services and their recent logs.

| Flag | Default | Effect |
|---|---|---|
| `--lines` | `30` | Number of recent log lines to show |

```bash
python -m workstation docker-health --lines 50
```

### `docker-logs`

Tail a Docker container log.

| Argument | Effect |
|---|---|
| `container` | Container name or identifier |

| Flag | Default | Effect |
|---|---|---|
| `--lines` | `100` | Number of recent log lines to show |

```bash
python -m workstation docker-logs happy_feistel --lines 200
```

### `hermes`

Hermes profile and state database health check. Reports on the profile
directory, the state database and the installed skills.

The full SQLite integrity probe is deliberately **not** run by this command;
it reports that the work is deferred rather than blocking for minutes on a
large database.

```bash
python -m workstation hermes
```

### `android-cleanup-plan`

Read-only Android SDK cleanup plan, derived from the Gradle requirements of
the configured repositories. Reports what could be removed and what it is
used for. It removes nothing.

```bash
python -m workstation android-cleanup-plan
```

### `repos`

Repository status audit across the configured repository roots.

| Flag | Effect |
|---|---|
| `--stale-branches` | Also report branches that are stale |

```bash
python -m workstation repos
python -m workstation repos --stale-branches
```

### `toolchain`

Developer toolchain audit.

| Flag | Effect |
|---|---|
| `--java` | Include Java details |
| `--android` | Include Android SDK details |

```bash
python -m workstation toolchain
python -m workstation toolchain --java
python -m workstation toolchain --android
```

### `forecast`

Disk pressure and managed-artefact forecast. Never deletes data.

```bash
python -m workstation forecast
```

### `kanban`

Kanban board health. Without `--archive-plan` this is read-only.

| Flag | Default | Effect |
|---|---|---|
| `--archive-plan` | none | List done tasks older than the given number of days |
| `--board` | none | Restrict the plan to one board |
| `--execute` | off | Execute the archive. Requires `--archive-plan` |
| `-y`, `--yes` | off | Confirm the archive |

```bash
python -m workstation kanban
python -m workstation kanban --archive-plan 30
python -m workstation kanban --archive-plan 30 --execute --yes
```

### `project`

Config-driven project status and commands. Without `--execute` this only
previews.

| Argument | Effect |
|---|---|
| `project` | Project name. Omit to report the status of every project |
| `action` | One of `status`, `test`, `lint`, `clean`, `web-test` |

| Flag | Default | Effect |
|---|---|---|
| `--execute` | off | Run the configured command |
| `--allow-shell` | off | Permit a shell-mode command. Required for shell-mode commands |

```bash
python -m workstation project
python -m workstation project mcp-java-sdk test
python -m workstation project mcp-java-sdk test --execute
```

Shell-mode commands additionally require the `WORKSTATION_ALLOW_SHELL`
environment variable for unattended runs. See
[Project commands](../README.md#project-commands).

### `loc`

Source line-count audit. Reports physical, code, blank and comment-only lines.

Exactly one of `--path` or `--project` is required.

| Flag | Effect |
|---|---|
| `--path` | Audit a directory directly |
| `--project` | Audit a configured project by name |
| `--include-config` | Include configuration files in the count |
| `--top` | `20` | Number of entries to show in the ranking |

```bash
python -m workstation loc --path D:/android/mcp-java-sdk
python -m workstation loc --project mcp-java-sdk --top 30
```

### `backup verify`

Read-only verification of an existing backup manifest. Checks every stored
payload digest and reports source-missing, failed, missing-payload and
digest-mismatch entries. It mutates nothing.

```bash
python -m workstation backup verify D:/backups/<backup-id>/manifest.json
```

---

## Guarded commands

These commands change state. Each one previews its action first and performs
nothing until the matching execution flag is supplied.

### `git-worktrees --execute --yes`

Deletes worktrees that the audit found to be removable. A worktree that Git
still tracks, or whose path carries a confirmed operating-system lock, is
never deleted.

```bash
python -m workstation git-worktrees --execute --yes
```

### `git-identity --fix`

Unsets local Git identities that are known to be unsafe for shared
repositories. It never writes an identity.

```bash
python -m workstation git-identity --fix
```

### `guard kill <PID>`

Requests termination of exactly one explicitly named PID. It never selects a
target by name, pattern or process group.

| Argument | Effect |
|---|---|
| `pid` | The single process identifier to act on |

| Flag | Default | Effect |
|---|---|---|
| `--execute` | off | Actually request termination. Without it, this is a dry-run |

```bash
python -m workstation guard kill 1234
python -m workstation guard kill 1234 --execute
```

### `kanban --archive-plan <DAYS> --execute --yes`

Archives done Kanban tasks older than the given number of days. The plan is
listed first; archiving publishes the archived task without clobbering the
live board.

```bash
python -m workstation kanban --archive-plan 30 --execute --yes
```

### `hermes-maintain`

Backs up, checkpoints and optimises the Hermes state database. The operation
is disk-gated: it refuses to run when free space is below the threshold.

| Flag | Default | Effect |
|---|---|---|
| `--execute` | off | Perform the maintenance. Without it, the plan is shown |
| `-y`, `--yes` | off | Confirm the maintenance |
| `--min-free-gb` | `15.0` | Minimum free disk space in GB required |

```bash
python -m workstation hermes-maintain
python -m workstation hermes-maintain --execute --yes --min-free-gb 5
```

### `schedule`

Previews, and optionally creates, a daily health-report schedule.

| Flag | Default | Effect |
|---|---|---|
| `--hour` | `9` | Hour of the day, in local time, for the report |
| `--create` | off | Create the schedule |
| `-y`, `--yes` | off | Confirm the creation |

```bash
python -m workstation schedule --hour 9
python -m workstation schedule --hour 9 --create --yes
```

---

## Data commands

### `backup`

Creates a versioned backup of the local configuration and the Hermes state
database. Unlike the guarded commands above, `backup` always writes.

| Flag | Default | Effect |
|---|---|---|
| `--label` | `workstation` | A label recorded with the backup |

```bash
python -m workstation backup --label workstation
```

Payload naming is collision-free: two sources with the same base name receive
distinct payload paths, and each manifest entry records its own path and
digest. Backup artefacts are restricted to their owner — see
[Backup permissions](backup-permissions.md).

### `restore`

Restores files from a backup manifest.

| Argument | Effect |
|---|---|
| `manifest` | Path to the backup manifest |

| Flag | Default | Effect |
|---|---|---|
| `--plan` | off | Validate and report the restore actions without mutating anything |
| `--execute` | off | Perform the restore |
| `-y`, `--yes` | off | Confirm the restore |
| `--allowed-root` | none | An authorised destination root. Repeatable. Required with `--execute` |

```bash
python -m workstation restore D:/backups/manifest.json --plan --allowed-root D:/projects
python -m workstation restore /srv/backups/manifest.json --execute --yes --allowed-root /srv/projects
```

`--plan` is read-only: it creates no directories and no files, and it
validates the complete manifest, every payload digest and every destination
against the authorised roots.

**Restore execution is POSIX-only.** Destination writes are bound to a
directory descriptor opened from the allowed root, so a swapped parent
directory cannot redirect them. On platforms without descriptor-relative
operations — Windows, for example — `restore --execute` refuses rather than
falling back to path-based replacement. `--plan` remains available on every
platform.
