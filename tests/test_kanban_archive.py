"""Tests for real Kanban archiving — uses SQLite kanban.db format."""
import json, os, sqlite3, time, pytest
from pathlib import Path
from workstation.modules.kanban import archive_tasks, archive_plan


def _make_board(tmp_path, name, tasks):
    """Create a kanban.db with tasks under HERMES_KANBAN_HOME/<name>."""
    board_root = tmp_path / name
    board_root.mkdir(parents=True)
    db = board_root / 'kanban.db'
    conn = sqlite3.connect(db)
    conn.execute('PRAGMA journal_mode=DELETE')
    conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY, title TEXT, body TEXT, status TEXT,
        created_at INTEGER, updated_at INTEGER, completed_at INTEGER, metadata TEXT)""")
    now = int(time.time())
    for t in tasks:
        conn.execute(
            "INSERT INTO tasks (id,title,body,status,created_at,updated_at,completed_at,metadata)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (t['id'], t.get('title', ''), t.get('body', ''), t.get('status', 'todo'),
             now - 86400 * 10, now - 86400 * 5, t.get('completed_at', now - 86400),
             json.dumps(t.get('metadata', {}))))
    conn.commit()
    conn.close()
    return board_root


def test_archive_is_dry_run_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_KANBAN_HOME', str(tmp_path))
    board = _make_board(tmp_path, 'testboard', [
        {'id': 't001', 'status': 'done',
         'completed_at': int(time.time()) - 86400 * 60},
    ])
    result = archive_tasks(30)
    assert result['execute'] is False
    assert result['archived_count'] == 1
    assert result['results'][0]['action'] == 'dry_run'
    conn = sqlite3.connect(board / 'kanban.db')
    count = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    conn.close()
    assert count == 1


def test_archive_removes_from_db_when_execute(tmp_path, monkeypatch):
    # Use a temp path OUTSIDE the real kanban tree so archive_plan only
    # sees our test board and doesn't open the 7 production board DBs.
    isolated = tmp_path / 'boards'
    isolated.mkdir()
    monkeypatch.setenv('HERMES_KANBAN_HOME', str(isolated))
    board = _make_board(isolated, 'testboard', [
        {'id': 't002', 'status': 'done',
         'completed_at': int(time.time()) - 86400 * 60},
    ])
    result = archive_tasks(30, execute=True, yes=True)
    assert result['execute'] is True
    assert result['archived_count'] == 1
    conn = sqlite3.connect(board / 'kanban.db')
    count = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    conn.close()
    assert count == 0
    archive_files = list((board / 'archive').rglob('t002.json'))
    assert len(archive_files) == 1
    archived = json.loads(archive_files[0].read_text())
    assert archived['id'] == 't002'


def test_archive_filters_to_one_board(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_KANBAN_HOME', str(tmp_path))
    _make_board(tmp_path, 'board-a', [{'id': 'ta', 'status': 'done',
         'completed_at': int(time.time()) - 86400 * 60}])
    _make_board(tmp_path, 'board-b', [{'id': 'tb', 'status': 'done',
         'completed_at': int(time.time()) - 86400 * 60}])
    result = archive_tasks(30, board='board-a', execute=True, yes=True)
    assert result['board'] == 'board-a'
    assert result['archived_count'] == 1
    assert result['results'][0]['task_id'] == 'ta'


def test_archive_skips_recent_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_KANBAN_HOME', str(tmp_path))
    _make_board(tmp_path, 'recent-board', [
        {'id': 't-recent', 'status': 'done',
         'completed_at': int(time.time()) - 86400 * 5}])
    result = archive_tasks(30)
    assert result['archived_count'] == 0


def test_archive_plan_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_KANBAN_HOME', str(tmp_path))
    board = _make_board(tmp_path, 'plan-board', [
        {'id': 't003', 'status': 'done',
         'completed_at': int(time.time()) - 86400 * 60}])
    plan = archive_plan(30)
    board_entry = next((b for b in plan['boards'] if b['board'] == 'plan-board'), None)
    assert board_entry is not None
    assert board_entry['count'] == 1
    conn = sqlite3.connect(board / 'kanban.db')
    count = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    conn.close()
    assert count == 1
