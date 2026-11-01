import os
from unittest.mock import patch
import pytest
from workstation.core.worktree import (
    LOCK_LOCKED,
    LOCK_UNKNOWN,
    LOCK_UNLOCKED,
    WorktreeInfo,
    delete_orphaned,
    delete_worktree,
)

def test_never_delete_known_worktree(tmp_path):
    d = tmp_path / "known"
    d.mkdir()
    wt = WorktreeInfo(path=str(d), repo="repo", is_known=True, is_orphaned=False,
                      is_locked=False, size_mb=0, branch="main")
    assert delete_worktree(wt) is False
    assert d.exists()

def test_delete_orphaned_empty_worktree(tmp_path):
    d = tmp_path / "orphaned"
    d.mkdir()
    (d / "file.txt").write_text("temp")
    wt = WorktreeInfo(path=str(d), repo="repo", is_known=False, is_orphaned=True,
                      is_locked=False, size_mb=0, branch="unknown")
    assert delete_worktree(wt) is True
    assert not d.exists()


def test_parses_detached_registered_worktree(tmp_path, monkeypatch):
    from workstation.core.worktree import get_git_worktrees
    import workstation.core.worktree as module

    root = str(tmp_path / "main")
    registered = str(tmp_path / "main" / ".worktrees" / "detached")
    porcelain = f"worktree {root}\nHEAD abcdef\n\nworktree {registered}\nHEAD 123456\ndetached\n\n"
    monkeypatch.setattr(module, "_run_git", lambda *_: (porcelain, 0))
    parsed = get_git_worktrees(root)
    assert os.path.normcase(os.path.normpath(registered)) in parsed



def test_audit_is_read_only_for_empty_and_nonempty_orphans(tmp_path, monkeypatch):
    import workstation.core.worktree as module

    repo = tmp_path / "repo"
    orphan_root = repo / ".worktrees"
    empty = orphan_root / "empty"
    nonempty = orphan_root / "nonempty"
    empty.mkdir(parents=True)
    nonempty.mkdir()
    payload = nonempty / "payload"
    payload.write_text("unchanged")
    monkeypatch.setattr(module, "get_git_worktrees", lambda _: {})

    results = module.audit_repo_worktrees(str(repo))
    by_name = {os.path.basename(item.path): item for item in results}

    assert empty.is_dir() and list(empty.iterdir()) == []
    assert payload.read_text() == "unchanged"
    for name in ("empty", "nonempty"):
        assert by_name[name].is_orphaned
        assert not by_name[name].is_locked


def test_nonempty_orphan_reports_not_locked_and_lock_state_is_explicit(tmp_path, monkeypatch):
    """A nonempty directory is not evidence of a lock: it must never report locked."""
    import workstation.core.worktree as module

    repo = tmp_path / "repo"
    nonempty = repo / ".worktrees" / "nonempty"
    nonempty.mkdir(parents=True)
    (nonempty / "payload").write_text("unchanged")
    monkeypatch.setattr(module, "get_git_worktrees", lambda _: {})

    item = module.audit_repo_worktrees(str(repo))[0]

    assert item.is_orphaned
    assert item.is_locked is False
    assert item.lock_state in (LOCK_UNKNOWN, LOCK_UNLOCKED)
    assert item.lock_state != LOCK_LOCKED


def test_mocked_true_os_lock_is_distinguishable(tmp_path, monkeypatch):
    """A confirmed OS lock must be reported as locked, not as unknown."""
    import workstation.core.worktree as module

    repo = tmp_path / "repo"
    orphan = repo / ".worktrees" / "held"
    orphan.mkdir(parents=True)
    monkeypatch.setattr(module, "get_git_worktrees", lambda _: {})
    monkeypatch.setattr(module, "_probe_lock_state", lambda path: LOCK_LOCKED)

    item = module.audit_repo_worktrees(str(repo))[0]

    assert item.lock_state == LOCK_LOCKED
    assert item.is_locked is True
    # The probe is read-only: the directory survives the audit.
    assert orphan.is_dir()


def test_lock_state_unknown_never_claims_locked(tmp_path, monkeypatch):
    import workstation.core.worktree as module

    repo = tmp_path / "repo"
    orphan = repo / ".worktrees" / "unproven"
    orphan.mkdir(parents=True)
    monkeypatch.setattr(module, "get_git_worktrees", lambda _: {})
    monkeypatch.setattr(module, "_probe_lock_state", lambda path: LOCK_UNKNOWN)

    item = module.audit_repo_worktrees(str(repo))[0]

    assert item.lock_state == LOCK_UNKNOWN
    assert item.is_locked is False


