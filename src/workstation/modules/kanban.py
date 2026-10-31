"""Kanban board health, archive planning, and selective archiving."""
from __future__ import annotations
import json, os, shutil, sqlite3, tempfile

from datetime import datetime, timezone
from pathlib import Path
from workstation.config import get_hermes_home
from workstation.core.safety import require_execute


def _boards_root() -> Path:
    """Return the Kanban boards root.

    When HERMES_KANBAN_HOME is set it is used directly (isolated test
    environments).  Otherwise the default path is derived from the Hermes
    profile home.
    """
    if 'HERMES_KANBAN_HOME' in os.environ:
        return Path(os.environ['HERMES_KANBAN_HOME'])
    return Path(get_hermes_home()).parent.parent / 'kanban' / 'boards'


def _board_db_paths(boards_root: Path) -> list[tuple[Path, Path]]:
    """Yield (board_name, db_path) for boards that have a kanban.db."""
    if not boards_root.is_dir():
        return []
    results = []
    for board in sorted(boards_root.iterdir()):
        if board.is_dir():
            db = board / 'kanban.db'
            if db.is_file():
                results.append((board, db))
    return results


def kanban_health() -> dict:
    boards_root = _boards_root()
    boards = []
    if not boards_root.is_dir():
        return {'status': 'unavailable', 'boards_root': str(boards_root), 'boards': []}
    for board, db in _board_db_paths(boards_root):
        board_info = {'name': board.name, 'database': str(db), 'size_mb': round(db.stat().st_size/(1024**2),2),
                      'wal_mb': round(_size(Path(str(db)+'-wal'))/(1024**2),2), 'integrity': None, 'statuses': {}, 'done_before_cutoff': 0}
        try:
            conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
            conn.execute('pragma busy_timeout=30000')
            board_info['integrity'] = conn.execute('pragma quick_check(1)').fetchone()[0]
            table_exists = conn.execute("select 1 from sqlite_master where type='table' and name='tasks'").fetchone()
            if not table_exists:
                board_info['integrity'] = 'ok (no tasks table; metadata-only board)'
                conn.close()
                boards.append(board_info)
                continue
            board_info['statuses'] = dict(conn.execute('select status, count(*) from tasks group by status'))
            cutoff = int(datetime.now(timezone.utc).timestamp()) - 30*24*60*60
            board_info['done_before_cutoff'] = conn.execute('select count(*) from tasks where status = ? and completed_at is not null and completed_at < ?', ('done', cutoff)).fetchone()[0]
            conn.close()
        except Exception as exc:
            board_info['integrity'] = f'unavailable: {exc}'
        boards.append(board_info)
    return {'status': 'available', 'boards_root': str(boards_root), 'boards': boards}


def archive_plan(days: int = 30) -> dict:
    """Generate a read-only candidate plan; no task data is mutated."""
    health = kanban_health()
    cutoff = int(datetime.now(timezone.utc).timestamp()) - days*24*60*60
    candidates = []
    for board in health.get('boards', []):
        try:
            conn = sqlite3.connect(f"file:{board['database']}?mode=ro", uri=True, timeout=30)
            has_tasks = conn.execute("select 1 from sqlite_master where type='table' and name='tasks'").fetchone()
            if not has_tasks:
                conn.close()
                candidates.append({'board': board['name'], 'count': 0, 'tasks': [], 'note': 'metadata-only board'})
                continue
            rows = conn.execute('select id, title, completed_at from tasks where status=? and completed_at is not null and completed_at < ? order by completed_at', ('done', cutoff)).fetchall()
            conn.close()
            candidates.append({'board': board['name'], 'count': len(rows), 'tasks': [{'id': row[0], 'title': row[1], 'completed_at': row[2]} for row in rows]})
        except Exception as exc:
            candidates.append({'board': board['name'], 'error': str(exc), 'count': 0, 'tasks': []})
    return {'days': days, 'cutoff_epoch': cutoff, 'boards': candidates,
            'safety': 'Plan only. Archive implementation must export JSON and require explicit confirmation per board.'}


