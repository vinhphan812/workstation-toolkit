"""Safe timestamped backups for config and SQLite state.

Backups can contain sensitive configuration and SQLite state, so every
artifact this module creates is restricted to its owner.  The policy and
the platform limitations are implemented in :mod:`workstation.core.permissions`;
this module only decides *what* has to be restricted and reports what
happened.

Every backup writes a versioned manifest that can be verified later
without modifying the backup tree, so a payload that was corrupted or
changed after the fact is detected instead of being assumed intact.
"""
from __future__ import annotations
import hashlib, json, os, shutil
from datetime import datetime, timezone
from pathlib import Path
from workstation.config import TOOLKIT_ROOT
from workstation.core import permissions

BACKUPS_DIR = TOOLKIT_ROOT / "backups"
MANIFEST_VERSION = 1
# The manifest is written beside the payloads, so its name is never a payload.
MANIFEST_NAME = "manifest.json"


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


class _PayloadNamer:
    """Assign each copied file a payload name no other file can claim.

    A source keeps its own basename while that name is free. Sources that
    share a basename, and sources whose name is already taken, fall back to
    a numbered variant that shadows no candidate basename. Names are compared
    case-insensitively because Windows and macOS volumes are
    case-insensitive, so two payloads can never land on one file.
    """

    def __init__(self, candidates: list[Path], occupied: tuple[str, ...] = ()) -> None:
        self.reserved = {source.name.casefold() for source in candidates}
        self.occupied = {name.casefold() for name in occupied}
        self.reserved |= self.occupied
        self.used: set[str] = set()

    def claim(self, source: Path) -> str:
        name = source.name
        folded = name.casefold()
        if folded not in self.used and folded not in self.occupied:
            payload = name
        else:
            stem = Path(name).stem
            suffix = Path(name).suffix
            index = 0
            while True:
                index += 1
                candidate = f"{stem}~{index}{suffix}"
                if candidate.casefold() not in self.used and candidate.casefold() not in self.reserved:
                    payload = candidate
                    break
        self.used.add(payload.casefold())
        return payload


def backup_files(label: str, paths: list[str], *, allow_partial: bool = False) -> dict:
    """Copy existing files after a volume-space preflight.

    A 64 MiB margin is reserved. By default, insufficient capacity fails
    before copying rather than leaving a partial multi-GB backup.

    Sources that share a basename are copied to distinct payloads, so one
    payload is never overwritten and every manifest entry names its own
    payload with its own digest. The manifest schema is unchanged: each
    entry keeps its source path, payload path, size and digest, so manifests
    written by earlier versions still restore.

    Sources are checked before and after copying; changing sources are
    reported as failed and never included as complete.

    The backup root, the backup directory, every payload and the manifest
    are restricted to their owner.  The resulting permission status is
    reported in the return value and recorded in the manifest, so an
    unsupported filesystem is visible instead of being implied safe.

    Failure safety: when a payload cannot be restricted, the backup aborts
    and the destination directory it created is removed, so no unprotected
    copy of sensitive data is left behind.
    """
    candidates = [Path(raw) for raw in paths]
    existing = [source for source in candidates if source.is_file()]
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
    namer = _PayloadNamer(candidates, occupied=(MANIFEST_NAME,))
    entries = []
    results = [root_result, destination_result]
    try:
        _require_enforced(destination_result, "directory")
        for source in candidates:
            if not source.is_file():
                entries.append({"source": str(source), "status": "missing"})
                continue
            before = source.stat()
            target = destination / namer.claim(source)
            try:
                payload_result = _copy_private(source, target)
            except FileNotFoundError:
                # The source disappeared between the check and the copy, so
                # no payload exists for it.  The partially created target is
                # removed instead of being left behind as an empty payload.
                target.unlink(missing_ok=True)
                entries.append({"source": str(source), "status": "missing"})
                continue
            _require_enforced(payload_result, "payload")
            results.append(payload_result)
            after = source.stat()
            source_hash = _sha256(source)
            copied_hash = _sha256(target)
            stable = (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino)
            if not stable or source_hash != copied_hash:
                entries.append({"source": str(source), "backup": str(target), "status": "failed", "reason": "source changed during backup"})
                target.unlink(missing_ok=True)
                continue
            entries.append({
                "source": str(source), "backup": str(target), "size": after.st_size,
                "mtime_ns": after.st_mtime_ns, "sha256": copied_hash, "status": "backed_up",
            })
        # The manifest is created empty and owner-only first, so the summary
        # it records can cover the manifest itself and not only the payloads
        # that were written before it.
        manifest_path = destination / MANIFEST_NAME
        manifest_result = permissions.write_private_text(manifest_path, "")
        _require_enforced(manifest_result, "manifest")
        manifest_index = len(results)
        results.append(manifest_result)
        summary = permissions.summarize(results)
        manifest = {
            "version": MANIFEST_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
            "label": label, "files": entries, "permissions": summary,
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
        "ok": all(entry["status"] != "failed" for entry in entries),
        "permissions": permissions.summarize(results),
    }


def verify_backup(manifest_path: str) -> dict:
    """Verify every payload in a manifest without modifying the backup tree."""
    manifest_file = Path(manifest_path).resolve(strict=True)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    root = manifest_file.parent.resolve(strict=True)
    checked, failed = [], []
    for index, entry in enumerate(manifest["files"]):
        if entry["status"] == "missing":
            failed.append({"index": index, "source": entry["source"], "reason": "source missing at backup time"})
            continue
        if entry["status"] == "failed":
            failed.append({"index": index, "source": entry.get("source"), "reason": entry.get("reason", "backup failed")})
            continue
        payload = Path(entry["backup"])
        if not payload.is_absolute():
            payload = root / payload
        payload = payload.resolve(strict=False)
        if not _is_relative_to(payload, root):
            failed.append({"index": index, "reason": "payload escapes manifest directory"})
            continue
        if not payload.is_file():
            failed.append({"index": index, "source": entry["source"], "reason": "payload missing", "backup": str(payload)})
            continue
        actual = _sha256(payload)
        if actual.lower() != entry["sha256"].lower():
            failed.append({"index": index, "source": entry["source"], "reason": "checksum mismatch", "expected_sha256": entry["sha256"], "actual_sha256": actual})
        else:
            checked.append({"source": entry["source"], "backup": str(payload), "sha256": actual})
    return {"ok": not failed, "manifest": str(manifest_file), "checked": checked, "failed": failed}


def _validate_manifest(manifest: object) -> None:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("Invalid backup manifest: 'files' must be a list")
    version = manifest.get("version", 0)
    if type(version) is not int or version not in (0, MANIFEST_VERSION):
        raise ValueError(f"Unsupported backup manifest version: {version!r}")
    for index, entry in enumerate(manifest["files"]):
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid backup manifest entry {index}: expected object")
        if entry.get("status") not in ("backed_up", "missing", "failed"):
            raise ValueError(f"Invalid backup manifest entry {index}: unsupported status {entry.get('status')!r}")
        if not isinstance(entry.get("source"), str) or not entry["source"]:
            raise ValueError(f"Invalid backup manifest entry {index}: invalid source")
        if entry["status"] == "backed_up":
            digest = entry.get("sha256")
            if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest)):
                raise ValueError(f"Invalid backup manifest entry {index}: invalid sha256")
            if entry.get("backup") is not None and (not isinstance(entry.get("backup"), str) or not entry["backup"]):
                raise ValueError(f"Invalid backup manifest entry {index}: backup must be a non-empty path")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
