# Contributing

## Safety requirements

- New mutation paths must default to dry-run and require an explicit execution flag plus confirmation.
- Do not add auto-delete, auto-kill, global PATH changes, Git identity writes, or credential handling without a narrowly scoped safety gate and tests.
- Local machine config belongs in ignored `config/*.json` files, never in committed examples.

## Verification

```bash
python -m compileall -q src
python -m pytest -q
python -m workstation --help
```

Test adapters using mocks; platform-specific commands must return an explicit unsupported/unavailable result when absent.
