"""Git worktree audit — cross-platform."""
import subprocess, os
from dataclasses import dataclass
from typing import List

@dataclass
class WorktreeInfo:
    path: str
    repo: str
    is_known: bool  # registered in git worktree list
    is_orphaned: bool  # physical dir exists but not in git list
    is_locked: bool  # can't delete (Windows handle)
    size_mb: float
    branch: str

def _run_git(repo: str, *args) -> tuple[str, int]:
    try:
        r = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip(), r.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "", 1

def _dir_size(path: str) -> float:
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    total += _dir_size(entry.path)
            except (PermissionError, OSError):
                pass
    except (PermissionError, OSError):
        pass
    return total / (1024**2)

def get_git_worktrees(repo: str) -> dict:
    """Return normalized worktree-path -> branch from Git porcelain output."""
    stdout, code = _run_git(repo, "worktree", "list", "--porcelain")
    known = {}
    if code != 0:
        return known

    current = None
    for line in stdout.splitlines():
        if line.startswith("worktree "):
            current = line.removeprefix("worktree ").strip()
            known.setdefault(os.path.normcase(os.path.normpath(current)), "detached")
        elif line.startswith("branch ") and current:
            known[os.path.normcase(os.path.normpath(current))] = line.removeprefix("branch ").strip()
        elif not line.strip():
            current = None
    return known

def audit_repo_worktrees(repo: str) -> List[WorktreeInfo]:
    """Audit worktrees for a single repo."""
    wt_dir = os.path.join(repo, ".worktrees")
    if not os.path.isdir(wt_dir):
        return []

    known = get_git_worktrees(repo)
    results = []
    for entry in os.scandir(wt_dir):
        if not entry.is_dir():
            continue
        path = entry.path
        size_mb = round(_dir_size(path), 2)
        normalized_path = os.path.normcase(os.path.normpath(path))
        branch = known.get(normalized_path, "unknown")
        is_known = normalized_path in known
        is_orphaned = not is_known

        # Try a simple delete to check lock
        is_locked = False
        if is_orphaned:
            try:
                os.rmdir(path)  # Only works on empty dirs
                is_locked = False
            except OSError:
                is_locked = True

        results.append(WorktreeInfo(
            path=path,
            repo=repo,
            is_known=is_known,
            is_orphaned=is_orphaned,
            is_locked=is_locked,
            size_mb=size_mb,
            branch=branch,
        ))
    return results

def audit_all_worktrees(repos: List[str]) -> dict:
    """Audit worktrees across all repos. Returns summary dict."""
    orphaned, known, locked, errors = [], [], [], {}
    for repo in repos:
        try:
            wts = audit_repo_worktrees(repo)
            for wt in wts:
                if wt.is_known:
                    known.append(wt)
                elif wt.is_locked:
                    locked.append(wt)
                else:
                    orphaned.append(wt)
        except Exception as e:
            errors[repo] = str(e)
    return {
        "orphaned": orphaned,
        "known": known,
        "locked": locked,
        "errors": errors,
        "total_orphaned_size_mb": round(sum(w.size_mb for w in orphaned), 2),
    }

def delete_worktree(wt: WorktreeInfo, force: bool = True) -> bool:
    """Delete an orphaned worktree directory."""
    import shutil
    if wt.is_known:
        return False  # Don't delete known worktrees
    try:
        shutil.rmtree(wt.path)
        return True
    except OSError:
        return False

def delete_orphaned(report: dict, confirm: bool = True) -> List[str]:
    """Delete all orphaned (non-locked) worktrees. Returns deleted paths."""
    deleted = []
    if confirm:
        print(f"Will delete {len(report['orphaned'])} orphaned worktrees? y/N: ", end="")
        if input().strip().lower() != "y":
            print("Aborted.")
            return []
    for wt in report["orphaned"]:
        if wt.is_locked:
            print(f"SKIP (locked): {wt.path}")
            continue
        if delete_worktree(wt):
            deleted.append(wt.path)
            print(f"DELETED: {wt.path} ({wt.size_mb} MB)")
        else:
            print(f"FAILED: {wt.path}")
    return deleted

def print_worktree_report(report: dict):
    print(f"\n=== Worktree Audit ===")
    print(f"  Known:      {len(report['known'])}")
    print(f"  Orphaned:  {len(report['orphaned'])} ({report['total_orphaned_size_mb']} MB)")
    print(f"  Locked:    {len(report['locked'])}")
    if report["errors"]:
        print(f"  Errors:    {len(report['errors'])}")
    if report["orphaned"]:
        print(f"\n  Orphaned worktrees:")
        for wt in report["orphaned"]:
            lock_flag = " [LOCKED]" if wt.is_locked else ""
            print(f"    {wt.path} ({wt.size_mb} MB){lock_flag}")
    if report["locked"]:
        print(f"\n  Locked (need reboot):")
        for wt in report["locked"]:
            print(f"    {wt.path}")
