"""Safe timestamped backups for config and SQLite state."""
from __future__ import annotations
import hashlib, json, shutil
from datetime import datetime, timezone
from pathlib import Path
from workstation.config import TOOLKIT_ROOT

BACKUPS_DIR = TOOLKIT_ROOT / "backups"
MANIFEST_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _available_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def backup_files(label: str, paths: list[str], *, allow_partial: bool = False) -> dict:
    """Copy existing files after a volume-space preflight.

    A 64 MiB margin is reserved. Sources are checked before and after copying;
    changing sources are reported as failed and never included as complete.
    """
    existing = [Path(raw) for raw in paths if Path(raw).is_file()]
    required = sum(item.stat().st_size for item in existing) + 64 * 1024 * 1024
    BACKUPS_DIR.mkdir(exist_ok=True)
    available = _available_bytes(BACKUPS_DIR)
    if available < required and not allow_partial:
        raise RuntimeError(f"Insufficient backup space: need {required / (1024**3):.2f} GB, have {available / (1024**3):.2f} GB")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = BACKUPS_DIR / f"{stamp}_{label}"
    destination.mkdir(parents=True, exist_ok=False)
    entries = []
    for raw in paths:
        source = Path(raw)
        if not source.is_file():
            entries.append({"source": str(source), "status": "missing"})
            continue
        before = source.stat()
        target = destination / source.name
        shutil.copy2(source, target)
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
    manifest = {"version": MANIFEST_VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "label": label, "files": entries}
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"directory": str(destination), "manifest": str(manifest_path), "files": entries, "ok": all(e["status"] != "failed" for e in entries)}


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
