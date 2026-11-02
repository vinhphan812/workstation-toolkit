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
    repo = tmp_path / "repo"
    d = repo / ".worktrees" / "orphaned"
    d.mkdir(parents=True)
    (d / "file.txt").write_text("temp")
    wt = WorktreeInfo(path=str(d), repo=str(repo), is_known=False, is_orphaned=True,
                      is_locked=False, size_mb=0, branch="unknown")
    with patch("workstation.core.worktree._run_git", return_value=("", 0)):
        assert delete_worktree(wt) is True
    assert not d.exists()


def test_refuse_path_escape_and_unclassified(tmp_path):
    from workstation.core.worktree import delete_worktree
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    wt = WorktreeInfo(str(outside), str(repo), False, True, False, 0, "unknown")
    with patch("workstation.core.worktree.get_git_worktrees", return_value={}):
        assert not delete_worktree(wt)
    assert outside.exists()
    inside = repo / ".worktrees" / "candidate"
    inside.mkdir(parents=True)
    wt.path = str(inside)
    wt.is_orphaned = False
    assert not delete_worktree(wt)
    assert inside.exists()


def test_symlink_escape_is_not_deleted(tmp_path):
    repo = tmp_path / "repo"
    root = repo / ".worktrees"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        import pytest
        pytest.skip("directory symlinks unavailable")
    wt = WorktreeInfo(str(link), str(repo), False, True, False, 0, "unknown")
    assert not delete_worktree(wt)
    assert outside.exists()
    assert link.is_symlink()


def test_registered_recheck_refuses_stale_orphan(tmp_path):
    repo = tmp_path / "repo"
    target = repo / ".worktrees" / "candidate"
    target.mkdir(parents=True)
    wt = WorktreeInfo(str(target), str(repo), False, True, False, 0, "unknown")
    with patch("workstation.core.worktree.get_git_worktrees", return_value={os.path.normcase(os.path.normpath(str(target))): "branch"}):
        assert not delete_worktree(wt)
    assert target.exists()


def test_registration_race_after_quarantine_refuses_and_restores_candidate(tmp_path, monkeypatch):
    import workstation.core.worktree as module

    repo = tmp_path / "repo"
    target = repo / ".worktrees" / "candidate"
    target.mkdir(parents=True)
    (target / "safe.txt").write_text("keep me")
    wt = WorktreeInfo(str(target), str(repo), False, True, False, 0, "unknown")

    real_rename = module.os.rename
    rename_calls = []

    def register_after_quarantine(source, destination, *_args):
        result = real_rename(source, destination)
        rename_calls.append((source, destination))
        if len(rename_calls) == 1:
            # Simulate `git worktree add` registering the original path after
            # deletion has atomically moved it aside but before the final query.
            module._run_git = lambda *_: (f"worktree {target}\nbranch refs/heads/live", 0)
        return result

    monkeypatch.setattr(module.os, "rename", register_after_quarantine)
    monkeypatch.setattr(module, "_run_git", lambda *_: ("", 0))
    assert delete_worktree(wt) is False
    assert len(rename_calls) == 2  # quarantine, then restore; never delete
    assert (target / "safe.txt").read_text() == "keep me"
    assert sorted(p.name for p in (repo / ".worktrees").iterdir()) == ["candidate"]


def test_candidate_replaced_after_quarantine_is_never_deleted(tmp_path, monkeypatch):
    import workstation.core.worktree as module

    repo = tmp_path / "repo"
    target = repo / ".worktrees" / "candidate"
    target.mkdir(parents=True)
    (target / "original.txt").write_text("original")
    wt = WorktreeInfo(str(target), str(repo), False, True, False, 0, "unknown")
    real_rename = module.os.rename
    calls = [0]

    def replace_path_after_move(source, destination, *_args):
        result = real_rename(source, destination)
        calls[0] += 1
        if calls[0] == 1:
            target.mkdir()
            (target / "outside.txt").write_text("must survive")
        return result

    monkeypatch.setattr(module.os, "rename", replace_path_after_move)
    monkeypatch.setattr(module, "_run_git", lambda *_: ("", 0))
    assert delete_worktree(wt) is False
    assert (target / "outside.txt").read_text() == "must survive"
    quarantine = next((repo / ".worktrees").glob(".delete-*"))
    assert (quarantine / "original.txt").read_text() == "original"


