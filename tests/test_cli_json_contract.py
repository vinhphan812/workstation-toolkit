"""Regression tests for the machine-readable output contract.

The CLI is consumed by agents, which parse standard output. A command run
with `--json` must therefore put exactly one JSON document on standard
output and nothing else. The human-readable prose belongs on standard
error, where it does not corrupt the document.

The defect these tests cover: `--json` printed the prose first and the JSON
afterwards, so `json.loads(stdout)` raised `JSONDecodeError` for every
command whose output was not already JSON.
"""
import json
import sys

import pytest

import workstation.cli as cli


def _run(argv, monkeypatch, capsys):
    """Run the CLI and return (exit_code, stdout, stderr)."""
    monkeypatch.setattr(sys, 'argv', argv)
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, str):
            code = 1
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    captured = capsys.readouterr()
    return 0, captured.out, captured.err


@pytest.fixture()
def isolated_board(tmp_path, monkeypatch):
    """Create a minimal Kanban board and point HERMES_KANBAN_HOME at it."""
    import sqlite3
    board_root = tmp_path / 'board'
    board_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('HERMES_KANBAN_HOME', str(tmp_path))
    db = board_root / 'kanban.db'
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, completed_at INTEGER)')
    conn.commit()
    conn.close()
    return board_root


def test_json_mode_prints_only_the_json_document_on_stdout(
        isolated_board, monkeypatch, capsys):
    """`--json` must leave standard output parseable as one JSON document."""
    code, out, err = _run(['workstation', '--json', 'kanban'], monkeypatch, capsys)
    assert code == 0
    document = json.loads(out)
    assert document['ok'] is True


def test_json_mode_keeps_stdout_machine_readable_and_stderr_separate(
        isolated_board, monkeypatch, capsys):
    """Standard output must be JSON; other command output must stay separate."""
    code, out, err = _run(['workstation', '--json', 'kanban'], monkeypatch, capsys)
    assert code == 0
    assert json.loads(out)['ok'] is True
    # This command has no prose formatter, so stderr may be empty. If it emits
    # text in future, the stream redirect must keep it out of stdout.
    assert not err or not err.lstrip().startswith('{')


def test_json_mode_restores_standard_output_after_the_command(
        isolated_board, monkeypatch, capsys):
    """The stream swap must not leak into the next command."""
    import io
    before = sys.stdout
    _run(['workstation', '--json', 'kanban'], monkeypatch, capsys)
    assert sys.stdout is before, 'standard output must be restored'


def test_json_mode_leaves_no_extra_output_after_the_document(
        isolated_board, monkeypatch, capsys):
    """Nothing may follow the JSON document on standard output."""
    _, out, _ = _run(['workstation', '--json', 'kanban'], monkeypatch, capsys)
    decoder = json.JSONDecoder()
    _, end = decoder.raw_decode(out.lstrip())
    remainder = out.lstrip()[end:].strip()
    assert remainder == '', f'extra output after the JSON document: {remainder!r}'


def test_plain_mode_still_prints_the_report_on_stdout(
        isolated_board, monkeypatch, capsys):
    """Without `--json` the existing behaviour must not change."""
    code, out, _ = _run(['workstation', 'kanban'], monkeypatch, capsys)
    assert code == 0
    assert json.loads(out)['ok'] is True


def test_json_mode_saves_the_report_without_polluting_stdout(
        isolated_board, monkeypatch, capsys, tmp_path):
    """`--save-report` writes files and reports the paths without breaking the
    JSON contract."""
    import workstation.core.reporting as reporting
    monkeypatch.setattr(reporting, 'REPORTS_DIR', tmp_path / 'reports')
    code, out, err = _run(
        ['workstation', '--json', '--save-report', 'kanban'], monkeypatch, capsys)
    assert code == 0
    assert json.loads(out)['ok'] is True
    assert 'Reports:' in err


def test_json_mode_emits_a_single_document_for_formatted_report_commands(
        monkeypatch, capsys):
    """Commands with custom human formatters must not duplicate JSON output."""
    from types import SimpleNamespace
    import workstation.core.docker as docker
    monkeypatch.setattr(docker, 'get_state', lambda: SimpleNamespace(
        ok=True, containers=[], images=[], volumes=[]))
    code, out, _ = _run(['workstation', '--json', 'docker'], monkeypatch, capsys)
    assert code == 0
    assert json.loads(out)['ok'] is True


def test_json_mode_emits_a_single_document_for_loc(
        tmp_path, monkeypatch, capsys):
    """A formatter-backed LOC command must also honour the JSON contract."""
    source = tmp_path / 'module.py'
    source.write_text('value = 1\\n', encoding='utf-8')
    code, out, _ = _run(
        ['workstation', '--json', 'loc', '--path', str(tmp_path)],
        monkeypatch, capsys)
    assert code == 0
    document = json.loads(out)
    assert document['ok'] is True


def test_json_mode_emits_a_single_document_for_guard(
        monkeypatch, capsys):
    """The process guard must not print its own JSON ahead of the report."""
    import workstation.modules.guard_audit as guard
    monkeypatch.setattr(guard, 'scan_processes', lambda no_network=False: {
        'ok': True, 'items': [], 'network_scanned': not no_network})
    code, out, _ = _run(
        ['workstation', '--json', 'guard', 'scan', '--no-network'],
        monkeypatch, capsys)
    assert code == 0
    document = json.loads(out)
    assert document['ok'] is True


def test_json_mode_emits_a_single_document_for_process(
        monkeypatch, capsys):
    """Human process summaries must not contaminate JSON output."""
    from types import SimpleNamespace
    import workstation.core.process as process
    monkeypatch.setattr(process, 'list_processes', lambda threshold: [
        SimpleNamespace(ram_gb=1.0, name='demo', pid=123, cmdline='demo')])
    monkeypatch.setattr(process, 'is_process_orphaned', lambda proc: (False, ''))
    code, out, _ = _run(
        ['workstation', '--json', 'process', '--threshold', '10'],
        monkeypatch, capsys)
    assert code == 0
    assert json.loads(out)['processes'][0]['name'] == 'demo'
