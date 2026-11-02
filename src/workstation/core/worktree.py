"""Git worktree audit — cross-platform."""
import subprocess, os
from dataclasses import dataclass
from typing import List

# Lock states. `is_locked` alone cannot express "we have no evidence", so the
# audit reports one of three states instead of guessing.
LOCK_UNKNOWN = "unknown"    # no reliable platform evidence available
LOCK_LOCKED = "locked"      # reliable evidence: the path is held open
LOCK_UNLOCKED = "unlocked"  # reliable evidence: the path is not held open

# Windows offers a reliable, non-mutating probe (CreateFileW with DELETE
# access). POSIX has no equivalent: unlinking an open file is legal there, so
# there is no kernel-enforced "lock" to observe.
LOCK_PROBE_SUPPORTED = os.name == "nt"


@dataclass
class WorktreeInfo:
    path: str
    repo: str
    is_known: bool  # registered in git worktree list
    is_orphaned: bool  # physical dir exists but not in git list
    is_locked: bool  # can't delete (Windows handle)
    size_mb: float
    branch: str
    lock_state: str = LOCK_UNKNOWN  # one of LOCK_UNKNOWN / LOCK_LOCKED / LOCK_UNLOCKED

    def __post_init__(self):
        if self.lock_state not in (LOCK_UNKNOWN, LOCK_LOCKED, LOCK_UNLOCKED):
            self.lock_state = LOCK_UNKNOWN
        if self.lock_state == LOCK_LOCKED:
            self.is_locked = True
        elif self.lock_state == LOCK_UNLOCKED:
            self.is_locked = False
        # For LOCK_UNKNOWN the caller-supplied is_locked is preserved: a caller
        # that asserts a lock explicitly keeps its claim, but the audit itself
        # never asserts one without platform evidence.

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

def _probe_lock_state(path: str) -> str:
    """Report the lock state of *path* without mutating it.

    Returns LOCK_LOCKED when reliable platform evidence says the path is held
    open, LOCK_UNLOCKED when reliable evidence says it is not, and
    LOCK_UNKNOWN when the platform offers no such evidence.

    On Windows the probe opens the directory with DELETE access and
    FILE_FLAG_BACKUP_SEMANTICS. That request fails with
    ERROR_SHARING_VIOLATION (32) when another handle holds the directory
    without FILE_SHARE_DELETE, and succeeds otherwise. The handle is closed
    immediately and nothing is created, renamed, or removed.

    On POSIX there is no kernel-enforced lock on a directory: an open file can
    always be unlinked, so no read-only probe can distinguish "locked" from
    "not locked". Reporting LOCK_UNKNOWN there is the honest answer.
    """
    if not LOCK_PROBE_SUPPORTED:
        return LOCK_UNKNOWN
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.restype = wintypes.HANDLE
        create_file.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        close_handle = kernel32.CloseHandle
        close_handle.restype = wintypes.BOOL
        close_handle.argtypes = [wintypes.HANDLE]

        delete_access = 0x00010000
        share_all = 0x00000001 | 0x00000002 | 0x00000004
        open_existing = 3
        backup_semantics = 0x02000000
        invalid_handle = wintypes.HANDLE(-1).value

        handle = create_file(
            os.path.abspath(path), delete_access, share_all, None,
            open_existing, backup_semantics, None,
        )
        if handle == invalid_handle or handle is None:
            # 32 == ERROR_SHARING_VIOLATION: another handle blocks deletion.
            return LOCK_LOCKED if ctypes.get_last_error() == 32 else LOCK_UNKNOWN
        close_handle(handle)
        return LOCK_UNLOCKED
    except Exception:
        return LOCK_UNKNOWN


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

        # Lock state cannot be inferred from a directory probe: rmdir is
        # destructive for empty paths and fails for every nonempty path.
        # Use a read-only, platform-specific probe instead, and report
        # LOCK_UNKNOWN where no reliable evidence exists.
        lock_state = _probe_lock_state(path)
        is_locked = lock_state == LOCK_LOCKED

        results.append(WorktreeInfo(
            path=path,
            repo=repo,
            is_known=is_known,
            is_orphaned=is_orphaned,
            is_locked=is_locked,
            size_mb=size_mb,
            branch=branch,
            lock_state=lock_state,
        ))
    return results

def audit_all_worktrees(repos: List[str]) -> dict:
    """Audit worktrees across all repos. Returns summary dict."""
    orphaned, known, locked, lock_unknown, errors = [], [], [], [], {}
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
                    if wt.lock_state == LOCK_UNKNOWN:
                        lock_unknown.append(wt)
        except Exception as e:
            errors[repo] = str(e)
    return {
        "orphaned": orphaned,
        "known": known,
        "locked": locked,
        "lock_unknown": lock_unknown,
        "errors": errors,
        "total_orphaned_size_mb": round(sum(w.size_mb for w in orphaned), 2),
    }

def _worktree_marker_admin_dir(tree: str) -> str | None:
    """Return the admin dir an in-tree worktree marker points at, or None.

    A linked worktree carries an in-tree `.git` *file* whose first line is
    `gitdir: <path>`. The path may be absolute or relative to `tree`.
    A `.git` *directory* is not a worktree marker (that is a nested
    repository) and yields None.
    """
    marker = os.path.join(tree, ".git")
    if os.path.islink(marker) or not os.path.isfile(marker):
        return None
    try:
        with open(marker, "r", encoding="utf-8", errors="replace") as fh:
            first = fh.readline().strip()
    except OSError:
        return None
    if not first.lower().startswith("gitdir:"):
        return None
    admin = first.split(":", 1)[1].strip()
    if not admin:
        return None
    if not os.path.isabs(admin):
        admin = os.path.join(tree, admin)
    return os.path.normpath(admin)

