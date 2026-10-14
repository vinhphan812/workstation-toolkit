"""System-level modules."""
import platform, os
from workstation.core import disk, docker, process
from workstation.adapters import windows, linux, macos

PLATFORM_MAP = {
    "windows": windows,
    "linux": linux,
    "darwin": macos,
}

def get_platform_adapter():
    adapter_module = PLATFORM_MAP.get(platform.system().lower())
    if adapter_module is None:
        return None
    if adapter_module is windows:
        return windows.WindowsAdapter()
    if adapter_module is linux:
        return linux.LinuxAdapter()
    if adapter_module is macos:
        return macos.MacOSAdapter()
    return None

def full_diagnostic() -> dict:
    """Return a complete system diagnostic report."""
    adapter = get_platform_adapter()
    return {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "platform": platform.system(),
        "platform_details": platform.platform(),
        "disk": _disk_report(),
        "ram": _ram_report(),
        "docker": _docker_report(),
        "firewall": adapter.get_firewall_status() if adapter else None,
        "git": _git_report(),
        "hermes": _hermes_report(),
        # The full home-directory scan belongs to the explicit `storage`
        # command. Keeping diagnose bounded makes it usable on large machines.
        "large_items": [],
    }

def _disk_report() -> dict:
    # Inspect the volume holding user-local app state rather than Python's
    # current working directory, which can be a different drive on Windows.
    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    info = disk.get_disk_info(local_app_data)
    return {
        "free_gb": info.free_gb,
        "total_gb": info.total_gb,
        "pct_used": info.pct_used,
        "system_drive": info.path,
    }

def _ram_report() -> dict:
    import psutil
    vm = psutil.virtual_memory()
    return {
        "total_gb": round(vm.total / (1024**3), 1),
        "free_gb": round(vm.free / (1024**3), 1),
        "used_gb": round(vm.used / (1024**3), 1),
        "pct_used": vm.percent,
    }

def _docker_report() -> dict:
    state = docker.get_state()
    return {
        "running": state.running,
        "containers": state.containers,
        "images_size": state.images_size,
        "volumes": state.volumes_count,
        "vhdx_gb": state.vhdx_gb,
        "error": state.error,
    }

def _git_report() -> dict:
    from workstation.core.git import get_global_identity
    gid = get_global_identity()
    return {
        "global_email": gid.email if gid else None,
        "global_name": gid.name if gid else None,
    }

def _hermes_report() -> dict:
    from workstation.config import get_hermes_home, get_hermes_profile
    home = get_hermes_home()
    profile = get_hermes_profile()
    state_db = os.path.join(profile, "state.db")
    return {
        "hermes_home": home,
        "hermes_profile": profile,
        "state_db_exists": os.path.exists(state_db),
        "state_db_mb": round(os.path.getsize(state_db) / (1024**2), 2) if os.path.exists(state_db) else 0,
    }

def storage_audit() -> dict:
    """Audit only configured high-value roots; bounded and cross-platform."""
    paths = [os.path.expanduser("~")]
    # On Windows, add each existing fixed drive root without descending into it.
    if os.name == "nt":
        import string
        paths = [f"{drive}:\\" for drive in string.ascii_uppercase if os.path.exists(f"{drive}:\\")]
    report = {}
    for path in paths:
        try:
            info = disk.get_disk_info(path)
            report[path] = {
                "total_gb": info.total_gb,
                "used_gb": info.used_gb,
                "free_gb": info.free_gb,
                "pct_used": info.pct_used,
            }
        except OSError as exc:
            report[path] = {"error": str(exc)}
    return report

def print_diagnostic(report: dict):
    print(f"\n=== System Diagnostic  [{report['timestamp']}] ===")
    print(f"Platform: {report['platform']} — {report['platform_details']}")

    # Disk
    d = report["disk"]
    color = "\033[91m" if d["free_gb"] < 10 else "\033[93m" if d["free_gb"] < 20 else "\033[92m"
    reset = "\033[0m"
    print(f"\nDisk: {color}{d['free_gb']} GB free / {d['total_gb']} GB{reset} ({d['pct_used']}% used)")

    # RAM
    r = report["ram"]
    rcolor = "\033[91m" if r["free_gb"] < 4 else "\033[93m" if r["free_gb"] < 8 else "\033[92m"
    print(f"RAM:  {rcolor}{r['free_gb']} GB free / {r['total_gb']} GB{reset}")

    # Docker
    dk = report["docker"]
    if dk["running"]:
        print(f"Docker: {dk['containers']} containers, images {dk['images_size']}, vhdx {dk['vhdx_gb']} GB")
    else:
        print(f"Docker: not running")

    # Git
    g = report["git"]
    print(f"Git: {g['global_name']} <{g['global_email']}>")

    # Hermes
    h = report["hermes"]
    print(f"Hermes profile: {h['hermes_profile']}")
    print(f"state.db: {h['state_db_mb']} MB" if h["state_db_exists"] else "state.db: not found")

    # Large items
    if report.get("large_items"):
        print(f"\nLarge items (>100 MB):")
        for item in report["large_items"][:10]:
            print(f"  {item['size_mb']:>8.1f} MB  {item['name'][:50]}")

def print_storage(data: dict):
    print(f"\n=== Storage Audit ===")
    for path, info in sorted(data.items(), key=lambda x: x[1]["total_gb"], reverse=True):
        print(f"  {path}: {info['free_gb']} GB free / {info['total_gb']} GB ({info['pct_used']}% used)")