def _size(path: Path) -> int:
    try: return path.stat().st_size
    except OSError: return 0


def print_kanban_health(report: dict) -> None:
    print('\n=== Kanban Health ===')
    print(f"Boards root: {report.get('boards_root')}")
    for item in report.get('boards', []):
        print(f"  {item['name']}: {item['size_mb']} MB; WAL={item['wal_mb']} MB; integrity={item['integrity']}; done>30d={item['done_before_cutoff']}")


def print_archive_plan(plan: dict) -> None:
    print(f"\n=== Kanban Archive Plan (done > {plan['days']} days) ===")
    for board in plan['boards']:
        print(f"  {board['board']}: {board['count']} candidates")


def _archive_task(board_name: str, task_id: str, execute: bool = False) -> dict:
    """Read all columns from the actual kanban tasks table, export to JSON under
    <board>/archive/YYYY-MM/, and DELETE from live DB when execute=True."""
    board_root = _boards_root() / board_name
    db = board_root / 'kanban.db'
    # Reserve the write lock before reading to avoid a DELETE-journal lock
    # upgrade race between export and deletion.
    conn = sqlite3.connect(db, timeout=30, isolation_level=None)
    conn.execute('PRAGMA busy_timeout=30000')
    try:
        conn.execute('BEGIN IMMEDIATE')
        cur = conn.execute('SELECT * FROM tasks WHERE id=? LIMIT 1', (task_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return {'task_id': task_id, 'skipped': True, 'reason': 'not found in database'}
        task = dict(zip(cols, row))
        done_ts = task.get('completed_at')
        year_month = datetime.fromtimestamp(done_ts, tz=timezone.utc).strftime('%Y-%m') if done_ts else 'unknown'
        archive_dir = board_root / 'archive' / year_month
        archive_file = archive_dir / f'{task_id}.json'
        if not execute:
            conn.rollback()
            return {'task_id': task_id, 'action': 'dry_run', 'destination': str(archive_file)}
        archive_dir.mkdir(parents=True, exist_ok=True)
        # Fail closed for existing regular files and symlinks.
        if archive_file.exists() or archive_file.is_symlink():
            conn.rollback()
            return {'task_id': task_id, 'skipped': True, 'reason': 'archive destination already exists', 'destination': str(archive_file)}
        fd, temp_name = tempfile.mkstemp(prefix=f'.{task_id}.', suffix='.tmp', dir=archive_dir)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump(task, fh, indent=2, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            with temp_path.open(encoding='utf-8') as fh:
                archived_task = json.load(fh)
            if not isinstance(archived_task, dict) or archived_task.get('id') != task_id:
                raise ValueError('archive verification failed: task id mismatch')
            # Hard-link publication is atomic and refuses a destination race.
            os.link(temp_path, archive_file)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        conn.execute('DELETE FROM tasks WHERE id=?', (task_id,))
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    return {'task_id': task_id, 'archived_to': str(archive_file)}


def archive_tasks(days: int = 30, board: str | None = None,
                  execute: bool = False, yes: bool = False) -> dict:
    """Export done tasks older than `days` to per-month JSON archives and remove
    them from the live database.

    Safety model:
      - Always requires explicit --execute and --yes flags.
      - Reads live DB but writes archive JSON + DELETE in a single transaction
        per task; safe to interrupt.
      - Never deletes the board database or the archive directory.
    """
    if execute:
        require_execute(execute, yes, 'Kanban archive')
    plan = archive_plan(days)
    archived, skipped = [], []
    for board_entry in plan['boards']:
        bname = board_entry['board']
        if board and bname != board:
            continue
        for task_info in board_entry.get('tasks', []):
            result = _archive_task(bname, task_info['id'], execute=execute)
            if execute:
                if result.get('skipped'):
                    skipped.append(result)
                else:
                    archived.append(result)
            else:
                archived.append(result)
    return {
        'days': days,
        'board': board,
        'execute': execute,
        'archived_count': len(archived),
        'skipped_count': len(skipped),
        'results': archived + skipped,
    }