def _is_live_worktree_registration(tree: str) -> bool:
    """True when `tree` carries a live Git worktree registration.

    Git creates the administrative directory *before* it writes the in-tree
    marker, so a marker whose admin dir still exists means the worktree is
    registered (or its registration is completing right now). A marker whose
    admin dir is gone is stale -- the tree is a genuine orphan and must stay
    deletable.
    """
    admin = _worktree_marker_admin_dir(tree)
    if admin is None:
        return False
    return os.path.isdir(admin)

def delete_worktree(wt: WorktreeInfo, force: bool = True) -> bool:
    """Delete a positively classified orphan beneath this repo's .worktrees."""
    import shutil
    if wt.is_known or not wt.is_orphaned or wt.is_locked:
        return False
    try:
        repo = os.path.realpath(wt.repo)
        root = os.path.realpath(os.path.join(repo, ".worktrees"))
        candidate = os.path.abspath(wt.path)
        target = os.path.realpath(candidate)
        # Require an immediate child and reject symlinks in the supplied path.
        if os.path.commonpath([root, target]) != root or target == root:
            return False
        if os.path.dirname(candidate) != os.path.abspath(os.path.join(repo, ".worktrees")):
            return False
        if os.path.islink(candidate) or target != candidate or not os.path.isdir(target):
            return False
        # Capture the directory entry identity, then atomically move it to an
        # unpredictable sibling before the final Git registration check. This
        # prevents a path swap from redirecting recursive deletion elsewhere.
        before = os.stat(candidate, follow_symlinks=False)
        quarantine = os.path.join(
            os.path.dirname(candidate), f".delete-{os.getpid()}-{os.urandom(16).hex()}"
        )
        os.rename(candidate, quarantine)
        moved = os.stat(quarantine, follow_symlinks=False)
        if (moved.st_dev, moved.st_ino) != (before.st_dev, before.st_ino):
            if not os.path.lexists(candidate):
                os.rename(quarantine, candidate)
            return False
        if os.path.islink(quarantine) or not os.path.isdir(quarantine):
            if not os.path.lexists(candidate):
                os.rename(quarantine, candidate)
            return False
        # Re-query after the atomic move. A registration racing before the move
        # still names candidate; a registration targeting the quarantine path
        # is also refused. A newly created candidate is never recursively
        # removed because deletion is confined to the quarantined entry.
        stdout, code = _run_git(repo, "worktree", "list", "--porcelain")
        if code != 0:
            if not os.path.lexists(candidate):
                os.rename(quarantine, candidate)
            return False
        registered = {os.path.normcase(os.path.normpath(line[9:].strip()))
                      for line in stdout.splitlines() if line.startswith("worktree ")}
        quarantined = os.path.normcase(os.path.normpath(quarantine))
        normalized = os.path.normcase(os.path.normpath(candidate))
        if normalized in registered or quarantined in registered:
            if not os.path.lexists(candidate):
                os.rename(quarantine, candidate)
            return False
        if os.path.lexists(candidate):
            # A replacement claimed the original name. Preserve both trees.
            return False
        # Boundary check. A registration can complete after the final
        # listing query above has taken its snapshot, so the listing cannot
        # observe it. The quarantined tree's own in-tree marker is the
        # registration's own record and is written by Git as part of that
        # registration, so it is read here at the destructive boundary
        # rather than from a repo-wide snapshot. A tree carrying a marker
        # for a live admin dir is a registered worktree and is never
        # recursively deleted.
        #
        # Limitation, stated plainly: Git exposes no lock or coordination
        # primitive for worktree registration, so removal cannot be made
        # atomic with a concurrent `git worktree add`. A registration that
        # writes its marker after this check is not observable by any
        # pre-delete check; what this guard does guarantee is that a
        # registration already recorded in the tree is never destroyed.
        if _is_live_worktree_registration(quarantine):
            if not os.path.lexists(candidate):
                os.rename(quarantine, candidate)
            return False
        if force:
            shutil.rmtree(quarantine)
        else:
            os.rmdir(quarantine)
        return True
    except (OSError, ValueError):
        # If a safe deletion attempt fails after quarantine, restore the original
        # pathname only when no replacement has claimed it.
        if 'quarantine' in locals() and os.path.lexists(quarantine):
            if not os.path.lexists(candidate):
                try:
                    os.rename(quarantine, candidate)
                except OSError:
                    pass
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
    print(f"  Lock state unknown: {len(report.get('lock_unknown', []))}")
    if report["errors"]:
        print(f"  Errors:    {len(report['errors'])}")
    if report["orphaned"]:
        print(f"\n  Orphaned worktrees:")
        for wt in report["orphaned"]:
            if wt.is_locked:
                lock_flag = " [LOCKED]"
            elif wt.lock_state == LOCK_UNKNOWN:
                lock_flag = " [LOCK STATE UNKNOWN]"
            else:
                lock_flag = ""
            print(f"    {wt.path} ({wt.size_mb} MB){lock_flag}")
    if report["locked"]:
        print(f"\n  Locked (need reboot):")
        for wt in report["locked"]:
            print(f"    {wt.path}")
