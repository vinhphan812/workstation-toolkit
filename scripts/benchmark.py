"""Reproducible benchmark harness for the workstation toolkit.

The performance claims made about the filesystem and audit scans are only
meaningful if a second person can repeat the measurement and land on the
same figure. This script is that harness. It is committed to the repository
so the claim and its evidence travel together.

Run it on a committed tree, with no other work in flight on the machine:

    python scripts/benchmark.py --output benchmarks/latest.json

A benchmark launched while other processes are running measures the machine
rather than the code, so the script records the environment it ran in and
refuses to report a comparison it did not actually make.

The script never mutates anything: it walks directories, and it runs the
read-only toolkit commands.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from workstation.core.fsscan import dir_size_bytes  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _environment(repo: Path | None = None) -> dict:
    """The environment the measurement was taken in.

    A timing without its environment is not a measurement, it is a number.
    """
    target = repo or REPO_ROOT
    return {
        "timestamp_utc": _now(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "cpu_count": os.cpu_count(),
        "git_commit": _git_in(target, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_in(target, "status", "--porcelain")),
    }


def _git_in(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _pathlib_size(root: Path) -> int:
    """Legacy-style traversal, excluding symlink/reparse-point targets."""
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_symlink():
                continue
            stat = path.stat(follow_symlinks=False)
            if getattr(stat, "st_file_attributes", 0) & 0x400:
                continue
            if path.is_file():
                total += stat.st_size
        except OSError:
            continue
    return total


def _measure_scan(root: Path, repeats: int) -> dict:
    """Compare both scanners fairly on one tree; totals must match."""
    strategies = {
        "pathlib_rglob": lambda: _pathlib_size(root),
        "shared_scandir": lambda: dir_size_bytes(root),
    }
    names = list(strategies)
    samples = {name: [] for name in names}
    totals = {name: None for name in names}
    for repeat in range(repeats):
        order = names if repeat % 2 == 0 else list(reversed(names))
        for name in order:
            start = time.perf_counter()
            total = strategies[name]()
            samples[name].append(time.perf_counter() - start)
            if totals[name] is not None and totals[name] != total:
                raise RuntimeError(f"{name} returned inconsistent totals")
            totals[name] = total
    if len(set(totals.values())) != 1:
        raise RuntimeError(f"strategy totals differ on the same tree: {totals!r}")
    return {
        "root": str(root),
        "entries": sum(1 for _ in root.rglob("*")),
        "repeats": repeats,
        "totals_match": True,
        "strategies": {
            name: {
                "total_bytes": totals[name],
                "seconds_min": round(min(samples[name]), 4),
                "seconds_median": round(statistics.median(samples[name]), 4),
                "seconds_max": round(max(samples[name]), 4),
            }
            for name in names
        },
    }


def _measure_cli(command: list[str], repeats: int) -> dict:
    """Time a read-only toolkit command as a subprocess."""
    timings = []
    exit_codes = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = subprocess.run(
            [sys.executable, "-m", "workstation", *command],
            cwd=REPO_ROOT, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )
        timings.append(time.perf_counter() - start)
        exit_codes.append(result.returncode)
    return {
        "command": " ".join(["workstation", *command]),
        "repeats": repeats,
        "exit_codes": exit_codes,
        "seconds_min": round(min(timings), 4),
        "seconds_median": round(statistics.median(timings), 4),
        "seconds_max": round(max(timings), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default=str(REPO_ROOT / "src"),
        help="the tree to walk for the scan measurement (default: src/)")
    parser.add_argument(
        "--repeats", type=int, default=3,
        help="how many times each measurement is repeated")
    parser.add_argument(
        "--cli-command", action="append", default=[],
        help="a read-only toolkit command to time; repeatable")
    parser.add_argument(
        "--output", default=None,
        help="write the raw result as JSON to this path")
    parser.add_argument(
        "--require-clean", action="store_true",
        help="refuse to run if the benchmark repository is dirty")
    parser.add_argument(
        "--repo", default=str(REPO_ROOT),
        help="the repository whose commit and cleanliness are recorded")
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")
    repo = Path(args.repo).resolve()
    environment = _environment(repo)
    if args.require_clean and environment["git_dirty"]:
        parser.error("the repository is dirty; commit or discard changes before benchmarking")

    measurements = {
        "environment": environment,
        "scan": _measure_scan(root, args.repeats),
        "cli": [_measure_cli(command.split(), args.repeats)
                for command in args.cli_command],
    }
    measurements["notes"] = [
        "Run on a committed tree with no other work in flight.",
        "The scanner timings are a same-tree microbenchmark; they do not "
        "prove an end-to-end speedup for a toolkit command.",
        "The harness and raw output are committed, so another person can "
        "repeat the measurement.",
        "A wall-clock timing alone does not attribute the time to this code; "
        "compare the median against a profile when the two disagree.",
    ]

    rendered = json.dumps(measurements, indent=2)
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote {destination}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
