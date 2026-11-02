"""Regression tests for CLI exit codes and the `loc` command path.

Three defects are covered here. Each was found by running the command and
reading its exit code, not by reading the source.

* `loc --path PATH` raised `NameError: name 'Path' is not defined` after it
  had already printed the whole audit, so the command always ended in a
  traceback and exit code 1.
* `kanban` and `kanban --archive-plan DAYS` always exited 1, because the CLI
  checked a report key that the Kanban reports never had.
* `backup verify` on a missing manifest printed a raw Python traceback
  instead of a single-line error.
"""
import json
import sys
import time

import pytest

import workstation.cli as cli
import workstation.core.backup as backup
import workstation.modules.kanban as kanban


def _run(argv, monkeypatch, capsys):
    """Run the CLI and return (exit_code, stdout, stderr)."""
    monkeypatch.setattr(sys, 'argv', argv)
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, str):
            code = 1
        return code, capsys.readouterr().out, str(code)
    return 0, capsys.readouterr().out, ''


# --------------------------------------------------------------------------
# loc --path must not crash
# --------------------------------------------------------------------------

def test_loc_with_path_exits_zero(tmp_path, monkeypatch, capsys):
    """`loc --path` must complete and exit 0 on a readable directory."""
    (tmp_path / 'module.py').write_text(
        'def f():\n    return 1\n', encoding='utf-8')
    code, out, _ = _run(
        ['workstation', 'loc', '--path', str(tmp_path)], monkeypatch, capsys)
    assert code == 0, 'loc --path must exit 0, it raised an exception'


def test_loc_with_path_does_not_raise_name_error(tmp_path, monkeypatch, capsys):
    """The regression: `Path` was used in cmd_loc without being imported."""
    (tmp_path / 'module.py').write_text('x = 1\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv',
                        ['workstation', 'loc', '--path', str(tmp_path)])
    # A NameError would propagate out of cli.main() as a NameError, not as a
    # SystemExit, so this test fails loudly if the import is missing again.
    cli.main()


def test_loc_with_missing_path_reports_an_error(tmp_path, monkeypatch, capsys):
    """A path that does not exist must fail cleanly, with exit code 1."""
    missing = tmp_path / 'does-not-exist'
    code, _, _ = _run(
        ['workstation', 'loc', '--path', str(missing)], monkeypatch, capsys)
    assert code == 1


# --------------------------------------------------------------------------
# kanban must exit 0 when the health check succeeds
# --------------------------------------------------------------------------

def _isolated_board(tmp_path, monkeypatch, name='board'):
    """Create a minimal Kanban board and point HERMES_KANBAN_HOME at it."""
    board_root = tmp_path / name
    board_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('HERMES_KANBAN_HOME', str(tmp_path))
    return board_root


def test_kanban_health_exits_zero_when_every_board_is_readable(
        tmp_path, monkeypatch, capsys):
    """The regression: `kanban` always exited 1 because the report had no
    `ok` key, and the CLI treats a missing key as a failure."""
    import sqlite3
    board_root = _isolated_board(tmp_path, monkeypatch)
    db = board_root / 'kanban.db'
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, completed_at INTEGER)')
    conn.commit()
    conn.close()

    code, out, _ = _run(['workstation', 'kanban'], monkeypatch, capsys)
    assert code == 0, 'a healthy kanban board must exit 0'
    report = json.loads(out)
    assert report['ok'] is True


def test_kanban_health_report_carries_an_ok_key(tmp_path, monkeypatch, capsys):
    """The report must state its own outcome rather than relying on the
    absence of a key."""
    _isolated_board(tmp_path, monkeypatch)
    code, out, _ = _run(['workstation', 'kanban'], monkeypatch, capsys)
    report = json.loads(out)
    assert 'ok' in report, 'the kanban report must have an explicit ok key'
    assert report['ok'] is True


def test_kanban_archive_plan_exits_zero(tmp_path, monkeypatch, capsys):
    """`--archive-plan` is a read-only preview and must exit 0."""
    _isolated_board(tmp_path, monkeypatch)
    code, out, _ = _run(
        ['workstation', 'kanban', '--archive-plan', '30'], monkeypatch, capsys)
    assert code == 0, 'a read-only archive plan must exit 0'
    report = json.loads(out)
    assert report['ok'] is True
    assert report['execute'] is False if 'execute' in report else True


