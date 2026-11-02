"""Tests for explicit, safer configured shell execution (issue #21)."""
from pathlib import Path
import subprocess
import sys
import pytest
import workstation.core.command_spec as command_spec
import workstation.modules.projects as projects
from workstation.core.command_spec import CommandConfigError, parse_command


def _project(tmp_path, commands, **extra):
    project = {'name': 'demo', 'path': str(tmp_path), 'commands': commands, 'timeouts': {}}
    project.update(extra)
    return project


def _use(monkeypatch, project):
    monkeypatch.setattr(projects, 'load_projects', lambda: [project])


# --- command_spec unit level ---------------------------------------------

def test_argv_command_is_parsed_without_a_shell():
    spec = parse_command({'argv': ['git', 'status', '--short']})
    assert spec.mode == 'argv'
    assert spec.argv == ('git', 'status', '--short')
    assert spec.requires_trusted_shell is False


def test_shell_command_requires_trusted_shell():
    spec = parse_command({'shell': 'git status | tee log.txt'})
    assert spec.mode == 'shell'
    assert spec.requires_trusted_shell is True


def test_legacy_string_without_shell_syntax_migrates_to_argv():
    spec = parse_command('python -m pytest')
    assert spec.mode == 'argv'
    assert spec.argv == ('python', '-m', 'pytest')


def test_legacy_string_with_shell_syntax_stays_shell():
    spec = parse_command('pytest && echo done')
    assert spec.mode == 'shell'
    assert spec.requires_trusted_shell is True


@pytest.mark.parametrize('value', [
    {'argv': []},
    {'argv': 'not-a-list'},
    {'argv': ['ok', 5]},
    {'argv': ['ok', '']},
    {'shell': ''},
    {'shell': 42},
    {'argv': ['a'], 'shell': 'b'},
    {},
    {'argv': ['a'], 'unknown': 1},
    42,
    ['a', 'b'],
])
def test_malformed_command_values_are_rejected(value):
    with pytest.raises(CommandConfigError):
        parse_command(value)


@pytest.mark.parametrize('value,expected', [
    ({'A': '1'}, {'A': '1'}),
    ({'A': 1}, {'A': '1'}),
    ({'A': True}, {'A': 'true'}),
])
def test_environment_values_are_normalised_to_strings(value, expected):
    assert command_spec.parse_environment(value) == expected


@pytest.mark.parametrize('value', [
    {'A': None},
    {'A': ['x']},
    {'A': {'b': 1}},
    {'=x': '1'},
    {'A\x00B': '1'},
])
def test_malformed_environment_values_are_rejected(value):
    with pytest.raises(CommandConfigError):
        command_spec.parse_environment(value)


def test_invalid_timeout_is_rejected():
    with pytest.raises(CommandConfigError):
        command_spec.parse_timeout({'test': 0}, 'test')
    with pytest.raises(CommandConfigError):
        command_spec.parse_timeout({'test': 'soon'}, 'test')


# --- plain-command tokenizing ---------------------------------------------

@pytest.mark.parametrize('text,expected', [
    ('python -m pytest', ['python', '-m', 'pytest']),
    ('  spaced   out  ', ['spaced', 'out']),
    ('echo "hello world"', ['echo', 'hello world']),
    ("echo 'single quoted'", ['echo', 'single quoted']),
    ('"C:\\Program Files\\My Tool\\tool.exe" --flag', ['C:\\Program Files\\My Tool\\tool.exe', '--flag']),
    ('echo "a" "b"', ['echo', 'a', 'b']),
    # An escaped quote is a literal quote character; it does not join the
    # words around it into one argument.
    ('echo say ' + chr(92) + '"hi' + chr(92) + '"', ['echo', 'say', '"hi"']),
])
def test_plain_command_is_split_without_interpretation(text, expected):
    assert command_spec.split_plain_command(text) == expected


def test_unquoted_path_with_spaces_splits_like_a_shell_would():
    # Quoting is what keeps a path in one argument; an unquoted path with
    # spaces splits on whitespace, exactly as a shell would split it.
    text = 'C:' + chr(92) + 'Program Files' + chr(92) + 'tool.exe --flag'
    assert command_spec.split_plain_command(text) == [
        'C:' + chr(92) + 'Program',
        'Files' + chr(92) + 'tool.exe',
        '--flag',
    ]


@pytest.mark.parametrize('text', ['', '   ', 'echo "unterminated'])
def test_unparseable_plain_commands_are_rejected(text):
    with pytest.raises(CommandConfigError):
        command_spec.split_plain_command(text)


@pytest.mark.parametrize('text', [
    'cmd && other',
    'cmd | other',
    'cmd > out.txt',
    'cmd < in.txt',
    'cmd $HOME',
    'cmd `whoami`',
    'cmd *',
    'cmd ?',
    'cmd ~',
    'cmd %PATH%',
    'cmd ^',
    'cmd (subshell)',
    'cmd [a]',
    'cmd {a}',
])
def test_strings_with_shell_syntax_are_detected(text):
    assert command_spec.contains_shell_syntax(text) is True


@pytest.mark.parametrize('text', [
    'python -m pytest',
    'git status --short',
    'echo "a && b"',
    "echo 'a | b'",
])
def test_strings_without_shell_syntax_are_not_detected(text):
    assert command_spec.contains_shell_syntax(text) is False


# --- execution behaviour ---------------------------------------------------

def test_project_command_defaults_to_dry_run(tmp_path, monkeypatch):
    _use(monkeypatch, _project(tmp_path, {'test': 'exit 1'}))
    report = projects.run_project_command('demo', 'test')
    assert report['ok'] is True
    assert report['dry_run'] is True
    assert report['command'] == 'exit 1'


