"""Safe timestamped backups for config and SQLite state."""
from __future__ import annotations
import hashlib, json, shutil
from datetime import datetime, timezone
from pathlib import Path
from workstation.config import TOOLKIT_ROOT

BACKUPS_DIR = TOOLKIT_ROOT / "backups"

# The manifest is written beside the payloads, so its name is never a payload.
MANIFEST_NAME = "manifest.json"

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _available_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


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
    """
    candidates = [Path(raw) for raw in paths]
    existing = [source for source in candidates if source.is_file()]
    required = sum(item.stat().st_size for item in existing) + 64 * 1024 * 1024
    BACKUPS_DIR.mkdir(exist_ok=True)
    available = _available_bytes(BACKUPS_DIR)
    if available < required and not allow_partial:
        raise RuntimeError(f"Insufficient backup space: need {required / (1024**3):.2f} GB, have {available / (1024**3):.2f} GB")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = BACKUPS_DIR / f"{stamp}_{label}"
    destination.mkdir(parents=True, exist_ok=False)
    namer = _PayloadNamer(candidates, occupied=(MANIFEST_NAME,))
    entries = []
    for source in candidates:
        if not source.is_file():
            entries.append({"source": str(source), "status": "missing"})
            continue
        target = destination / namer.claim(source)
        try:
            shutil.copy2(source, target)
        except FileNotFoundError:
            entries.append({"source": str(source), "status": "missing"})
            continue
        entries.append({
            "source": str(source), "backup": str(target), "size": target.stat().st_size,
            "sha256": _sha256(target), "status": "backed_up",
        })
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "label": label, "files": entries}
    manifest_path = destination / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"directory": str(destination), "manifest": str(manifest_path), "files": entries}
