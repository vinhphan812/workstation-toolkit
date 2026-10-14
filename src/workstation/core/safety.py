"""Safety gates shared by mutation commands."""
from __future__ import annotations
import os
from pathlib import Path

class SafetyError(RuntimeError):
    pass

def require_execute(execute: bool, yes: bool, action: str) -> None:
    if not execute:
        raise SafetyError(f"{action} is a dry-run by default; pass --execute.")
    if not yes:
        raise SafetyError(f"{action} requires --yes after reviewing the dry-run.")

def require_free_space(path: str | Path, min_gb: float) -> float:
    from shutil import disk_usage
    free_gb = disk_usage(path).free / (1024**3)
    if free_gb < min_gb:
        raise SafetyError(f"Need {min_gb:.1f} GB free on volume containing {path}; have {free_gb:.2f} GB.")
    return round(free_gb, 2)
