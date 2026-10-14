"""Storage forecasting and conservative cleanup planning."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
from workstation.core.disk import get_disk_info
from workstation.config import get_hermes_profile


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def disk_space_forecast() -> dict:
    """Report current disk pressure and known large managed artefacts.

    This is intentionally advisory: it does not estimate a time-to-full value
    without a historical series, and it never deletes candidates.
    """
    roots = _windows_roots() if os.name == 'nt' else [Path('/')]
    drives = []
    for root in roots:
        info = get_disk_info(str(root))
        drives.append(info.__dict__)

    profile = Path(get_hermes_profile())
    candidates = []
    state_db = profile / 'state.db'
    if state_db.exists():
        candidates.append({
            'category': 'Hermes state database', 'path': str(state_db),
            'size_mb': round(_size(state_db) / (1024**2), 2),
            'safe_action': 'Backup and use a dedicated repair/vacuum command; do not delete.',
            'risk': 'high',
        })
    for suffix, label in [('-wal', 'Hermes state WAL'), ('-shm', 'Hermes state shared memory')]:
        path = Path(str(state_db) + suffix)
        if path.exists():
            candidates.append({
                'category': label, 'path': str(path), 'size_mb': round(_size(path)/(1024**2), 2),
                'safe_action': 'Do not delete while Hermes is running; checkpoint through SQLite maintenance.',
                'risk': 'high',
            })
    docker_vhd = Path(os.path.expandvars(r'%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx'))
    if docker_vhd.exists():
        candidates.append({
            'category': 'Docker WSL VHDX', 'path': str(docker_vhd), 'size_mb': round(_size(docker_vhd)/(1024**2), 2),
            'safe_action': 'Use docker prune first; compact only with Docker stopped and a verified backup.',
            'risk': 'high',
        })
    android_sdk = Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or Path.home() / 'AppData/Local/Android/Sdk')
    if android_sdk.exists():
        candidates.append({
            'category': 'Android SDK', 'path': str(android_sdk), 'size_mb': round(_tree_size(android_sdk)/(1024**2), 2),
            'safe_action': 'Use android-sdk audit; remove packages only after checking project requirements.',
            'risk': 'medium',
        })
    return {'generated_at': datetime.now(timezone.utc).isoformat(), 'drives': drives, 'managed_candidates': candidates,
            'note': 'Forecast requires historical reports. Run this command with --save-report periodically to establish a growth baseline.'}


def _windows_roots() -> list[Path]:
    import string
    return [Path(f'{letter}:/') for letter in string.ascii_uppercase if os.path.exists(f'{letter}:/')]


def _tree_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob('*'):
            try:
                if item.is_file(): total += item.stat().st_size
            except OSError: pass
    except OSError: pass
    return total


def print_forecast(report: dict) -> None:
    print('\n=== Disk Space Forecast ===')
    for drive in report['drives']:
        state = 'CRITICAL' if drive['free_gb'] < 10 else 'WARNING' if drive['free_gb'] < 20 else 'OK'
        print(f"  [{state}] {drive['path']}: {drive['free_gb']} GB free / {drive['total_gb']} GB ({drive['pct_used']}% used)")
    print('\nManaged large artefacts:')
    for item in report['managed_candidates']:
        print(f"  [{item['risk'].upper()}] {item['size_mb']:,.1f} MB — {item['category']}")
        print(f"      {item['safe_action']}")
