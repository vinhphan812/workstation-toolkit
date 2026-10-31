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
    """Restore only well-formed entries confined to their manifest backup folder.

    ``source`` is an absolute original path in manifests emitted by
    :func:`backup_files`; ``backup`` must remain inside the manifest directory.
    """
    require_execute(execute, yes, 'restore')
    manifest_file = Path(manifest_path).resolve(strict=True)
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list):
        raise ValueError("Invalid backup manifest: 'files' must be a list")
    restored, skipped = [], []
    backup_root = manifest_file.parent.resolve(strict=True)
    for index, entry in enumerate(manifest['files']):
        if not isinstance(entry, dict):
            raise ValueError(f'Invalid backup manifest entry {index}: expected object')
        status = entry.get('status')
        if not isinstance(status, str):
            raise ValueError(f"Invalid backup manifest entry {index}: 'status' must be a string")
        if status != 'backed_up':
            if status != 'missing':
                raise ValueError(f"Invalid backup manifest entry {index}: unsupported status {status!r}")
            source_value = entry.get('source')
            if not isinstance(source_value, str) or not source_value:
                raise ValueError(f"Invalid backup manifest entry {index}: invalid source")
            skipped.append(entry)
            continue
        source_value, backup_value = entry.get('source'), entry.get('backup')
        if not isinstance(source_value, str) or not source_value or not isinstance(backup_value, str) or not backup_value:
            raise ValueError(f'Invalid backup manifest entry {index}: source and backup must be non-empty paths')
        source, backup = Path(source_value), Path(backup_value)
        if not source.is_absolute():
            raise ValueError(f"Invalid backup manifest entry {index}: source must be absolute")
        if not backup.is_absolute():
            backup = backup_root / backup
        # Resolve existing symlinks before containment checks. The destination
        # itself may not exist; resolve(strict=False) still resolves its parents.
        backup = backup.resolve(strict=True)
        try:
            backup.relative_to(backup_root)
        except ValueError as exc:
            raise ValueError(f'Invalid backup manifest entry {index}: backup escapes manifest directory') from exc
        source = source.resolve(strict=False)
        expected = entry.get('sha256')
        if expected is not None and (not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdefABCDEF' for c in expected)):
            raise ValueError(f"Invalid backup manifest entry {index}: invalid sha256")
        if not backup.is_file():
            skipped.append({**entry, 'reason': 'backup missing'})
            continue
        from workstation.core.backup import _sha256
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
