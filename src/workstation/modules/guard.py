"""Anti-malware / process-guard skeleton.
Detects and optionally terminates suspicious processes using heuristics.
Read-only by default; --execute flag required for any kill action.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import socket
import struct
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import psutil

from workstation.core.process import ProcessInfo, list_processes


# ── Severity taxonomy ────────────────────────────────────────────────────────
SEV_INFO     = "info"
SEV_WARN     = "warning"
SEV_HIGH     = "high"
SEV_CRITICAL = "critical"


@dataclass
class Finding:
    pid: int
    name: str
    severity: str
    category: str
    detail: str
    evidence: str
    verdict: str          # "suspicious" | "orphaned" | "zombie" | "clean"
    auto_kill: bool = False  # True only for unambiguous malware signatures


# ── Heuristics: suspicious process name patterns ──────────────────────────────
# Patterns here are advisory. They flag processes that warrant human review.
SUSPICIOUS_NAME_PATTERNS = [
    # Coin miners (confirmed malware, never legitimate on a workstation)
    (re.compile(r"xmrig",          re.I), "crypto-miner known binary name"),
    (re.compile(r"cryptonight",    re.I), "crypto-miner known binary name"),
    (re.compile(r"nicehash",       re.I), "crypto-miner known binary name"),
    (re.compile(r"minerx",        re.I), "crypto-miner known binary name"),
    (re.compile(r"t-rex.*miner",   re.I), "crypto-miner known binary name"),
    # Remote-access trojans
    (re.compile(r"teamviewer.*\.exe$", re.I), "RAT binary name (verify legitimacy)"),
    (re.compile(r"anydesk.*\.exe$",    re.I), "RAT binary name (verify legitimacy)"),
    # Info-stealer / credential-dumper patterns
    (re.compile(r"mimikatz",       re.I), "credential-dumper known tool"),
    (re.compile(r"lsass.*dump",    re.I), "lsass dump pattern"),
    # Cryptolocker patterns
    (re.compile(r"cryptolocker",   re.I), "ransomware known binary"),
    (re.compile(r"wannacry",       re.I), "ransomware known binary"),
    (re.compile(r"petya",          re.I), "ransomware known binary"),
    # Suspicious obfuscated names (single random string, no extension)
    (re.compile(r"^[a-z0-9]{8,12}$",    re.I), "random-looking binary name, no extension"),
    (re.compile(r"tmp[0-9a-f]{6,16}",   re.I), "temp-script binary name"),
]

# Suspicious path patterns in cmdline
SUSPICIOUS_PATH_PATTERNS = [
    (re.compile(r"\\\\tmp\\\\",               re.I), "cmdline references \\tmp\\"),
    (re.compile(r"/tmp/",                       re.I), "cmdline references /tmp/"),
    (re.compile(r"AppData\\\\Roaming\\\\Microsoft\\\\Windows\\\\", re.I), "suspicious AppData path"),
    (re.compile(r"Downloaded.*\.exe",           re.I), "exe launched from Downloads"),
    (re.compile(r"iex\s*\(",                    re.I), "PowerShell IEX download-execute pattern"),
    (re.compile(r"WebClient\.DownloadFile",      re.I), "PowerShell WebClient download"),
    (re.compile(r"Invoke-WebRequest",            re.I), "PowerShell Invoke-WebRequest (verify intent)"),
    (re.compile(r"Invoke-Expression",            re.I), "PowerShell IEX / Invoke-Expression"),
    (re.compile(r"certutil.*-urlcache",         re.I), "certutil download pattern"),
    (re.compile(r"bitsadmin",                   re.I), "BITS download pattern"),
    (re.compile(r"curl\s+-[sS].*\|.*sh",       re.I), "curl pipe to shell"),
    (re.compile(r"wget.*\|.*sh",               re.I), "wget pipe to shell"),
    (re.compile(r"base64\s+-d\s+\|",           re.I), "base64 decode pipe to shell"),
    (re.compile(r"mshta\s+http",               re.I), "mshta remote payload"),
    (re.compile(r"rundll32.*javascript:",       re.I), "rundll32 javascript payload"),
    (re.compile(r"regsvr32.*scrobj",           re.I), "regsvr32 Squiblydoo"),
    (re.compile(r"regsvr32.*http",             re.I), "regsvr32 remote DLL"),
    (re.compile(r"msiexec.*http",              re.I), "msiexec remote MSI"),
]

# Suspicious network: unusual listening ports
SUSPICIOUS_PORTS = {4444, 5555, 6666, 6667, 7777, 8888, 9999, 1337, 31337}

# Processes never flagged
SAFE_BY_NAME = {
    "python", "python3", "python.exe", "node", "node.exe",
    "code", "code.exe", "code insiders", "code-insiders.exe",
    "java", "java.exe", "javaw.exe",
    "docker", "dockerd", "containerd", "docker-compose",
    "git", "gh", "rustc", "cargo", "rust-analyzer",
    "postgres", "mongod", "redis-server",
    "hermes", "hermes.exe",
    "powershell", "pwsh", "cmd", "cmd.exe",
    "explorer", "System", "Idle", "smss", "csrss",
    "wininit", "services", "lsass", "svchost",
    "Memory Compression", "Registry",
}


# ── Core detection ───────────────────────────────────────────────────────────

def _exe_path(proc: psutil.Process) -> str:
    """Return the executable path for a process, or '' if inaccessible."""
    try:
        return proc.exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
        return ""


def _exe_path_from_info(info: ProcessInfo) -> str:
    """Return exe path for a ProcessInfo without a live psutil.Process handle."""
    try:
        return psutil.Process(info.pid).exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _cmdline(proc: psutil.Process) -> str:
    try:
        raw = proc.cmdline() or []
        return " ".join(raw)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _cwd(proc: psutil.Process) -> str:
    try:
        return proc.cwd() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _parent_exists(ppid: int) -> bool:
    try:
        psutil.Process(ppid).name()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _check_zombie(proc: psutil.Process, info: ProcessInfo) -> Optional[Finding]:
    try:
        status = proc.status()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        status = "unknown"
    if status in (psutil.STATUS_ZOMBIE, "zombie", "defunct"):
        return Finding(
            pid=info.pid, name=info.name,
            severity=SEV_WARN,
            category="zombie",
            detail="Process is in zombie state and will not exit on its own",
            evidence=f"status={status} ppid={info.parent_pid}",
            verdict="zombie",
        )
    return None


def _check_orphaned_worktree(info: ProcessInfo, cmdline: str, cwd: str) -> Optional[Finding]:
    """Processes whose cmdline/cwd reference deleted worktree directories."""
    norm = cmdline.replace("/", "\\")
    clues = []
    if ".worktrees" in norm and ("t_" in norm or "wt_" in norm):
        clues.append("worktree path in cmdline")
    if re.search(r"worktree.*deleted", norm, re.I):
        clues.append("'worktree deleted' path in cmdline")
    if cwd and ".worktrees" in cwd.replace("/", "\\"):
        clues.append("cwd is a worktree directory")
    if not clues:
        return None
    return Finding(
        pid=info.pid, name=info.name,
        severity=SEV_WARN,
        category="orphaned-worktree",
        detail="Process references a deleted Git worktree directory",
        evidence=f"cmdline={cmdline[:120]}  cwd={cwd}",
        verdict="orphaned",
        auto_kill=False,   # user must confirm; we may not own the process
    )


def _check_suspicious_cmdline(info: ProcessInfo, cmdline: str = "") -> Optional[Finding]:
    """Cmdline heuristic: download-execute, obfuscation, suspicious paths."""
    if not cmdline:
        cmdline = info.cmdline or ""
    if not cmdline:
        return None
    for pattern, reason in SUSPICIOUS_PATH_PATTERNS:
        if pattern.search(cmdline):
            return Finding(
                pid=info.pid, name=info.name,
                severity=SEV_HIGH,
                category="suspicious-cmdline",
                detail=reason,
                evidence=f"matched: {pattern.pattern}  cmdline={cmdline[:200]}",
                verdict="suspicious",
                auto_kill=False,
            )
    return None


def _check_suspicious_name(info: ProcessInfo, exe_path: str) -> Optional[Finding]:
    """Name heuristic: known-bad binary names."""
    name_lower = info.name.lower()
    for pattern, reason in SUSPICIOUS_NAME_PATTERNS:
        if pattern.search(info.name) or pattern.search(name_lower):
            # Crypto miners / RATs = critical
            sev = SEV_CRITICAL if "miner" in reason or "RAT" in reason else SEV_HIGH
            return Finding(
                pid=info.pid, name=info.name,
                severity=sev,
                category="known-bad-name",
                detail=reason,
                evidence=f"matched pattern: {pattern.pattern}  exe={exe_path}",
                verdict="suspicious",
                auto_kill=(sev == SEV_CRITICAL),
            )
    return None


def _check_suspicious_network(proc: psutil.Process, info: ProcessInfo) -> Optional[Finding]:
    """Connections to/from suspicious ports or unusual listening ports."""
    try:
        connections = proc.net_connections(kind="inet")
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return None
    findings = []
    for conn in connections:
        if conn.laddr and conn.laddr.port in SUSPICIOUS_PORTS:
            findings.append(f"listening on port {conn.laddr.port}")
        if conn.raddr:
            try:
                ip = conn.raddr.ip
                if ip.startswith(("192.168.", "10.", "172.")):
                    pass  # private = OK
                elif ip in ("127.0.0.1", "::1"):
                    pass
                elif conn.raddr.port in SUSPICIOUS_PORTS:
                    findings.append(f"connects to {ip}:{conn.raddr.port}")
            except Exception:
                pass
    if not findings:
        return None
    return Finding(
        pid=info.pid, name=info.name,
        severity=SEV_HIGH,
        category="suspicious-network",
        detail="; ".join(findings),
        evidence=f"matched suspicious port connections; exe={_exe_path(proc)}",
        verdict="suspicious",
        auto_kill=False,
    )


def _check_parentless(proc: psutil.Process, info: ProcessInfo) -> Optional[Finding]:
    """Daemon-style process whose parent is gone (init orphans, etc.).

    We only flag this when the process also has a suspicious characteristic:
    - non-standard executable path (not in system/program files)
    - cmdline references a worktree or temp path
    - unusual process name

    A normal Windows child process (chrome, explorer, taskmgr) going parentless
    after its parent exits is a normal lifecycle event and is not flagged.
    """
    if info.parent_pid <= 1:  # PID 0 or 1 (init/systemd)
        return None
    if not _parent_exists(info.parent_pid):
        cmdline = info.cmdline or ""
        norm = cmdline.replace("/", "\\")
        # Suspicious signals that warrant flagging a parentless process
        suspicious = (
            ".worktrees" in norm or
            re.search(r"\\Temp\\", norm, re.I) or
            re.search(r"\\AppData\\Roaming\\", norm, re.I) or
            # Random-looking process name (8+ hex chars, no spaces)
            bool(re.match(r"^[a-f0-9]{8,}$", info.name, re.I))
        )
        if not suspicious:
            return None  # normal orphan; skip
        return Finding(
            pid=info.pid, name=info.name,
            severity=SEV_WARN,
            category="parentless",
            detail=f"Parent PID={info.parent_pid} not found; process may be orphaned",
            evidence=f"ppid={info.parent_pid} cmdline={cmdline[:100]}",
            verdict="orphaned",
            auto_kill=False,
        )
    return None


def _single_check(proc: psutil.Process, info: ProcessInfo) -> List[Finding]:
    findings: List[Finding] = []
    exe_path = _exe_path(proc)
    cmdline  = info.cmdline or _cmdline(proc)
    cwd      = info.cwd     or _cwd(proc)

    # Fast checks first
    checks = [
        _check_zombie,
        lambda i, c=cmdline, w=cwd: _check_orphaned_worktree(i, c, w),
        lambda i, e=exe_path:     _check_suspicious_name(i, e),
        lambda i, c=cmdline:      _check_suspicious_cmdline(i, c),
        lambda i, c=cmdline:      _check_suspicious_network(proc, i) if cmdline else None,
        lambda i:                 _check_parentless(proc, i),
    ]
    for fn in checks:
        try:
            result = fn(info)
            if result:
                findings.append(result)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return findings


# ── Public API ───────────────────────────────────────────────────────────────

def guard_audit(threshold_mb: int = 50, include_clean: bool = False,
                check_network: bool = True) -> dict:
    """Scan all processes above threshold_mb for suspicious behaviour.

    Returns a structured report dict with:
      - findings: list of Finding objects (as dicts)
      - summary:  counts by severity and verdict
      - safe:     list of clean processes scanned
    """
    findings: List[Finding] = []
    safe: List[dict] = []
    all_procs = list_processes(threshold_mb)

    for info in all_procs:
        if info.name.lower() in SAFE_BY_NAME:
            if include_clean:
                safe.append({"pid": info.pid, "name": info.name, "ram_mb": info.ram_mb})
            continue
        # Name-based checks only need ProcessInfo (no psutil.Process needed).
        # Run them first so they catch processes even if the psutil.Process
        # handle is gone by the time we call psutil.Process().
        name_hit = _check_suspicious_name(info, _exe_path_from_info(info))
        if name_hit:
            findings.append(name_hit)
        elif include_clean:
            safe.append({"pid": info.pid, "name": info.name, "ram_mb": info.ram_mb})
        # psutil-based checks require a live handle.
        try:
            proc = psutil.Process(info.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for fn, fn_args in (
            (_check_suspicious_cmdline,  (info,)),
            (_check_suspicious_network,  (proc, info)),
            (_check_parentless,         (proc, info)),
            (_check_orphaned_worktree,  (info, info.cmdline, info.cwd)),
            (_check_zombie,             (proc, info)),
        ):
            try:
                result = fn(*fn_args)
                if result:
                    findings.append(result)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    # Sort: critical first, then high, warning, info
    order = {SEV_CRITICAL: 0, SEV_HIGH: 1, SEV_WARN: 2, SEV_INFO: 3}
    findings.sort(key=lambda f: (order.get(f.severity, 4), -f.pid))

    return {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "platform": platform.system(),
        "threshold_mb": threshold_mb,
        "processes_scanned": len(all_procs),
        "findings": [vars(f) for f in findings],
        "summary": {
            "total":     len(findings),
            "critical":  sum(1 for f in findings if f.severity == SEV_CRITICAL),
            "high":      sum(1 for f in findings if f.severity == SEV_HIGH),
            "warning":   sum(1 for f in findings if f.severity == SEV_WARN),
            "info":      sum(1 for f in findings if f.severity == SEV_INFO),
            "orphaned":  sum(1 for f in findings if f.verdict == "orphaned"),
            "zombie":    sum(1 for f in findings if f.verdict == "zombie"),
            "suspicious": sum(1 for f in findings if f.verdict == "suspicious"),
            "auto_kill": sum(1 for f in findings if f.auto_kill),
        },
        "safe_processes": safe,
    }


def kill_finding(pid: int) -> bool:
    """Terminate a process by PID. Returns True on success."""
    try:
        psutil.Process(pid).kill()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def kill_findings(findings: List[Finding], *, execute: bool = False) -> dict:
    """Terminate processes listed in findings.

    Safety: always dry-run by default. Pass execute=True to actually kill.
    Only kills findings where verdict is 'zombie' or auto_kill=True
    unless execute=True is set (user explicitly accepts risk).
    """
    killed, skipped = [], []
    for f in findings:
        if not execute:
            skipped.append({"pid": f.pid, "name": f.name, "reason": f.detail})
            continue
        # When execute=True, kill everything flagged (user accepted risk)
        ok = kill_finding(f.pid)
        (killed if ok else skipped).append({"pid": f.pid, "name": f.name})
    return {"dry_run": not execute, "killed": killed, "skipped": skipped}


# ── Output formatting ────────────────────────────────────────────────────────

def print_guard_report(report: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  PROCESS GUARD — {report['timestamp']}")
    print(f"  Platform: {report['platform']}  |  Scanned: {report['processes_scanned']} heavy processes")
    print(f"{'='*60}")

    s = report["summary"]
    print(f"\n  Summary: {s['total']} finding(s)")
    if s["critical"]:  print(f"    {s['critical']:>3} CRITICAL   (auto-kill candidate)")
    if s["high"]:      print(f"    {s['high']:>3} HIGH        (suspicious)")
    if s["warning"]:   print(f"    {s['warning']:>3} WARNING     (orphaned / zombie)")
    if s["info"]:      print(f"    {s['info']:>3} INFO")
    print(f"\n  Verdict: {s['orphaned']} orphaned  |  {s['zombie']} zombie  |  {s['suspicious']} suspicious")

    findings = report["findings"]
    if not findings:
        print("\n  No suspicious processes detected.")
        return

    print(f"\n  Findings:")
    for f in findings:
        # Support both Finding dataclass and plain dict (from JSON report)
        sev  = f.severity  if hasattr(f, "severity")  else f["severity"]
        pid  = f.pid       if hasattr(f, "pid")         else f["pid"]
        name = f.name      if hasattr(f, "name")        else f["name"]
        verd = f.verdict   if hasattr(f, "verdict")   else f["verdict"]
        auto = f.auto_kill if hasattr(f, "auto_kill") else f["auto_kill"]
        cat  = f.category  if hasattr(f, "category")   else f["category"]
        det  = f.detail    if hasattr(f, "detail")    else f["detail"]
        ev   = f.evidence  if hasattr(f, "evidence")   else f["evidence"]

        sev_icon = {"critical": "🔴", "high": "🟠", "warning": "🟡", "info": "⚪"}.get(sev, "  ")
        verdict_tag = f"[{verd}]{' [AUTO-KILL]' if auto else ''}"
        print(f"\n  {sev_icon} PID={pid:>6}  {name:<40} {verdict_tag}")
        print(f"     Category : {cat}")
        print(f"     Severity : {sev}")
        print(f"     Detail   : {det}")
        print(f"     Evidence : {ev[:120]}")

    print(f"\n  To terminate:  workstation guard --kill --pid <PID> --execute")
    print(f"  Dry-run kill: workstation guard --kill --pid <PID>")
