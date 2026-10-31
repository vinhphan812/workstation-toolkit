"""Backup/restore and Hermes SQLite maintenance, all explicit and guarded."""
from __future__ import annotations
import hashlib, json, os, shutil, sqlite3, stat, subprocess, tempfile
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


def restore_backup(manifest_path: str, execute: bool = False, yes: bool = False, allowed_roots: list[str] | tuple[str, ...] | None = None) -> dict:
    """Restore entries only beneath caller-authorized destination roots.

    Generated manifests retain their original absolute source paths; callers
    must explicitly authorize those roots. Backup payloads stay in the manifest
    directory and are read from a single no-follow descriptor into staging.
    """
    require_execute(execute, yes, 'restore')
    if not allowed_roots:
        raise ValueError('restore requires at least one --allowed-root destination')
    roots = [Path(root).resolve(strict=True) for root in allowed_roots]
    if not all(root.is_dir() for root in roots):
        raise ValueError('each allowed root must be an existing directory')
    manifest_file = Path(manifest_path).resolve(strict=True)
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list):
        raise ValueError("Invalid backup manifest: 'files' must be a list")
    restored, skipped = [], []
    backup_root = manifest_file.parent.resolve(strict=True)
    validated = []
    for index, entry in enumerate(manifest['files']):
        if not isinstance(entry, dict):
            raise ValueError(f'Invalid backup manifest entry {index}: expected object')
        status = entry.get('status')
        if status not in ('backed_up', 'missing'):
            raise ValueError(f"Invalid backup manifest entry {index}: unsupported status {status!r}")
        source_value = entry.get('source')
        if not isinstance(source_value, str) or not source_value:
            raise ValueError(f"Invalid backup manifest entry {index}: invalid source")
        source = Path(source_value)
        if not source.is_absolute():
            raise ValueError(f"Invalid backup manifest entry {index}: source must be absolute")
        source = source.resolve(strict=False)
        if not any(_is_relative_to(source, root) for root in roots):
            raise ValueError(f'Invalid backup manifest entry {index}: source is outside allowed roots')
        if status == 'missing':
            validated.append((entry, source, None))
            continue
        backup_value = entry.get('backup')
        if not isinstance(backup_value, str) or not backup_value:
            raise ValueError(f'Invalid backup manifest entry {index}: backup must be a non-empty path')
        backup = Path(backup_value)
        if not backup.is_absolute():
            backup = backup_root / backup
        backup = backup.resolve(strict=True)
        if not _is_relative_to(backup, backup_root):
            raise ValueError(f'Invalid backup manifest entry {index}: backup escapes manifest directory')
        expected = entry.get('sha256')
        if expected is not None and (not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdefABCDEF' for c in expected)):
            raise ValueError(f"Invalid backup manifest entry {index}: invalid sha256")
        validated.append((entry, source, (backup, expected)))

    for entry, source, payload in validated:
        if payload is None:
            skipped.append(entry)
            continue
        backup, expected = payload
        if not backup.is_file():
            skipped.append({**entry, 'reason': 'backup missing'})
            continue
        # On POSIX O_NOFOLLOW protects the final component. The descriptor is
        # opened once, then both digest validation and staging use those exact
        # bytes, closing the path-reopen TOCTOU. Parent-directory swaps in a
        # concurrently writable backup tree remain outside this threat model;
        # backup directories must not be concurrently modified during restore.
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        try:
            fd = os.open(backup, flags)
        except OSError as exc:
            raise ValueError(f'Unable to safely open backup payload: {exc}') from exc
        try:
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('Backup payload is not a regular file')
                data = stream.read()
        finally:
            os.close(fd)
        actual = hashlib.sha256(data).hexdigest()
        if expected and actual.lower() != expected.lower():
            skipped.append({**entry, 'reason': 'checksum mismatch', 'actual_sha256': actual})
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f'.{source.name}.restore-', dir=source.parent)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            if expected and hashlib.sha256(Path(temp_name).read_bytes()).hexdigest().lower() != expected.lower():
                skipped.append({**entry, 'reason': 'post-copy checksum mismatch'})
                continue
            os.replace(temp_name, source)
            restored.append(str(source))
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    return {'restored': restored, 'skipped': skipped}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


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
