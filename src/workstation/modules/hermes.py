"""Hermes-specific modules."""
import os, sqlite3
from workstation.config import get_hermes_home, get_hermes_profile

def hermes_health() -> dict:
    home = get_hermes_home()
    profile = get_hermes_profile()
    state_db = os.path.join(profile, "state.db")

    result = {
        "hermes_home": home,
        "hermes_profile": profile,
        "state_db_exists": os.path.exists(state_db),
        "state_db_mb": 0,
        "state_db_integrity": None,
        "state_db_wal_mb": 0,
        "skills_count": _count_skills(profile),
        "version": None,
    }

    if result["state_db_exists"]:
        result["state_db_mb"] = round(os.path.getsize(state_db) / (1024**2), 2)
        wal = state_db + "-wal"
        shm = state_db + "-shm"
        result["state_db_wal_mb"] = round(os.path.getsize(wal) / (1024**2), 2) if os.path.exists(wal) else 0
        # Keep default health checks responsive on multi-GB state databases.
        # A full integrity scan is exposed separately by a future repair tool.
        if result["state_db_mb"] > 1024:
            result["state_db_integrity"] = "skipped: database >1 GB (use repair/integrity command)"
        else:
            result["state_db_integrity"] = _check_integrity(state_db)

    # Try to get version
    import subprocess
    try:
        r = subprocess.run(["hermes", "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            result["version"] = r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return result

def _check_integrity(path: str) -> str:
    """Run a bounded read-only SQLite integrity probe.

    Large, actively written Hermes databases can take minutes for a full
    `integrity_check`; the default health command must stay responsive.
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        conn.execute("PRAGMA busy_timeout = 2000")
        result = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
        conn.close()
        return result
    except Exception as e:
        return f"unavailable: {e}"

def _count_skills(profile: str) -> int:
    skills_dir = os.path.join(profile, "skills")
    if not os.path.isdir(skills_dir):
        return 0
    return sum(1 for _ in os.scandir(skills_dir) if _.is_dir() and not _.name.startswith("."))

def print_hermes_report(r: dict):
    print(f"\n=== Hermes Health ===")
    print(f"  Profile: {r['hermes_profile']}")
    print(f"  Version: {r['version'] or 'unknown'}")
    print(f"  state.db: {r['state_db_mb']} MB")
    if r["state_db_wal_mb"] > 0:
        print(f"  WAL: {r['state_db_wal_mb']} MB")
    print(f"  Integrity: {r['state_db_integrity']}")
    print(f"  Skills: {r['skills_count']}")
