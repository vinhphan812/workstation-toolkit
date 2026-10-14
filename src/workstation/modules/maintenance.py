"""Backup/restore and Hermes SQLite maintenance, all explicit and guarded."""
from __future__ import annotations
import json, os, shutil, sqlite3, subprocess
from pathlib import Path
from workstation.config import TOOLKIT_ROOT, get_hermes_profile, get_hermes_home
from workstation.core.backup import backup_files
from workstation.core.safety import require_execute, require_free_space


def default_backup_targets() -> list[str]:
    profile = Path(get_hermes_profile())
    config = TOOLKIT_ROOT / 'config'
    targets = [profile / 'state.db', config / 'repos.json', config / 'projects.json']
    return [str(path) for path in targets if path.exists()]


def create_backup(label: str = 'workstation') -> dict:
    return backup_files(label, default_backup_targets())


def restore_backup(manifest_path: str, execute: bool = False, yes: bool = False) -> dict:
    require_execute(execute, yes, 'restore')
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    restored, skipped = [], []
    for entry in manifest.get('files', []):
        if entry.get('status') != 'backed_up':
            skipped.append(entry)
            continue
        source, backup = Path(entry['source']), Path(entry['backup'])
        if not backup.is_file():
            skipped.append({**entry, 'reason': 'backup missing'})
            continue
        from workstation.core.backup import _sha256
        expected = entry.get('sha256')
        actual = _sha256(backup)
        if expected and actual != expected:
            skipped.append({**entry, 'reason': 'checksum mismatch', 'actual_sha256': actual})
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, source)
        if expected and _sha256(source) != expected:
            skipped.append({**entry, 'reason': 'post-copy checksum mismatch'})
            continue
        restored.append(str(source))
    return {'restored': restored, 'skipped': skipped}


def hermes_db_maintenance(execute: bool = False, yes: bool = False, min_free_gb: float = 15.0) -> dict:
    """Plan or execute backup → WAL checkpoint → quick_check → optimize.

    Does not stop Hermes itself. A busy database is reported; it is never
    force-unlocked or copied unsafely.
    """
    profile = Path(get_hermes_profile())
    db = profile / 'state.db'
    if not db.is_file():
        return {'ok': False, 'error': f'state.db missing: {db}'}
    before_mb = round(db.stat().st_size/(1024**2), 2)
    plan = ['backup state.db/config', 'SQLite WAL checkpoint(TRUNCATE)', 'PRAGMA quick_check(1)', 'Hermes sessions optimize --force', 'post-check size + quick_check']
    if not execute:
        return {'ok': True, 'dry_run': True, 'database': str(db), 'size_before_mb': before_mb, 'required_free_gb': min_free_gb, 'plan': plan}
    require_execute(execute, yes, 'Hermes database maintenance')
    free_gb = require_free_space(db, min_free_gb)
    backup = backup_files('hermes_state_before_maintenance', [str(db), str(Path(str(db)+'-wal')), str(Path(str(db)+'-shm'))])
    result = {'ok': True, 'dry_run': False, 'backup': backup, 'free_before_gb': free_gb, 'size_before_mb': before_mb, 'checkpoint': None, 'quick_check_before': None, 'optimize_exit': None, 'quick_check_after': None}
    try:
        conn = sqlite3.connect(db, timeout=10)
        conn.execute('PRAGMA busy_timeout=10000')
        result['quick_check_before'] = conn.execute('PRAGMA quick_check(1)').fetchone()[0]
        result['checkpoint'] = list(conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())
        conn.close()
    except Exception as exc:
        result.update({'ok': False, 'error': f'SQLite preflight/checkpoint failed: {exc}'})
        return result
    try:
        process = subprocess.run(['hermes', 'sessions', 'optimize', '--force'], capture_output=True, text=True, timeout=900)
        result['optimize_exit'] = process.returncode
        result['optimize_output'] = (process.stdout + process.stderr)[-6000:]
    except Exception as exc:
        result.update({'ok': False, 'error': f'optimize failed: {exc}'})
        return result
    try:
        conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
        result['quick_check_after'] = conn.execute('PRAGMA quick_check(1)').fetchone()[0]
        conn.close()
        result['size_after_mb'] = round(db.stat().st_size/(1024**2), 2)
    except Exception as exc:
        result.update({'ok': False, 'error': f'post-check failed: {exc}'})
    return result


def print_maintenance(report: dict) -> None:
    print('\n=== Hermes DB Maintenance ===')
    print(json.dumps(report, indent=2, default=str))