def test_argv_metacharacters_are_passed_literally(tmp_path, monkeypatch):
    """A metacharacter-laden argument must not be interpreted by a shell."""
    marker = tmp_path / 'pwned.txt'
    payload = f'x & echo owned > {marker}'
    _use(monkeypatch, _project(tmp_path, {'test': {'argv': [sys.executable, '-c', 'import sys; print(sys.argv[1])', payload]}}))
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is True
    assert report['mode'] == 'argv'
    assert payload in report['output']
    assert not marker.exists(), 'shell metacharacters must not be interpreted'


def test_argv_mode_does_not_use_a_shell(tmp_path, monkeypatch):
    recorded = {}
    real_run = subprocess.run

    def spy(cmd, **kwargs):
        recorded['cmd'] = cmd
        recorded['kwargs'] = kwargs
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(projects.subprocess, 'run', spy)
    _use(monkeypatch, _project(tmp_path, {'test': {'argv': [sys.executable, '-c', 'print(1)']}}))
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is True
    assert recorded['kwargs']['shell'] is False
    assert isinstance(recorded['cmd'], list)


def test_shell_mode_is_refused_without_explicit_opt_in(tmp_path, monkeypatch):
    marker = tmp_path / 'pwned.txt'
    _use(monkeypatch, _project(tmp_path, {'test': {'shell': f'echo owned > "{marker}"'}}))
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is False
    assert report['requires_trusted_shell'] is True
    assert '--allow-shell' in report['error']
    assert not marker.exists(), 'shell command must not run without opt-in'


def test_shell_mode_runs_with_explicit_opt_in(tmp_path, monkeypatch):
    marker = tmp_path / 'ran.txt'
    _use(monkeypatch, _project(tmp_path, {'test': {'shell': f'echo owned > "{marker}"'}}))
    report = projects.run_project_command('demo', 'test', execute=True, allow_shell=True)
    assert report['ok'] is True
    assert report['mode'] == 'shell'
    assert marker.exists(), 'trusted shell command must actually run'


def test_shell_mode_opt_in_via_environment(tmp_path, monkeypatch):
    marker = tmp_path / 'ran.txt'
    monkeypatch.setenv(projects.ALLOW_SHELL_ENV, '1')
    _use(monkeypatch, _project(tmp_path, {'test': {'shell': f'echo owned > "{marker}"'}}))
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is True
    assert marker.exists()


def test_legacy_shell_string_requires_opt_in(tmp_path, monkeypatch):
    marker = tmp_path / 'pwned.txt'
    _use(monkeypatch, _project(tmp_path, {'test': f'echo owned > "{marker}"'}))
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is False
    assert report['mode'] == 'shell'
    assert report['requires_trusted_shell'] is True
    assert not marker.exists()


def test_legacy_plain_string_still_runs_without_shell(tmp_path, monkeypatch):
    # A legacy plain string is migrated to argv and executed without a shell.
    exe = sys.executable
    if ' ' in exe:
        exe = '"' + exe + '"'
    _use(monkeypatch, _project(tmp_path, {'test': exe + ' -c "print(1)"'}))
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is True
    assert report['mode'] == 'argv'
    assert report['source'] == 'legacy'
    assert '1' in report['output']


def test_invalid_command_configuration_is_reported(tmp_path, monkeypatch):
    _use(monkeypatch, _project(tmp_path, {'test': {'argv': ['ok', 5]}}))
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is False
    assert 'invalid configuration' in report['error']


def test_invalid_environment_configuration_is_reported(tmp_path, monkeypatch):
    _use(monkeypatch, _project(tmp_path, {'test': {'argv': ['echo', 'hi']}}, environment={'A': None}))
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is False
    assert 'invalid configuration' in report['error']


def test_environment_overrides_are_applied(tmp_path, monkeypatch):
    _use(monkeypatch, _project(tmp_path, {'test': {'argv': [sys.executable, '-c', 'import os; print(os.environ["WST_TEST_VAR"])']}}, environment={'WST_TEST_VAR': 'set-by-config'}))
    report = projects.run_project_command('demo', 'test', execute=True)
    assert report['ok'] is True
    assert 'set-by-config' in report['output']


def test_dry_run_reports_shell_mode_without_executing(tmp_path, monkeypatch):
    marker = tmp_path / 'pwned.txt'
    _use(monkeypatch, _project(tmp_path, {'test': {'shell': f'echo owned > "{marker}"'}}))
    report = projects.run_project_command('demo', 'test')
    assert report['ok'] is True
    assert report['dry_run'] is True
    assert report['mode'] == 'shell'
    assert report['requires_trusted_shell'] is True
    assert not marker.exists()


def test_project_status_reports_command_modes(tmp_path, monkeypatch):
    _use(monkeypatch, _project(tmp_path, {'test': {'argv': ['pytest']}, 'lint': {'shell': 'ruff check .'}}))
    report = projects.project_status('demo')
    assert report['projects'][0]['command_modes'] == {'test': 'argv', 'lint': 'shell'}


# --- shipped example configuration ----------------------------------------

def test_shipped_example_configuration_is_valid():
    import json
    from workstation.config import TOOLKIT_ROOT
    example = json.loads((TOOLKIT_ROOT / 'config' / 'projects.json.example').read_text())
    for project in example['projects']:
        for action, value in project['commands'].items():
            spec = parse_command(value)
            assert spec.mode == 'argv', f'example command {action!r} should use argv'
        command_spec.parse_environment(project.get('environment'))
        command_spec.parse_timeout(project.get('timeouts'), 'test')
