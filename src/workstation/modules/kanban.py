"""Read-only Kanban board health and archive planning."""
from __future__ import annotations
import os, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from workstation.config import get_hermes_home


def _boards_root() -> Path:
    return Path(os.environ.get('HERMES_KANBAN_HOME') or Path(get_hermes_home()).parent.parent / 'kanban' / 'boards')


def kanban_health() -> dict:
    root = _boards_root()
    boards = []
    if not root.is_dir():
        return {'status': 'unavailable', 'boards_root': str(root), 'boards': []}
    for board in sorted(path for path in root.iterdir() if path.is_dir()):
        db = board / 'kanban.db'
        if not db.is_file():
            continue
        board_info = {'name': board.name, 'database': str(db), 'size_mb': round(db.stat().st_size/(1024**2),2),
                      'wal_mb': round(_size(Path(str(db)+'-wal'))/(1024**2),2), 'integrity': None, 'statuses': {}, 'done_before_cutoff': 0}
        try:
            conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=2)
            conn.execute('pragma busy_timeout=2000')
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
    return {'status': 'available', 'boards_root': str(root), 'boards': boards}


def archive_plan(days: int = 30) -> dict:
    """Generate a read-only candidate plan; no task data is mutated."""
    health = kanban_health()
    cutoff = int(datetime.now(timezone.utc).timestamp()) - days*24*60*60
    candidates = []
    for board in health.get('boards', []):
        try:
            conn = sqlite3.connect(f"file:{board['database']}?mode=ro", uri=True, timeout=2)
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
