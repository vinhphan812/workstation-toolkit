# Changelog template

Copy this file to the repository root as `CHANGELOG.md` and replace the
placeholders. The live changelog for this project is at
[CHANGELOG.md](../../CHANGELOG.md).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Rules

1. **Every release gets a section.** The section heading is `## [X.Y.Z] - YYYY-MM-DD`,
   with the release date in ISO 8601 format.
2. **Unreleased work stays under `## [Unreleased]`.** Move an entry into a
   release section when the tag is pushed, never before.
3. **Categories are fixed.** Use `Added`, `Changed`, `Deprecated`, `Removed`,
   `Fixed`, `Security`, `Performance`, `Documentation` and `Internal`. Keep a
   category only when it has entries.
4. **Write selected notable changes, not a commit ledger.** Describe changes
   a user of the toolkit can observe. Routine test-only follow-ups may be
   omitted; do not claim every commit is listed or state a commit count unless
   the count and the full hash coverage are automatically verified. Add the
   relevant commit hash in parentheses for traceability.
5. **One bullet is one change.** A bullet that needs "and" is usually two
   bullets.
6. **Link the comparison** at the foot of the file. The `[Unreleased]` link
   compares the newest tag with `HEAD`; a release link compares the previous
   tag with the new one.

## Structure

```markdown
# Changelog

All notable changes to this project are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A new capability the user can invoke. (`abcdef1`)

### Changed

- An existing behaviour that now works differently. (`abcdef1`)

### Fixed

- A defect that made the toolkit behave incorrectly. (`abcdef1`)

## [0.1.0] - YYYY-MM-DD

The first tagged release.

[Unreleased]: https://github.com/OWNER/REPO/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/REPO/releases/tag/v0.1.0
```

## Section checklist

| Check | Rule |
|---|---|
| Heading format | `## [X.Y.Z] - YYYY-MM-DD` |
| Date format | ISO 8601, not a prose date |
| Link references | Every version heading has a matching link at the foot |
| Ordering | Newest release first, `Unreleased` above them |
| Traceability | Each bullet ends with its commit hash in parentheses |
| Spelling | British English, matching the rest of the documentation |

## Related

- [Documentation index](../index.md)
- [Architecture template](architecture_template.md)
- [Template library index](index.md)
- [Contributing](../../CONTRIBUTING.md)