def test_audit_report_separates_unknown_lock_state(tmp_path, monkeypatch):
    import workstation.core.worktree as module

    repo = tmp_path / "repo"
    (repo / ".worktrees" / "a").mkdir(parents=True)
    (repo / ".worktrees" / "b").mkdir(parents=True)
    monkeypatch.setattr(module, "get_git_worktrees", lambda _: {})
    monkeypatch.setattr(module, "_probe_lock_state", lambda path: LOCK_UNKNOWN)

    report = module.audit_all_worktrees([str(repo)])

    assert report["errors"] == {}
    assert len(report["orphaned"]) == 2
    assert len(report["lock_unknown"]) == 2
    assert report["locked"] == []


@pytest.mark.skipif(os.name != "nt", reason="Windows share-mode lock semantics")
def test_real_os_lock_on_windows_is_detected_without_mutating(tmp_path, monkeypatch):
    """Real Windows evidence: a handle held without FILE_SHARE_DELETE is a lock."""
    import ctypes
    from ctypes import wintypes
    import workstation.core.worktree as module

    repo = tmp_path / "repo"
    orphan = repo / ".worktrees" / "held"
    orphan.mkdir(parents=True)
    payload = orphan / "payload"
    payload.write_text("unchanged")
    monkeypatch.setattr(module, "get_git_worktrees", lambda _: {})

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.restype = wintypes.HANDLE
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    generic_read = 0x80000000
    share_read_write = 0x00000001 | 0x00000002
    open_existing = 3
    backup_semantics = 0x02000000
    invalid_handle = wintypes.HANDLE(-1).value

    handle = create_file(
        str(orphan), generic_read, share_read_write, None,
        open_existing, backup_semantics, None,
    )
    assert handle not in (invalid_handle, None), "failed to hold a test handle"

    try:
        item = module.audit_repo_worktrees(str(repo))[0]
        assert item.lock_state == LOCK_LOCKED
        assert item.is_locked is True
        # Read-only guarantee: nothing was removed or altered.
        assert orphan.is_dir()
        assert payload.read_text() == "unchanged"
    finally:
        kernel32.CloseHandle(handle)

    # Once the handle is released the same path is provably not locked.
    released = module.audit_repo_worktrees(str(repo))[0]
    assert released.lock_state == LOCK_UNLOCKED
    assert released.is_locked is False
    assert orphan.is_dir()


def test_locked_orphan_is_not_deleted(tmp_path):
    """Deletion is refused for a confirmed lock on every platform."""
    d = tmp_path / "locked"
    d.mkdir()
    (d / "file.txt").write_text("keep")
    wt = WorktreeInfo(path=str(d), repo="repo", is_known=False, is_orphaned=True,
                      is_locked=True, size_mb=0, branch="unknown",
                      lock_state=LOCK_LOCKED)
    assert delete_worktree(wt) is False
    assert d.exists()


def test_delete_orphaned_requires_confirmation(tmp_path):
    d = tmp_path / "orphan"
    d.mkdir()
    (d / "file.txt").write_text("temp")
    wt = WorktreeInfo(path=str(d), repo="repo", is_known=False, is_orphaned=True,
                      is_locked=False, size_mb=0, branch="unknown",
                      lock_state=LOCK_UNLOCKED)
    report = {"orphaned": [wt]}

    with patch("builtins.input", return_value="n"):
        assert delete_orphaned(report, confirm=True) == []
    assert d.exists()

    with patch("builtins.input", return_value="y"):
        assert delete_orphaned(report, confirm=True) == [str(d)]
    assert not d.exists()


def test_cli_worktree_deletion_requires_execute_and_confirmation(tmp_path, monkeypatch):
    """Deletion stays gated behind explicit --execute plus an explicit confirmation."""
    from workstation.cli import build_parser, cmd_git_worktrees
    import workstation.cli as cli_module

    repo = tmp_path / "repo"
    orphan = repo / ".worktrees" / "orphan"
    orphan.mkdir(parents=True)
    (orphan / "file.txt").write_text("temp")

    monkeypatch.setattr(cli_module, "load_repos", lambda: [str(repo)])
    monkeypatch.setattr(
        "workstation.core.worktree.get_git_worktrees", lambda _: {},
    )

    # No --execute: audit only, nothing is deleted.
    cmd_git_worktrees(build_parser().parse_args(["git-worktrees"]))
    assert orphan.is_dir()

    # --execute with a declined confirmation: still nothing is deleted.
    with patch("builtins.input", return_value="n"):
        cmd_git_worktrees(build_parser().parse_args(["git-worktrees", "--execute"]))
    assert orphan.is_dir()

    # --execute with an explicit confirmation: the orphan is removed.
    with patch("builtins.input", return_value="y"):
        cmd_git_worktrees(build_parser().parse_args(["git-worktrees", "--execute"]))
    assert not orphan.exists()
