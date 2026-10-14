"""Developer workstation audits: repo hygiene, toolchains, Java and Android SDK."""
from __future__ import annotations
import os, re, shutil, subprocess
from pathlib import Path
from workstation.config import load_repos
from workstation.core.git import is_repo_dirty, get_repo_branches, get_remotes


def _run(*args: str, timeout: int = 20) -> tuple[str, int]:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        return result.stdout.strip() or result.stderr.strip(), result.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return str(exc), 1


def repo_dirty_check() -> dict:
    entries = []
    for repo in load_repos():
        if not Path(repo, ".git").exists():
            continue
        entries.append({
            "name": Path(repo).name,
            "path": repo,
            "dirty": is_repo_dirty(repo),
            "branches": get_repo_branches(repo),
            "remotes": get_remotes(repo),
        })
    return {"repos": entries, "dirty_count": sum(item["dirty"] for item in entries)}


def stale_branches() -> dict:
    """Report local branches already merged into the repo default branch."""
    entries = []
    for repo in load_repos():
        if not Path(repo, ".git").exists():
            continue
        out, code = _run("git", "-C", repo, "branch", "--merged")
        if code:
            continue
        default = "master"
        branch_out, _ = _run("git", "-C", repo, "symbolic-ref", "refs/remotes/origin/HEAD", "--short")
        if branch_out.startswith("origin/"):
            default = branch_out.split("/", 1)[1]
        merged = [line.replace("*", "").strip() for line in out.splitlines()]
        candidates = [branch for branch in merged if branch and branch != default]
        entries.append({"name": Path(repo).name, "path": repo, "default_branch": default, "merged_local_branches": candidates})
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
    def dirs(name: str) -> list[dict]:
        base = root / name
        if not base.is_dir():
            return []
        return [{"name": item.name, "path": str(item), "size_mb": round(_dir_size(item) / (1024**2), 2)} for item in base.iterdir() if item.is_dir()]
    return {
        "status": "available", "sdk_root": str(root), "total_mb": round(_dir_size(root) / (1024**2), 2),
        "build_tools": dirs("build-tools"), "platforms": dirs("platforms"), "emulators": dirs("emulator"), "system_images": dirs("system-images"),
    }


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file(): total += item.stat().st_size
            except OSError: pass
    except OSError: pass
    return total


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
