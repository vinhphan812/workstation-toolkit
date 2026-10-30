"""Process inspection — cross-platform via psutil."""
import os, re, time

import psutil
from dataclasses import dataclass
from typing import List, Optional

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

def list_processes(threshold_mb: int = 100) -> List[ProcessInfo]:
    """List processes using more than threshold_mb of RAM."""
    excluded = {"System", "Idle", "smss", "csrss", "wininit", "services", "lsass"}
    results = []
    for p in psutil.process_iter(["pid", "name", "memory_info", "cmdline", "cwd", "status", "ppid"]):
        try:
            info = p.info
            ram_mb = info["memory_info"].rss / (1024**2)
            if ram_mb < threshold_mb:
                continue
            if info["name"] in excluded:
                continue
            cmdline = " ".join(info["cmdline"]) if info["cmdline"] else ""
            cwd = info["cwd"] or ""
            results.append(ProcessInfo(
                pid=info["pid"],
                name=info["name"],
                ram_mb=round(ram_mb, 1),
                ram_gb=round(ram_mb / 1024, 2),
                cmdline=cmdline[:120],
                cwd=cwd,
                parent_pid=info["ppid"],
                status=info["status"],
            ))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    results.sort(key=lambda x: x.ram_mb, reverse=True)
    return results

def is_process_orphaned(proc: ProcessInfo) -> tuple[bool, str]:
    """Report only explicit stale-path evidence, not a missing parent alone.

    Parentless processes are normal on Windows and Unix. Parent and cwd
    access failures are treated as unknown; an empty cwd is not missing-path
    evidence. A deleted cwd or explicit stale worktree cmdline remains useful
    advisory evidence.
    """
    normalized = proc.cmdline.replace("/", "\\")
    if ".worktrees" in normalized and "t_" in normalized:
        return True, "cmdline references orphaned worktree path"
    for pattern in (r"worktree.*deleted", r"node_modules.*missing"):
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return True, "cmdline references orphaned path"

    if proc.cwd and not os.path.exists(proc.cwd):
        return True, f"cwd does not exist: {proc.cwd}"
    return False, ""

def kill_process(pid: int) -> bool:
    try:
        p = psutil.Process(pid)
        p.kill()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

def find_by_name(name: str) -> List[ProcessInfo]:
    """Find all processes matching name (substring)."""
    return [p for p in list_processes(1) if name.lower() in p.name.lower()]
