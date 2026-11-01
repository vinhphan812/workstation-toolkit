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
