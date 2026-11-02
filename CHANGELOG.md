# Changelog

All notable changes to this project are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A release is published by pushing a `v*` tag. The release workflow builds the
distribution and attaches it to the GitHub release for that tag. Release-tag
creation must be protected by repository rulesets or tag protection; see the
[Releases](README.md#releases) section of the README.

## [Unreleased]

### Added

- `docs/command-reference.md` — every command, flag and default, verified
  against the command's own `--help` output.
- `docs/configuration.md` — the configuration files, which command reads
  each one, and the environment-variable resolution order.
- `CHANGELOG.md` — this file.

### Changed

- `README.md` restructured with a table of contents, a quick-start section, a
  complete command table, and a separate configuration and
  environment-variable reference.
- `README.md` now documents `hermes-maintain`, `android-cleanup-plan` and
  `schedule`, which were previously undocumented.
- `CONTRIBUTING.md` now states the branch, commit and sign-off conventions,
  the merge and CI rules, and the documentation standards.

### Fixed

- `config/local.json` is now gitignored. The loader reads that filename, but
  only `config/local.toml` was ignored, so a device-local settings file
  could have been committed by accident.

## [0.1.0] — 2026-10-15

The first tagged release.

[Unreleased]: https://github.com/vinhphan812/workstation-toolkit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vinhphan812/workstation-toolkit/releases/tag/v0.1.0
