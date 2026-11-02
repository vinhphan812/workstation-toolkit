# Contributing

## Safety requirements

- New mutation paths must default to dry-run and require an explicit execution
  flag plus confirmation.
- Configured project commands are executable code. Prefer `{"argv": [...]}`
  so arguments are passed literally without a shell; `{"shell": "..."}`
  requires the operator to opt in with `--allow-shell` (or
  `WORKSTATION_ALLOW_SHELL=1`). The opt-in must not live in the project
  configuration.
- Do not add auto-delete, auto-kill, global PATH changes, Git identity
  writes, or credential handling without a narrowly scoped safety gate and
  tests.
- Local machine config belongs in ignored `config/*.json` files, never in
  committed examples.

## Branching and commits

- Branch from `main` with a descriptive prefix: `feat/`, `fix/`, `docs/` or
  `chore/`.
- One concern per pull request. A refactor and a behaviour change belong in
  separate pull requests.
- Every commit carries a `Signed-off-by` trailer:

  ```
  Signed-off-by: Vinh Phan <vinhphan812@gmail.com>
  ```

- Commit subjects use the imperative mood and stay under 72 characters. Use
  `type(scope): summary` where a scope applies, for example
  `fix(restore): report post-copy checksum mismatch as failure`.
- Do not rewrite published history. If a change needs correcting after it has
  been pushed, add a new commit.

## Pull requests

- The pull request body states what changed, why, and how it was verified.
  Paste the actual command output rather than a description of it.
- Every pull request is merged with a merge commit. Do not squash and do not
  rebase a branch that has already been pushed.
- The exact head commit must pass the required CI contexts before the merge:
  Windows, Ubuntu and macOS, each on Python 3.11 and Python 3.12.
- Merging uses an exact-head guard so that a commit pushed after the CI run
  cannot be merged unnoticed.

## Verification

Run these before opening a pull request:

```bash
python -m compileall -q src
python -m pytest -q
python -m workstation --help
```

Test adapters using mocks; platform-specific commands must return an explicit
unsupported/unavailable result when absent.

For a change that affects the command line, verify the behaviour by running
the command and capturing its output. A claim that a command works is not
evidence.

## Documentation standards

Documentation is written in **English (UK)**. Do not mix another language into
a document, a commit message, a pull-request title or a review comment.

- Every factual claim about the toolkit's behaviour must be verified against
  the source or the command's own `--help` output before it is written down.
  A claim that cannot be verified is not written as fact.
- Prefer a verifiable statement over an absolute one. "Fails closed on
  Windows" is verifiable; "is safe" is not.
- State the platform, the version and the exact command where a limitation
  applies.
- Do not document behaviour that the code does not implement, and do not
  remove documentation of behaviour that it does.

### What to update

A change to a command, a flag, a configuration key or a default must update
the documentation in the same pull request:

| Change | Documents to update |
|---|---|
| A command or flag | `README.md`, `docs/command-reference.md` |
| A configuration key or default | `README.md`, `docs/configuration.md` |
| A permission or safety policy | `README.md`, `docs/backup-permissions.md` |
| A release or workflow policy | `README.md`, `CHANGELOG.md` |

### Style

- Wrap prose at 80 columns. Fenced code blocks and tables may exceed it.
- Use sentence case for headings.
- Use British spelling: `behaviour`, `artefact`, `licence` (as a noun),
  `organisation`.
- Link between documents with relative paths, so the links work on GitHub and
  in a local checkout.
- Keep the table of contents in `README.md` in step with its headings.