def test_kanban_archive_plan_does_not_mutate(tmp_path, monkeypatch, capsys):
    """The plan must stay read-only whatever its exit code."""
    import sqlite3
    board_root = _isolated_board(tmp_path, monkeypatch)
    db = board_root / 'kanban.db'
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, completed_at INTEGER)')
    conn.execute("INSERT INTO tasks VALUES ('t1', 'done', ?)",
                 (int(time.time()) - 86400 * 60,))
    conn.commit()
    conn.close()

    _run(['workstation', 'kanban', '--archive-plan', '30'], monkeypatch, capsys)
    conn = sqlite3.connect(db)
    count = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    conn.close()
    assert count == 1, 'the archive plan must not delete anything'


def test_kanban_health_reports_an_unreadable_board_as_not_ok(
        tmp_path, monkeypatch, capsys):
    """A board that cannot be read must make the overall result not-ok, so
    the exit code reflects it instead of reporting a clean health check."""
    board_root = tmp_path / 'broken'
    board_root.mkdir(parents=True)
    # A file where the database is expected: sqlite cannot open it.
    (board_root / 'kanban.db').write_text('not a database', encoding='utf-8')
    monkeypatch.setenv('HERMES_KANBAN_HOME', str(tmp_path))

    code, out, _ = _run(['workstation', 'kanban'], monkeypatch, capsys)
    report = json.loads(out)
    assert report['ok'] is False, 'an unreadable board must not report ok'
    assert code == 1, 'an unreadable board must exit 1'


def test_kanban_health_reports_unavailable_boards_root(tmp_path, monkeypatch, capsys):
    """A missing boards root is a failure, not a success."""
    monkeypatch.setenv('HERMES_KANBAN_HOME', str(tmp_path / 'nope'))
    code, out, _ = _run(['workstation', 'kanban'], monkeypatch, capsys)
    report = json.loads(out)
    assert report['ok'] is False
    assert report['status'] == 'unavailable'
    assert code == 1


# --------------------------------------------------------------------------
# backup verify must not print a traceback
# --------------------------------------------------------------------------

def test_backup_verify_reports_a_missing_manifest_cleanly(
        tmp_path, monkeypatch, capsys):
    """The regression: a missing manifest raised FileNotFoundError out of
    cli.main(), producing an 18-line traceback."""
    missing = tmp_path / 'no-such-manifest.json'
    monkeypatch.setattr(sys, 'argv',
                        ['workstation', 'backup', 'verify', str(missing)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    captured = capsys.readouterr()
    assert 'Traceback' not in captured.err, (
        'a missing manifest must produce a clean error, not a traceback')
    assert 'FileNotFoundError' not in captured.err
    assert exc.value.code != 0, 'a missing manifest must fail'


def test_backup_verify_reports_a_corrupt_manifest_cleanly(
        tmp_path, monkeypatch, capsys):
    """A malformed manifest must also fail cleanly."""
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{not json', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv',
                        ['workstation', 'backup', 'verify', str(manifest)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    captured = capsys.readouterr()
    assert 'Traceback' not in captured.err
    assert exc.value.code != 0


def _make_backup(tmp_path, monkeypatch):
    """Create a real backup and return the path to its manifest."""
    monkeypatch.setattr(backup, 'BACKUPS_DIR', tmp_path / 'backups')
    source = tmp_path / 'source.txt'
    source.write_text('content', encoding='utf-8')
    result = backup.backup_files('test', [str(source)])
    return result['manifest']


def test_backup_verify_of_a_valid_manifest_exits_zero(
        tmp_path, monkeypatch, capsys):
    """A valid manifest still verifies and exits 0."""
    manifest_path = _make_backup(tmp_path, monkeypatch)
    code, out, _ = _run(
        ['workstation', 'backup', 'verify', manifest_path],
        monkeypatch, capsys)
    assert code == 0, 'a valid manifest must verify with exit 0'


def test_backup_verify_prints_its_report(tmp_path, monkeypatch, capsys):
    """The verification result must be visible on stdout, not only when
    --json is passed."""
    manifest_path = _make_backup(tmp_path, monkeypatch)
    code, out, _ = _run(
        ['workstation', 'backup', 'verify', manifest_path],
        monkeypatch, capsys)
    assert json.loads(out)['ok'] is True


def test_backup_verify_of_a_corrupt_payload_exits_one(
        tmp_path, monkeypatch, capsys):
    """A payload that no longer matches its digest must fail with exit 1."""
    manifest_path = _make_backup(tmp_path, monkeypatch)
    manifest = json.loads(open(manifest_path, encoding='utf-8').read())
    payload = backup.Path(manifest['files'][0]['backup'])
    payload.write_bytes(b'corrupt')
    code, out, _ = _run(
        ['workstation', 'backup', 'verify', manifest_path],
        monkeypatch, capsys)
    assert code == 1, 'a checksum mismatch must exit 1'
    assert json.loads(out)['ok'] is False
