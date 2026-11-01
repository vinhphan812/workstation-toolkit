import pytest
import workstation.modules.projects as projects


def test_project_command_defaults_to_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, 'load_projects', lambda: [{
        'name': 'demo', 'path': str(tmp_path), 'commands': {'test': ['python', '-c', 'raise SystemExit(1)']}, 'timeouts': {}
    }])
    report = projects.run_project_command('demo', 'test')
    assert report['ok'] is True
    assert report['dry_run'] is True


def test_argv_command_passes_metacharacters_literally(tmp_path, monkeypatch):
    marker = tmp_path / 'should-not-exist'
    command = ['python', '-c', 'import sys; print(sys.argv[1])', f'; touch {marker}']
    monkeypatch.setattr(projects, 'load_projects', lambda: [{
        'name': 'demo', 'path': str(tmp_path), 'commands': {'test': command}, 'timeouts': {}
    }])
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is True
    assert report['output'].strip() == f'; touch {marker}'
    assert not marker.exists()


def test_shell_command_requires_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, 'load_projects', lambda: [{
        'name': 'demo', 'path': str(tmp_path), 'commands': {'test': 'echo unsafe'}, 'timeouts': {}
    }])
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is False
    assert 'trusted_shell' in report['error']


def test_shell_command_runs_with_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, 'load_projects', lambda: [{
        'name': 'demo', 'path': str(tmp_path), 'trusted_shell': True,
        'commands': {'test': 'echo trusted'}, 'timeouts': {}
    }])
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is True
    assert report['output'].strip() == 'trusted'


def test_malformed_command_is_rejected_even_in_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, 'load_projects', lambda: [{
        'name': 'demo', 'path': str(tmp_path), 'commands': {'test': ['python', 3]}, 'timeouts': {}
    }])
    report = projects.run_project_command('demo', 'test')
    assert report['ok'] is False
    assert 'command must' in report['error']


def test_malformed_environment_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, 'load_projects', lambda: [{
        'name': 'demo', 'path': str(tmp_path), 'environment': {'X': 1},
        'commands': {'test': ['python', '-c', 'pass']}, 'timeouts': {}
    }])
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is False
    assert 'environment' in report['error']


@pytest.mark.parametrize('timeout', [0, -1, True, '5', None])
def test_malformed_timeout_is_rejected(tmp_path, monkeypatch, timeout):
    monkeypatch.setattr(projects, 'load_projects', lambda: [{
        'name': 'demo', 'path': str(tmp_path), 'commands': {'test': ['python', '-c', 'pass']},
        'timeouts': {'test': timeout}
    }])
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is False
    assert 'timeout' in report['error']
