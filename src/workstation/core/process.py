"""Process inspection — cross-platform via psutil."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List

import psutil


@dataclass
class ProcessInfo:
    pid: int
    name: str
    ram_mb: float
    ram_gb: float
    cmdline: str
    cwd: str
    parent_pid: int
    status: str


# System processes never reported.
EXCLUDED = {
    "System", "Idle", "smss", "csrss", "wininit", "services", "lsass",
    "Memory Compression", "Registry",
}


def list_processes(threshold_mb: int = 100) -> List[ProcessInfo]:
    """List processes using more than threshold_mb of RAM.

    Performance: two-phase approach.
      Phase 1 iterates all processes asking only for pid/name/rss (fast).
      Phase 2 opens a Process object only for candidates above threshold,
    collecting extra metadata (cmdline, cwd, status, ppid) on-demand.
    """
    # Phase 1: fast filter
    candidates: List[tuple[int, str, float]] = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = proc.info
            if info["name"] in EXCLUDED:
                continue
            ram_mb = info["memory_info"].rss / (1024 ** 2)
            if ram_mb < threshold_mb:
                continue
            candidates.append((info["pid"], info["name"], ram_mb))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    # Phase 2: enrich only heavy candidates
    results: List[ProcessInfo] = []
    for pid, name, ram_mb in candidates:
        try:
            p = psutil.Process(pid)
            cmdline = " ".join(p.cmdline()) if p.cmdline() else ""
            try:
                cwd = p.cwd() or ""
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                cwd = ""
            results.append(ProcessInfo(
                pid=pid, name=name,
                ram_mb=round(ram_mb, 1), ram_gb=round(ram_mb / 1024, 2),
                cmdline=cmdline[:120], cwd=cwd,
                parent_pid=p.ppid(), status=str(p.status()),
            ))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    results.sort(key=lambda x: x.ram_mb, reverse=True)
    return results


def is_process_orphaned(proc: ProcessInfo) -> tuple[bool, str]:
    """Check if a process appears orphaned.

    Evidence: worktree path in cmdline, missing cwd, or parent gone.
    This is advisory, not a guaranteed zombie classification.
    """
    normalized = proc.cmdline.replace("/", "\\")
    if ".worktrees" in normalized and "t_" in normalized:
        return True, "cmdline references orphaned worktree path"
    for pattern in (r"worktree.*deleted", r"node_modules.*missing"):
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return True, "cmdline references orphaned path"
    try:
        psutil.Process(proc.parent_pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True, f"parent PID={proc.parent_pid} not found"
    except Exception:
        return True, f"parent PID={proc.parent_pid} unreachable"
    if proc.cwd and not os.path.exists(proc.cwd):
        return True, f"cwd does not exist: {proc.cwd}"
    return False, ""


def kill_process(pid: int) -> bool:
    """Terminate a process. Returns True on success, False if
    the process no longer exists or access is denied."""
    try:
        psutil.Process(pid).kill()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def find_by_name(name: str, threshold_mb: int = 1) -> List[ProcessInfo]:
    """Return processes whose name contains the given substring."""
    return [p for p in list_processes(threshold_mb)
             if name.lower() in p.name.lower()]


def kill_by_name(name: str, *, execute: bool = False) -> dict:
    """Find processes by name and optionally terminate them.

    Safety model:
      - Always dry-run by default (lists PIDs, never kills).
      - Pass execute=True to actually terminate.
    """
    matches = find_by_name(name)
    result = {
        "found":      [{"pid": p.pid, "name": p.name, "ram_mb": p.ram_mb}
                          for p in matches],
        "terminated":  [],
        "skipped":     [],
        "dry_run":     not execute,
    }
    if not execute:
        return result
    for proc in matches:
        success = kill_process(proc.pid)
        (result["terminated"] if success else result["skipped"]
         ).append(proc.pid)
    return result
