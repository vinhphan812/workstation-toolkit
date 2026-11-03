# Changelog

All notable changes to this project are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A release is published by pushing a `v*` tag. The release workflow builds the
distribution and attaches it to the GitHub release for that tag. Release-tag
creation must be protected by repository rulesets or tag protection; see the
[Releases](README.md#releases) section of the README.

The reusable template for this file is
[docs/templates/changelog_template.md](docs/templates/changelog_template.md).

## [Unreleased]

The release candidate is `0.2.0`. Move the release entries out of this section
when preparing the final release commit immediately before pushing the tag.

## [0.2.0] - 2026-11-03

The entries below are selected notable changes since the initial `v0.1.0`
release. They are grouped by type rather than listed commit by commit; test-only
follow-ups and other routine commits are intentionally omitted.

### Added

- **Kanban archiving** that reads the board schema defensively, exports the
  archived tasks per month and removes them from the live database. The
  archive is safety-gated and supports a board filter and a skip-recent
  window. (`41c82c0`, `d60d116`)
- **Process triage and explicit termination.** `guard scan` collects
  per-process evidence and reports advisory heuristics; `guard kill` requests
  termination of exactly one explicitly named process identifier and never
  selects a target by name, pattern or process group. (`4a6a306`)
- **Backup verification and restore planning.** `backup verify` checks every
  stored payload digest and reports source-missing, failed, missing-payload
  and digest-mismatch entries without mutating anything; `restore --plan`
  validates the complete manifest and every destination against the
  authorised roots without creating a directory or a file. (`b31cec7`)

### Security

- **Backup artefacts are owner-only.** On POSIX the directory mode is `0700`
  and the file mode is `0600`, applied from the first instant the artefact
  exists. On Windows the discretionary access control list is restricted to
  the owner, with `SYSTEM` and `Administrators` removed and inheritance
  disabled, so there is no window in which another user can read the
  payload. (`d9ebd5c`, `f40c80c`)
- **Backup fails closed when the permission outcome cannot be established.**
  An unreadable Windows security descriptor is now reported as `failed`
  rather than `unsupported`, which aborts the backup and removes the
  incomplete payload instead of leaving an artefact whose protection was
  never confirmed. (`742f677`, `7004b1e`)
- **Restore validates the manifest and refuses unauthorised destinations.**
  Manifest paths are validated before anything is written, and a restore
  requires an explicit authorised destination root. (`e39c6fa`,
  `c173fd7`)
- **Restore binds destination writes to an opened directory.** Destination
  mutations are anchored to a directory descriptor opened from the allowed
  root, so a swapped parent directory cannot redirect them outside it.
  (`04fced5`, `65967e7`)
- **Restore fails closed where the platform cannot support that.** The
  capability is detected once at import time; where descriptor-relative
  operations are unavailable, `restore --execute` refuses before any
  destination mutation instead of falling back to path-based replacement.
  `--plan` remains available on every platform. (`1d6f28c`)
- **Restore streams and verifies its staging area**, and reports a checksum
  failure as a failure with a non-zero exit code rather than a warning.
  (`8eb3eef`, `9ae1bf8`)
- **Configured shell execution is explicit and opt-in.** A shell-mode project
  command now needs a trusted-shell opt-in that deliberately lives outside
  the configuration file, so somebody able to edit the configuration cannot
  grant themselves the right to run arbitrary shell code. (`7206a84`)
- **The worktree audit is read-only.** Probing a worktree no longer touches
  the filesystem, and the lock state is reported as `locked`, `unlocked` or
  `unknown` instead of being guessed. (`37899aa`, `85abb37`)
- **Orphan worktree deletion is verified before it happens.** A worktree is
  quarantined by an atomic rename to an unpredictable sibling, its directory
  entry identity is compared before and after the move, Git registration is
  queried again afterwards, and the recursive removal is confined to the
  quarantined entry. (`82202e6`, `a440815`, `fc5bd9a`)
- **Release workflow permissions are isolated**, and the third-party actions
  are pinned to verified full commit SHAs with the upstream version in a
  comment. (`66abc11`, `3e2551f`)
- **The Kanban archive no longer clobbers the live board**, and the archive
  no longer triggers a SQLite lock upgrade. (`2d060a0`, `5ca457e`)

### Fixed

- **Backup payloads are named collision-free.** Two sources with the same
  base name receive distinct payload paths, and each manifest entry records
  its own path and digest. The comparison is case-insensitive, because
  Windows and macOS volumes are. (`bdc7853`, `b1a13ea`)
- **Backup handles a read-only manifest and platform-specific error
  numbers.** The owner's write bit is added for the duration of the write and
  the original mode is restored afterwards, and the symbolic `errno`
  constant is used instead of a number that differs between Linux and macOS.
  (`d6c7d2c`, `ed29727`)
- **A failed maintenance stage is reported as a failure.** Every failed
  stage is visible in the report and the command exits non-zero. (`953943c`,
  `a69f714`)
- **`backup verify` no longer prints a traceback** for a missing or malformed
  manifest. It reports the failure as a single line, like the other
  commands, and prints its report on standard output. (`cddab1e`)
- **`kanban` no longer exits `1` on a healthy board.** The Kanban reports
  carry an explicit `ok` key, and a board that cannot be opened is listed in
  `unreadable_boards` rather than being hidden. (`cddab1e`)
- **The `loc` command no longer crashes.** A duplicate `cmd_kanban`
  definition was shadowing the real one, leaving unreachable code that
  referenced argument names the parser no longer used. (`cddab1e`)
- **False orphan process findings are avoided.** (`be8f58c`)

### Performance

- **The process scan runs in two phases.** A cheap first pass reads the
  process identifier, name and resident memory; a second pass opens only the
  candidates above the threshold and reads their metadata. A process whose
  command line or working directory cannot be read is still reported with a
  blank value rather than being dropped, and the Windows system processes
  `Memory Compression` and `Registry` remain excluded. (`33f9e00`)
- **Filesystem and audit scans share one walker.** A single iterative
  traversal in `core/fsscan.py` replaces repeated recursive walks, and the
  Android SDK and Docker sizes are computed from that one traversal instead of
  from a second pass over the same tree. The walker skips symbolic links and
  reparse points, tolerates unreadable entries, and applies the configured
  path-style exclusions. Audit work over the configured repositories and
  worktrees runs with bounded concurrency while preserving the reported
  ordering. (`9947d9f`)

### Documentation

- **The documentation was rebuilt.** `docs/index.md` is now the single entry
  point and reaches every document, `docs/architecture.md` describes the
  layers, the dependency direction, the execution flow and the safety model
  as they are implemented, and `docs/templates/` holds the reusable
  templates. The site is published with MkDocs and builds under `--strict`.
  The repository's documentation tests validate relative Markdown links; the
  strict site build checks the configured navigation and emitted pages.
  A CI job builds the site on every pull request. (`336a2bd`, `61245be`,
  `dd7c58f`)
- The documentation was audited and restructured: the README gained a table
  of contents, a quick start and a command table that lists every command the
  CLI exposes, and the configuration and environment sections moved into
  their own document. (`336a2bd`)
- The configuration reference now states that the `*.toml.example` files are
  illustrative and are never parsed, merged or read by any command.
  (`2ca5a90`)
- The worktree documentation no longer describes a dry-run option the
  command does not have, and the command name in it was corrected.
  (`b9e02a9`, `57ec8a6`)
- The backup documentation distinguishes `unsupported`, which means the
  filesystem positively reports that it cannot express the policy, from
  `failed`, which means the outcome could not be established at all.
  (`1e59ab7`)

### Internal

- The repository line endings were restored in the files that had been
  touched, so a pull-request diff shows content changes rather than
  whole-file rewrites. (`74f31fe`)
- Regression coverage was added for the fail-closed backup paths, the
  portable restore corruption injection, the worktree registration races and
  the shell consent environment. (`c312bf1`, `1a54743`, `132f83c`,
  `35e8284`, `2c24cee`, `55635d6`, and the restore corruption-injection
  series)

## [0.1.0] - 2026-10-15

The first tagged release. It introduced the toolkit itself: the system
diagnostic, the storage and process audits, the repository and Git identity
audits, the Git worktree audit, the Docker audit and cleanup, the Hermes
health check and database maintenance, the Android SDK cleanup planner, the
Kanban board health check, the project command runner, the backup and restore
path, the source line-count audit, the disk forecast and the daily health
report schedule. (`950deb0`)

[Unreleased]: https://github.com/vinhphan812/workstation-toolkit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/vinhphan812/workstation-toolkit/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/vinhphan812/workstation-toolkit/releases/tag/v0.1.0
