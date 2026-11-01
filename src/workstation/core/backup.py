"""Safe timestamped backups for config and SQLite state.

Backups can contain sensitive configuration and SQLite state, so every
artifact this module creates is restricted to its owner.  The policy and
the platform limitations are implemented in :mod:`workstation.core.permissions`;
this module only decides *what* has to be restricted and reports what
happened.
"""
from __future__ import annotations
import hashlib, json, os, shutil
from datetime import datetime, timezone
from pathlib import Path
from workstation.config import TOOLKIT_ROOT
from workstation.core import permissions

BACKUPS_DIR = TOOLKIT_ROOT / "backups"


def _copy_private(source: Path, target: Path) -> permissions.PermissionResult:
    """Create a private copy of a payload file.

    On POSIX the payload is created with an owner-only mode from the very
    first instant it exists, so it is never briefly readable by another
    user.  On Windows the copy inherits the DACL of the already restricted
    backup directory and the resulting DACL is verified afterwards.

    An already existing target is overwritten rather than rejected, which
    keeps the previous copy semantics for sources that share a file name.
    """
    if os.name == "nt":
        shutil.copy2(source, target)
        return permissions.restrict_created_file(target)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, permissions.FILE_MODE)
    with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
        shutil.copyfileobj(input_file, output)
    # Only the timestamps are copied.  copystat would also carry the source
    # permission bits, which would briefly widen the copy beyond the
    # owner-only mode it was created with.
    source_stat = source.stat()
    os.utime(target, (source_stat.st_atime, source_stat.st_mtime))
    return permissions.restrict_created_file(target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _available_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _require_enforced(result: permissions.PermissionResult, what: str) -> None:
    """Abort when a path could not be restricted at all.

    An unsupported platform is not an error: the backup still runs and the
    outcome is reported honestly in the result and the manifest.  A genuine
    failure is an error, because continuing would write the payload into a
    location that is known not to be protected.
    """
    if result.failed:
        raise RuntimeError(
            f"Backup {what} could not be restricted to its owner: {result.detail}"
        )


def backup_files(label: str, paths: list[str], *, allow_partial: bool = False) -> dict:
    """Copy existing files after a volume-space preflight.

    A 64 MiB margin is reserved. By default, insufficient capacity fails
    before copying rather than leaving a partial multi-GB backup.

    The backup root, the backup directory, every payload and the manifest
    are restricted to their owner.  The resulting permission status is
    reported in the return value and recorded in the manifest, so an
    unsupported filesystem is visible instead of being implied safe.

    Failure safety: when a payload cannot be restricted, the backup aborts
    and the destination directory it created is removed, so no unprotected
    copy of sensitive data is left behind.
    """
    existing = [Path(raw) for raw in paths if Path(raw).is_file()]
    required = sum(item.stat().st_size for item in existing) + 64 * 1024 * 1024
    root_result = permissions.ensure_directory(BACKUPS_DIR)
    _require_enforced(root_result, "root")
    available = _available_bytes(BACKUPS_DIR)
    if available < required and not allow_partial:
        raise RuntimeError(f"Insufficient backup space: need {required / (1024**3):.2f} GB, have {available / (1024**3):.2f} GB")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = BACKUPS_DIR / f"{stamp}_{label}"
    # The destination is created before the try block, so a name collision
    # propagates without the cleanup below removing a directory that this
    # call did not create.
    destination_result = permissions.create_directory(destination)
    entries = []
    results = [root_result, destination_result]
    try:
        _require_enforced(destination_result, "directory")
        for raw in paths:
            source = Path(raw)
            if not source.is_file():
                entries.append({"source": str(source), "status": "missing"})
                continue
            target = destination / source.name
            payload_result = _copy_private(source, target)
            _require_enforced(payload_result, "payload")
            results.append(payload_result)
            entries.append({
                "source": str(source), "backup": str(target), "size": target.stat().st_size,
                "sha256": _sha256(target), "status": "backed_up",
            })
        # The manifest is created empty and owner-only first, so the summary
        # it records can cover the manifest itself and not only the payloads
        # that were written before it.
        manifest_path = destination / "manifest.json"
        manifest_result = permissions.write_private_text(manifest_path, "")
        _require_enforced(manifest_result, "manifest")
        manifest_index = len(results)
        results.append(manifest_result)
        summary = permissions.summarize(results)
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(), "label": label,
            "files": entries, "permissions": summary,
        }
        # The rewrite keeps the owner-only permissions of the file that was
        # just created, so the manifest content cannot widen them.  It
        # reports the same outcome as the creation, so the summary that was
        # recorded inside the manifest stays accurate.
        manifest_result = permissions.rewrite_private_text(
            manifest_path, json.dumps(manifest, indent=2)
        )
        _require_enforced(manifest_result, "manifest")
    except Exception:
        # The destination was created by this call and is not a complete,
        # protected backup, so it is removed instead of being left behind
        # with an unprotected payload in it.
        shutil.rmtree(destination, ignore_errors=True)
        raise
    results[manifest_index] = manifest_result
    return {
        "directory": str(destination), "manifest": str(manifest_path), "files": entries,
        "permissions": permissions.summarize(results),
    }
