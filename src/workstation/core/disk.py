"""Disk inspection — cross-platform."""
import shutil, os
from dataclasses import dataclass
from typing import List

@dataclass
class DiskInfo:
    path: str
    total_gb: float
    used_gb: float
    free_gb: float
    pct_used: float

def get_disk_info(path: str = "/") -> DiskInfo:
    """Return disk usage for the volume containing `path`."""
    usage = shutil.disk_usage(path)
    total = usage.total / (1024**3)
    used  = usage.used  / (1024**3)
    free  = usage.free / (1024**3)
    return DiskInfo(
        path=path,
        total_gb=round(total, 2),
        used_gb=round(used, 2),
        free_gb=round(free, 2),
        pct_used=round((used / total) * 100, 1),
    )

def get_large_items(top_dir: str, min_mb: int = 50, limit: int = 10) -> List[dict]:
    """Return largest files/dirs under top_dir."""
    items = []
    try:
        for entry in os.scandir(top_dir):
            try:
                if entry.is_file(follow_symlinks=False):
                    size_mb = entry.stat().st_size / (1024**2)
                elif entry.is_dir(follow_symlinks=False):
                    size_mb = _dir_size(entry.path) / (1024**2)
                else:
                    continue
                if size_mb >= min_mb:
                    items.append({
                        "name": entry.name,
                        "path": entry.path,
                        "size_mb": round(size_mb, 2),
                        "age_days": (os.path.getmtime(entry.path) -
                                     os.path.getctime(entry.path)) // 86400,
                    })
            except (PermissionError, OSError):
                pass
    except (PermissionError, OSError):
        pass
    items.sort(key=lambda x: x["size_mb"], reverse=True)
    return items[:limit]

def _dir_size(path: str) -> float:
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _dir_size(entry.path)
            except (PermissionError, OSError):
                pass
    except (PermissionError, OSError):
        pass
    return total
