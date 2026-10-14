"""Safe timestamped backups for config and SQLite state."""
from __future__ import annotations
import hashlib, json, shutil
from datetime import datetime, timezone
from pathlib import Path
from workstation.config import TOOLKIT_ROOT

BACKUPS_DIR = TOOLKIT_ROOT / "backups"

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

    A 64 MiB margin is reserved. By default, insufficient capacity fails
    before copying rather than leaving a partial multi-GB backup.
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
        target = destination / source.name
        shutil.copy2(source, target)
        entries.append({
            "source": str(source), "backup": str(target), "size": target.stat().st_size,
            "sha256": _sha256(target), "status": "backed_up",
        })
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "label": label, "files": entries}
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"directory": str(destination), "manifest": str(manifest_path), "files": entries}
