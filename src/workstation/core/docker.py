"""Docker inspection — calls docker CLI, cross-platform."""
import subprocess, json, os
from concurrent.futures import ThreadPoolExecutor
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

    # The remaining Docker calls are independent of each other, and the
    # slowest one by far is `docker system df`: it walks the whole image and
    # build cache and took 15 seconds on this machine. The previous code ran
    # `system df` twice (once formatted for the image size, once for the build
    # cache) and every other call sequentially, so the state probe cost 25
    # seconds. One plain `system df` supplies both values, and the rest of the
    # calls now run concurrently.
    with ThreadPoolExecutor(max_workers=5) as pool:
        running_future = pool.submit(_run, "ps", "--format", "{{.Names}}")
        stopped_future = pool.submit(_run, "ps", "-a", "--filter", "status=exited",
                                      "--format", "{{.Names}}")
        images_future = pool.submit(_run, "images", "--format", "{{.Repository}}:{{.Tag}}")
        volumes_future = pool.submit(_run, "volume", "ls", "--format", "{{.Name}}")
        df_future = pool.submit(_run, "system", "df")

    stdout, _ = running_future.result()
    running_names = [n for n in stdout.splitlines() if n.strip()]
    containers = len(running_names)

    stdout, _ = stopped_future.result()
    stopped_count = len([n for n in stdout.splitlines() if n.strip()])

    stdout, _ = images_future.result()

    stdout, _ = volumes_future.result()
    volumes_count = len([v for v in stdout.splitlines() if v.strip()])

    # One `system df` reports both the image size and the build cache. The
    # table form is used rather than `--format`: on Docker Desktop for
    # Windows the formatted variant fails with a containerd snapshotter
    # error, while the plain table succeeds.
    #
    # The table rows are not fixed width. The TYPE label can be one word
    # ("Images") or two ("Build Cache", "Local Volumes"), and RECLAIMABLE is
    # either one field ("0B") or two ("0B (0%)"). The SIZE column is the
    # first field after TYPE, TOTAL and ACTIVE that carries a size unit,
    # and TOTAL and ACTIVE are always plain counts, so the size is the
    # first field that is not a bare integer.
    df_out, _ = df_future.result()
    images_size = "N/A"
    build_cache = "N/A"
    for line in df_out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        # The label may be two words, so it is read as everything before the
        # numeric columns rather than as a single field.
        label = " ".join(parts[:2]).lower()
        # Skip the header row.
        if label.startswith("type"):
            continue
        size = None
        for candidate in parts[2:]:
            if candidate.isdigit():
                continue
            size = candidate
            break
        if size is None:
            continue
        if label.startswith("images") and images_size == "N/A":
            images_size = size
        elif label.startswith("build cache") and build_cache == "N/A":
            build_cache = size

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
