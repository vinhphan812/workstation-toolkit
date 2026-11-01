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
    restored, skipped, failed = [], [], []
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
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdefABCDEF' for c in expected):
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
        # Payload reads use O_NOFOLLOW for the final component. Destination
        # mutations below are anchored to an opened parent directory on POSIX.
        nofollow = getattr(os, 'O_NOFOLLOW', 0)
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | nofollow
        try:
            fd = os.open(backup, flags)
        except OSError as exc:
            raise ValueError(f'Unable to safely open backup payload: {exc}') from exc
        temp_name = None
        destination_fd = None
        try:
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('Backup payload is not a regular file')
                # Validate the complete source before creating any destination
                # staging file, then rewind this same descriptor for the copy.
                source_hash = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    source_hash.update(chunk)
                actual = source_hash.hexdigest()
                if actual.lower() != expected.lower():
                    failed.append({**entry, 'reason': 'checksum mismatch', 'expected_sha256': expected, 'actual_sha256': actual, 'evidence_path': str(backup), 'source_preserved': True, 'backup_preserved': True})
                    continue
                stream.seek(0)
                try:
                    stage_fd, temp_name, destination_fd, leaf_name = _open_destination_parent(source, roots)
                except (OSError, ValueError) as exc:
                    failed.append({**entry, 'reason': f'destination parent unavailable: {exc}', 'source_preserved': True, 'backup_preserved': True})
                    continue
                copy_hash = hashlib.sha256()
                with os.fdopen(stage_fd, 'wb') as out:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        copy_hash.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                if copy_hash.hexdigest().lower() != expected.lower():
                    failed.append({**entry, 'reason': 'source changed during staging', 'expected_sha256': expected, 'actual_sha256': copy_hash.hexdigest(), 'evidence_path': temp_name, 'source_preserved': True, 'backup_preserved': True})
                    temp_name = None
                    continue
        finally:
            os.close(fd)
        try:
            staged_hash = hashlib.sha256()
            if destination_fd is None:
                staged_file = open(temp_name, 'rb')
            else:
                staged_file = os.fdopen(os.open(temp_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=destination_fd), 'rb')
            with staged_file as staged:
                for chunk in iter(lambda: staged.read(1024 * 1024), b''):
                    staged_hash.update(chunk)
            if staged_hash.hexdigest().lower() != expected.lower():
                failed.append({**entry, 'reason': 'post-copy checksum mismatch', 'expected_sha256': expected, 'actual_sha256': staged_hash.hexdigest(), 'evidence_path': temp_name, 'source_preserved': True, 'backup_preserved': True})
                temp_name = None
                continue
            if destination_fd is not None:
                os.replace(temp_name, leaf_name, src_dir_fd=destination_fd, dst_dir_fd=destination_fd)
            else:
                # Non-POSIX fallback: policy requires destination trees to be
                # trusted and not concurrently writable during restore.
                parent = source.parent.resolve(strict=True)
                if not any(_is_relative_to(parent, root) for root in roots):
                    failed.append({**entry, 'reason': 'destination parent changed outside allowed roots', 'source_preserved': True, 'backup_preserved': True})
                    temp_name = None
                    continue
                os.replace(temp_name, source)
            temp_name = None
            restored.append(str(source))
        finally:
            if temp_name is not None:
                try:
                    if destination_fd is None:
                        os.unlink(temp_name)
                    else:
                        os.unlink(temp_name, dir_fd=destination_fd)
                except (FileNotFoundError, OSError):
                    pass
            if destination_fd is not None:
                os.close(destination_fd)
    return {'ok': not failed, 'restored': restored, 'skipped': skipped, 'failed': failed}


def _open_destination_parent(source: Path, roots: list[Path]):
    """Create/open the parent without following swapped path components (POSIX)."""
    if os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW') or not os.supports_dir_fd:
        parent = source.parent.resolve(strict=False)
        if not any(_is_relative_to(parent, root) for root in roots):
            raise ValueError('destination parent changed outside allowed roots')
        source.parent.mkdir(parents=True, exist_ok=True)
        parent = source.parent.resolve(strict=True)
        if not any(_is_relative_to(parent, root) for root in roots):
            raise ValueError('destination parent changed outside allowed roots')
        fd, name = tempfile.mkstemp(prefix=f'.{source.name}.restore-', dir=parent)
        return fd, name, None, source.name

    root = next((r for r in roots if _is_relative_to(source, r)), None)
    if root is None:
        raise ValueError('destination parent changed outside allowed roots')
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | os.O_NOFOLLOW
    current = os.open(root, flags)
    try:
        relative_parent = source.parent.relative_to(root)
        for part in relative_parent.parts:
            if part in ('', '.'):
                continue
            try:
                child = os.open(part, flags, dir_fd=current)
            except FileNotFoundError:
                os.mkdir(part, dir_fd=current)
                child = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = child
        leaf = source.name
        fd, temp_name = _create_stage_at(current, leaf)
        return fd, temp_name, current, leaf
    except Exception:
        os.close(current)
        raise


def _create_stage_at(parent_fd: int, leaf: str) -> tuple[int, str]:
    import secrets
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    for _ in range(100):
        name = f'.{leaf}.restore-{secrets.token_hex(8)}'
        try:
            return os.open(name, flags, 0o600, dir_fd=parent_fd), name
        except FileExistsError:
            continue
    raise FileExistsError('unable to create unique restore staging file')


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
