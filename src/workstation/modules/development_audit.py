"""Developer workstation audits: repo hygiene, toolchains, Java and Android SDK."""
from __future__ import annotations
import os, re, shutil, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from workstation.config import load_repos
from workstation.core.git import get_repo_summary, is_repo_dirty, get_repo_branches, get_remotes
from workstation.core.fsscan import dir_size_bytes, dir_size_by_child_levels


def _run(*args: str, timeout: int = 20) -> tuple[str, int]:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        return result.stdout.strip() or result.stderr.strip(), result.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return str(exc), 1


def repo_dirty_check() -> dict:
    repos = [repo for repo in load_repos() if Path(repo, ".git").exists()]

    def inspect(repo: str) -> dict:
        summary = get_repo_summary(repo)
        return {
            "name": Path(repo).name,
            "path": repo,
            "dirty": summary["dirty"],
            "branches": summary["branches"],
            "remotes": summary["remotes"],
        }

    # Each repository costs three Git child processes and the parent spends
    # all of that time waiting, so the repositories are inspected
    # concurrently. Report order follows the configured order.
    with ThreadPoolExecutor(max_workers=min(8, len(repos) or 1)) as pool:
        entries = list(pool.map(inspect, repos))

    return {"repos": entries, "dirty_count": sum(item["dirty"] for item in entries)}


def stale_branches() -> dict:
    """Report local branches already merged into the repo default branch."""
    repos = [repo for repo in load_repos() if Path(repo, ".git").exists()]

    def inspect(repo: str) -> dict | None:
        out, code = _run("git", "-C", repo, "branch", "--merged")
        if code:
            return None
        default = "master"
        branch_out, _ = _run("git", "-C", repo, "symbolic-ref", "refs/remotes/origin/HEAD", "--short")
        if branch_out.startswith("origin/"):
            default = branch_out.split("/", 1)[1]
        merged = [line.replace("*", "").strip() for line in out.splitlines()]
        candidates = [branch for branch in merged if branch and branch != default]
        return {"name": Path(repo).name, "path": repo, "default_branch": default,
                "merged_local_branches": candidates}

    # The per-repo work is dominated by waiting for the Git child process, so
    # running the repositories concurrently is a genuine win rather than
    # contention. Ordering of the report is preserved.
    with ThreadPoolExecutor(max_workers=min(8, len(repos) or 1)) as pool:
        inspected = list(pool.map(inspect, repos))

    entries = [item for item in inspected if item is not None]
    return {"repos": entries, "stale_count": sum(len(item["merged_local_branches"]) for item in entries)}


def toolchain_audit() -> dict:
    tools = {}
    for executable, version_args in {
        "git": ["--version"], "java": ["-version"], "javac": ["-version"],
        "node": ["--version"], "npm": ["--version"], "uv": ["--version"],
        "python": ["--version"], "docker": ["--version"], "gradle": ["--version"],
    }.items():
        path = shutil.which(executable)
        if not path:
            tools[executable] = {"available": False}
            continue
        output, code = _run(executable, *version_args, timeout=10)
        tools[executable] = {"available": code == 0, "path": path, "version": output.splitlines()[0] if output else ""}
    return {"tools": tools}


def java_home_audit() -> dict:
    candidates = []
    seen = set()
    roots = [os.environ.get("JAVA_HOME", ""), "C:/Java", "C:/Program Files/Java", "C:/Program Files/Eclipse Adoptium"]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        root_path = Path(root)
        possible = [root_path] if (root_path / "bin" / "java.exe").exists() or (root_path / "bin" / "java").exists() else list(root_path.iterdir())
        for candidate in possible:
            java_bin = candidate / "bin" / ("java.exe" if os.name == "nt" else "java")
            if not java_bin.exists() or str(candidate) in seen:
                continue
            seen.add(str(candidate))
            out, _ = _run(str(java_bin), "-version", timeout=10)
            candidates.append({"path": str(candidate), "version": out.splitlines()[0] if out else "unknown", "active": os.path.normcase(str(candidate)) == os.path.normcase(os.environ.get("JAVA_HOME", ""))})
    return {"java_home": os.environ.get("JAVA_HOME"), "jdks": candidates}


def android_sdk_audit() -> dict:
    sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if not sdk:
        possible = Path.home() / "AppData" / "Local" / "Android" / "Sdk"
        sdk = str(possible) if possible.exists() else ""
    root = Path(sdk)
    if not root.is_dir():
        return {"status": "unavailable", "reason": "ANDROID_SDK_ROOT not found", "sdk_root": sdk}

    # One traversal of the SDK yields both the total and the size of every
    # package directory. The previous implementation measured the root and
    # then re-walked build-tools, platforms, emulator and system-images,
    # repeating roughly a quarter of the whole SDK.
    levels = dir_size_by_child_levels(root, (1, 2))
    depth1, depth2 = levels[1], levels[2]

    def dirs(name: str) -> list[dict]:
        base = root / name
        if not base.is_dir():
            return []
        entries = []
        for item in sorted(base.iterdir()):
            if not item.is_dir():
                continue
            key = f"{name}{os.sep}{item.name}"
            entries.append({
                "name": item.name,
                "path": str(item),
                "size_mb": round(depth2.get(key, 0) / (1024 ** 2), 2),
            })
        return entries

    families = {
        "build_tools": dirs("build-tools"),
        "platforms": dirs("platforms"),
        "emulators": dirs("emulator"),
        "system_images": dirs("system-images"),
    }
    total_mb = round(sum(depth1.values()) / (1024 ** 2), 2)
    return {
        "status": "available", "sdk_root": str(root), "total_mb": total_mb,
        **families,
    }


def _dir_size(path: Path) -> int:
    """Return the size in bytes of every file under *path*.

    Kept as a module-level name because the audit helpers below call it and
    because the test suite patches it.
    """
    return dir_size_bytes(path)


def print_repo_check(report: dict) -> None:
    print("\n=== Repository Status ===")
    print(f"Repos: {len(report['repos'])}; dirty: {report['dirty_count']}")
    for item in report["repos"]:
        print(f"  [{'DIRTY' if item['dirty'] else 'CLEAN'}] {item['name']} — branches={len(item['branches'])}, remotes={len(item['remotes'])}")


def print_toolchain(report: dict) -> None:
    print("\n=== Toolchain Audit ===")
    for name, item in report["tools"].items():
        state = "OK" if item.get("available") else "MISSING"
        print(f"  [{state}] {name}: {item.get('version', '')} {item.get('path', '')}")