def test_force_false_refuses_nonempty_quarantined_directory(tmp_path):
    repo = tmp_path / "repo"
    target = repo / ".worktrees" / "candidate"
    target.mkdir(parents=True)
    (target / "safe.txt").write_text("keep me")
    wt = WorktreeInfo(str(target), str(repo), False, True, False, 0, "unknown")
    with patch("workstation.core.worktree._run_git", return_value=("", 0)):
        assert delete_worktree(wt, force=False) is False
    assert (target / "safe.txt").read_text() == "keep me"


def test_late_registration_at_rmtree_boundary_is_refused_and_tree_preserved(tmp_path, monkeypatch):
    """Regression for the registration-after-final-query/before-delete gap.

    A Git worktree registration can complete *after* the final
    `git worktree list` query has already produced its snapshot, i.e. inside
    the window between that query and the destructive `shutil.rmtree` call.
    The final listing therefore does not (and cannot) observe it.

    The quarantined tree is the authority on its own registration: it
    carries an in-tree `.git` marker pointing at the live administrative
    directory. Deleting such a tree recursively destroys a registered
    worktree, so the delete must be refused and the tree preserved.
    """
    import shutil
    import workstation.core.worktree as module

    repo = tmp_path / "repo"
    target = repo / ".worktrees" / "candidate"
    target.mkdir(parents=True)
    (target / "safe.txt").write_text("keep me")
    wt = WorktreeInfo(str(target), str(repo), False, True, False, 0, "unknown")

    # A live administrative directory, as Git would create for a worktree.
    admin = repo / ".git" / "worktrees" / "late"
    admin.mkdir(parents=True)

    rmtree_calls = []
    real_rmtree = shutil.rmtree

    def spy_rmtree(path, *args, **kwargs):
        rmtree_calls.append(path)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", spy_rmtree)

    def fake_run_git(repo_path, *args):
        # The final listing snapshot was taken *before* the registration
        # completed, so it cannot mention the worktree. The registration
        # lands immediately afterwards, in the window before the delete.
        quarantine = next((repo / ".worktrees").glob(".delete-*"))
        (quarantine / ".git").write_text("gitdir: %s\n" % admin)
        return ("", 0)

    monkeypatch.setattr(module, "_run_git", fake_run_git)

    assert delete_worktree(wt) is False
    assert rmtree_calls == [], "quarantined tree was recursively deleted"
    assert (target / "safe.txt").read_text() == "keep me"
    assert sorted(p.name for p in (repo / ".worktrees").iterdir()) == ["candidate"]


def test_stale_marker_orphan_is_still_deletable(tmp_path):
    """A pruned orphan keeps a stale in-tree `.git` marker.

    Its admin dir is gone, so it is not a registered worktree and must stay
    deletable -- otherwise the guard would make genuine orphan cleanup
    impossible. Only a marker pointing at a *live* admin dir blocks deletion.
    """
    repo = tmp_path / "repo"
    target = repo / ".worktrees" / "orphaned"
    target.mkdir(parents=True)
    (target / "file.txt").write_text("temp")
    stale = repo / ".git" / "worktrees" / "gone"
    (target / ".git").write_text("gitdir: %s\n" % stale)
    assert not stale.exists()

    wt = WorktreeInfo(str(target), str(repo), False, True, False, 0, "unknown")
    with patch("workstation.core.worktree._run_git", return_value=("", 0)):
        assert delete_worktree(wt) is True
    assert not target.exists()


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
    # The candidate must satisfy the deletion contract: an immediate child of
    # <repo>/.worktrees, and the Git registration re-query must succeed.
    repo = tmp_path / "repo"
    d = repo / ".worktrees" / "orphan"
    d.mkdir(parents=True)
    (d / "file.txt").write_text("temp")
    wt = WorktreeInfo(path=str(d), repo=str(repo), is_known=False, is_orphaned=True,
                      is_locked=False, size_mb=0, branch="unknown",
                      lock_state=LOCK_UNLOCKED)
    report = {"orphaned": [wt]}

    with patch("workstation.core.worktree._run_git", return_value=("", 0)):
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
    # The deletion path re-queries `git worktree list` before removing the
    # candidate; the temporary directory is not a repository, so that query is
    # stubbed to an empty registration list.
    monkeypatch.setattr(
        "workstation.core.worktree._run_git", lambda *a, **k: ("", 0),
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
