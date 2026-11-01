"""CLI wiring tests for explicit configured shell execution (issue #21)."""
import json
import sys
import pytest
import workstation.cli as cli
import workstation.modules.projects as projects


def _use(monkeypatch, project):
    monkeypatch.setattr(projects, 'load_projects', lambda: [project])


def _run(argv, capsys, monkeypatch):
    monkeypatch.setattr(sys, 'argv', argv)
    cli.main()
    return json.loads(capsys.readouterr().out)


def test_cli_rejects_shell_command_without_allow_shell(tmp_path, monkeypatch, capsys):
    marker = tmp_path / 'pwned.txt'
    _use(monkeypatch, {'name': 'demo', 'path': str(tmp_path), 'commands': {'test': {'shell': f'echo owned > "{marker}"'}}, 'timeouts': {}})
    with pytest.raises(SystemExit) as exc:
        _run(['workstation', 'project', 'demo', 'test', '--execute'], capsys, monkeypatch)
    assert exc.value.code == 1
    assert not marker.exists(), 'shell command must not run without --allow-shell'


def test_cli_runs_shell_command_with_allow_shell(tmp_path, monkeypatch, capsys):
    marker = tmp_path / 'ran.txt'
    _use(monkeypatch, {'name': 'demo', 'path': str(tmp_path), 'commands': {'test': {'shell': f'echo owned > "{marker}"'}}, 'timeouts': {}})
    report = _run(['workstation', 'project', 'demo', 'test', '--execute', '--allow-shell'], capsys, monkeypatch)
    assert report['ok'] is True
    assert marker.exists()


def test_cli_dry_run_reports_command_mode(tmp_path, monkeypatch, capsys):
    _use(monkeypatch, {'name': 'demo', 'path': str(tmp_path), 'commands': {'test': {'argv': ['pytest']}, 'lint': {'shell': 'ruff check .'}}, 'timeouts': {}})
    report = _run(['workstation', 'project', 'demo', 'test'], capsys, monkeypatch)
    assert report['dry_run'] is True
    assert report['mode'] == 'argv'


def test_cli_shell_opt_in_from_environment(tmp_path, monkeypatch, capsys):
    marker = tmp_path / 'ran-from-environment.txt'
    _use(monkeypatch, {'name': 'demo', 'path': str(tmp_path), 'commands': {'test': {'shell': f'echo owned > "{marker}"'}}, 'timeouts': {}})
    monkeypatch.setenv('WORKSTATION_ALLOW_SHELL', '1')
    report = _run(['workstation', 'project', 'demo', 'test', '--execute'], capsys, monkeypatch)
    assert report['ok'] is True
    assert marker.exists()
