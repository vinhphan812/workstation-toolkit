import os
from unittest.mock import patch
from workstation.core.worktree import WorktreeInfo, delete_worktree

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


def test_parses_detached_registered_worktree(tmp_path, monkeypatch):
    from workstation.core.worktree import get_git_worktrees
    import workstation.core.worktree as module

    root = str(tmp_path / "main")
    registered = str(tmp_path / "main" / ".worktrees" / "detached")
    porcelain = f"worktree {root}\nHEAD abcdef\n\nworktree {registered}\nHEAD 123456\ndetached\n\n"
    monkeypatch.setattr(module, "_run_git", lambda *_: (porcelain, 0))
    parsed = get_git_worktrees(root)
    assert os.path.normcase(os.path.normpath(registered)) in parsed
