"""Docker inspection — calls docker CLI, cross-platform."""
import subprocess, json, os
from dataclasses import dataclass
from typing import List

@dataclass
class DockerState:
    running: bool
    containers: int
    running_names: List[str]
    stopped_count: int
    images_size: str
    volumes_count: int
    build_cache: str
    vhdx_gb: float
    error: str = ""

def _run(*args) -> tuple[str, int]:
    try:
        r = subprocess.run(
            ["docker"] + list(args),
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip(), r.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return str(e), 1

def get_state() -> DockerState:
    stdout, code = _run("info")
    if code != 0:
        return DockerState(running=False, containers=0, running_names=[],
                           stopped_count=0, images_size="N/A", volumes_count=0,
                           build_cache="N/A", vhdx_gb=0.0, error=stdout)

    # Running containers
    stdout, _ = _run("ps", "--format", "{{.Names}}")
    running_names = [n for n in stdout.splitlines() if n.strip()]
    containers = len(running_names)

    # Stopped containers
    stdout, _ = _run("ps", "-a", "--filter", "status=exited", "--format", "{{.Names}}")
    stopped_count = len([n for n in stdout.splitlines() if n.strip()])

    # Images size
    stdout, _ = _run("images", "--format", "{{.Repository}}:{{.Tag}}")
    # Total size via system df
    df_out, _ = _run("system", "df", "--format", "{{.Size}}")
    images_size = "N/A"
    for line in df_out.splitlines():
        if "Images" in line or line.startswith("Images"):
            parts = line.split()
            if len(parts) >= 2:
                images_size = parts[1] if len(parts) > 1 else parts[-1]
            break

    # Volumes count
    stdout, _ = _run("volume", "ls", "--format", "{{.Name}}")
    volumes_count = len([v for v in stdout.splitlines() if v.strip()])

    # Build cache
    build_cache = "N/A"
    stdout, _ = _run("system", "df")
    for line in stdout.splitlines():
        if "Build" in line:
            parts = line.split()
            build_cache = parts[-1] if parts else "N/A"
            break

    # VHDX size (Windows only)
    vhdx_gb = 0.0
    vhdx_path = os.path.expandvars("%LOCALAPPDATA%\\Docker\\wsl\\disk\\docker_data.vhdx")
    if os.path.exists(vhdx_path):
        vhdx_gb = round(os.path.getsize(vhdx_path) / (1024**3), 2)

    return DockerState(
        running=True,
        containers=containers,
        running_names=running_names,
        stopped_count=stopped_count,
        images_size=images_size,
        volumes_count=volumes_count,
        build_cache=build_cache,
        vhdx_gb=vhdx_gb,
    )

def prune_stopped() -> str:
    stdout, code = _run("container", "prune", "-f")
    return stdout or ("failed: " + stdout if code != 0 else "done")

def prune_images() -> str:
    stdout, code = _run("image", "prune", "-a", "-f")
    return stdout or ("failed" if code != 0 else "done")

def prune_volumes() -> tuple[str, int]:
    """Returns (message, count_removed)."""
    # Get orphaned volumes (not attached to running containers)
    running, _ = _run("ps", "--format", "{{.Names}}")
    used_vols = set()
    for c in running.splitlines():
        if not c.strip():
            continue
        out, _ = _run("inspect", c, "--format", "{{range .Mounts}}{{.Name}} {{end}}")
        for v in out.split():
            if v.strip():
                used_vols.add(v.strip())

    all_vols, _ = _run("volume", "ls", "--format", "{{.Name}}")
    orphaned = [v for v in all_vols.splitlines() if v.strip() and v not in used_vols]

    removed = 0
    for v in orphaned:
        out, code = _run("volume", "rm", v)
        if code == 0:
            removed += 1
    return f"Removed {removed}/{len(orphaned)} volumes", removed

def get_vhdx_size() -> float:
    vhdx_path = os.path.expandvars("%LOCALAPPDATA%\\Docker\\wsl\\disk\\docker_data.vhdx")
    if os.path.exists(vhdx_path):
        return round(os.path.getsize(vhdx_path) / (1024**3), 2)
    return 0.0
