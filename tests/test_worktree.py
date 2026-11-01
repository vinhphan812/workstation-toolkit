import os
from unittest.mock import patch
from workstation.core.worktree import WorktreeInfo, delete_worktree


def test_git_worktrees_command_is_read_only_by_default(tmp_path, monkeypatch, capsys):
    import workstation.cli as cli
    import workstation.core.worktree as worktree

    monkeypatch.setattr(cli, "load_repos", lambda: [str(tmp_path)])
    monkeypatch.setattr(worktree, "audit_all_worktrees", lambda _repos: {
        "orphaned": [], "known": [], "locked": [], "errors": {},
        "total_orphaned_size_mb": 0,
    })
    deleted = []
    monkeypatch.setattr(worktree, "delete_orphaned", lambda *a, **k: deleted.append(True))
    args = cli.build_parser().parse_args(["git-worktrees"])
    args.func(args)
    assert deleted == []
    assert "Worktree Audit" in capsys.readouterr().out

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
