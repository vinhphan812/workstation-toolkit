"""Read-only process risk triage and explicit single-PID termination."""
from __future__ import annotations

import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import psutil

UNAVAILABLE = "<unavailable>"
BENIGN_REMOTE_NAMES = ("anydesk", "teamviewer")
SUSPICIOUS_TERMS = ("xmrig", "mimikatz", "psexec", "keylogger", "cryptominer")


@dataclass
class ProcessEvidence:
    pid: int
    ppid: int | str
    starttime: float | str
    exe: str
    cmdline: str
    cwd: str
    status: str


def _value(proc: psutil.Process, key: str, getter: str) -> Any:
    try:
        if key == "pid":
            return proc.pid
        if key == "ppid":
            return proc.ppid()
        value = getattr(proc, getter)()
        if key == "cmdline":
            return " ".join(value) if value else UNAVAILABLE
        return value if value not in (None, "") else UNAVAILABLE
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
        return UNAVAILABLE


def collect_process_evidence(process: psutil.Process) -> ProcessEvidence:
    """Collect evidence with an explicit marker for each inaccessible field."""
    start = _value(process, "starttime", "create_time")
    return ProcessEvidence(
        pid=_value(process, "pid", ""),
        ppid=_value(process, "ppid", ""),
        starttime=start,
        exe=_value(process, "exe", "exe"),
        cmdline=_value(process, "cmdline", "cmdline"),
        cwd=_value(process, "cwd", "cwd"),
        status=_value(process, "status", "status"),
    )


def parent_pid_is_orphaned(parent_pid: int | str, exists) -> bool:
    """Treat missing/inaccessible parent data as unknown, not orphan evidence."""
    if not isinstance(parent_pid, int) or parent_pid <= 1:
        return False
    try:
        return not exists(parent_pid)
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
        return False


def _lifecycle(evidence: ProcessEvidence) -> tuple[str, str]:
    """Separate lifecycle evidence from behavior/name heuristics."""
    if evidence.cwd == UNAVAILABLE:
        return "unknown", "cwd unavailable; cannot verify working directory"
    if not evidence.cwd:
        return "unknown", "cwd empty; cannot verify working directory"
    if not os.path.exists(evidence.cwd):
        return "possible_orphan", "reported cwd does not exist in this process namespace"
    return "normal_or_unknown", "existing cwd; absent/inaccessible parent alone is not orphan evidence"


def _heuristic(evidence: ProcessEvidence) -> tuple[list[str], str]:
    text = " ".join((str(evidence.exe), str(evidence.cmdline))).lower()
    # Remove recognized benign support-tool tokens before heuristic matching.
    for name in BENIGN_REMOTE_NAMES:
        text = text.replace(name, "")
    indicators = [term for term in SUSPICIOUS_TERMS if term in text]
    confidence = "low" if indicators else "none"
    return indicators, confidence


def inspect_network_connections() -> dict:
    """Return compact connection evidence; permission failures are non-fatal."""
    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError) as exc:
        return {"status": "unavailable", "reason": type(exc).__name__, "count": None, "connections": []}
    compact = []
    for conn in connections:
        compact.append({
            "family": str(conn.family),
            "type": str(conn.type),
            "local_address": str(conn.laddr) if conn.laddr else None,
            "remote_address": str(conn.raddr) if conn.raddr else None,
            "status": conn.status or None,
            "pid": conn.pid,
        })
    return {"status": "available", "count": len(compact), "connections": compact}


def scan_processes(*, no_network: bool = False) -> dict:
    """Scan every visible process, without RAM filtering; never mutate state."""
    network = None if no_network else inspect_network_connections()
    rows = []
    for proc in psutil.process_iter():
        evidence = collect_process_evidence(proc)
        lifecycle, lifecycle_reason = _lifecycle(evidence)
        indicators, confidence = _heuristic(evidence)
        rows.append({
            "evidence": asdict(evidence),
            "lifecycle": lifecycle,
            "lifecycle_reason": lifecycle_reason,
            "heuristic_indicators": indicators,
            "heuristic_confidence": confidence,
            "heuristic_advisory": True,
            "confidence_limitations": "Name/cmdline indicators are weak signals and may be false positives; operator verification required.",
        })
    return {
        "processes": rows,
        "network_inspection": {"status": "skipped", "count": None, "connections": []} if no_network else network,
        "limitations": [
            "Process evidence is a point-in-time, permission-limited snapshot.",
            "Heuristic indicators are advisory, not a malware determination.",
            "Network connection enumeration may be incomplete or unavailable due to permissions.",
            "Missing parent PID alone does not establish an orphan.",
            "Path existence is checked only in this process namespace.",
        ],
        "mutating_operations": "none; scan is read-only",
    }


def kill_pid(pid: int, *, execute: bool = False) -> dict:
    """Preview by default or terminate exactly one explicit PID with one call."""
    if pid <= 0:
        raise ValueError("PID must be positive")
    if not execute:
        return {"pid": pid, "executed": False, "action": "dry_run"}
    try:
        psutil.Process(pid).kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        return {"pid": pid, "executed": False, "action": "failed", "reason": type(exc).__name__}
    return {"pid": pid, "executed": True, "action": "kill_requested"}
