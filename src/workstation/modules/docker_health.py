"""Runtime Docker service health and bounded log inspection."""
from __future__ import annotations
import subprocess
from workstation.core.docker import get_state

def _run(*args: str, timeout: int = 15) -> tuple[str, int]:
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() or r.stderr.strip(), r.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return str(exc), 1

def docker_service_health(log_lines: int = 30) -> dict:
    state = get_state()
    if not state.running:
        return {"status": "unavailable", "error": state.error, "containers": []}
    names, _ = _run("ps", "--format", "{{.Names}}")
    containers = []
    for name in filter(None, names.splitlines()):
        inspect, code = _run("inspect", name, "--format", "{{json .State}}")
        logs, log_code = _run("logs", "--tail", str(log_lines), name, timeout=20)
        containers.append({"name": name, "state_raw": inspect if code == 0 else None, "recent_logs": logs[-4000:] if log_code == 0 else "unavailable"})
    return {"status": "available", "containers": containers}

def docker_log_tail(container: str, lines: int = 100) -> dict:
    output, code = _run("logs", "--tail", str(lines), container, timeout=30)
    return {"container": container, "lines": lines, "ok": code == 0, "output": output}
