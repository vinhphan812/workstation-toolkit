# Contributing

## Safety requirements

- New mutation paths must default to dry-run and require an explicit execution flag plus confirmation.
- Configured project commands are executable code. Prefer `{"argv": [...]}` so arguments are passed literally without a shell; `{"shell": "..."}` requires the operator to opt in with `--allow-shell` (or `WORKSTATION_ALLOW_SHELL=1`). The opt-in must not live in the project configuration.
- Do not add auto-delete, auto-kill, global PATH changes, Git identity writes, or credential handling without a narrowly scoped safety gate and tests.
- Local machine config belongs in ignored `config/*.json` files, never in committed examples.

## Verification

```bash
python -m compileall -q src
python -m pytest -q
python -m workstation --help
```

Test adapters using mocks; platform-specific commands must return an explicit unsupported/unavailable result when absent.
