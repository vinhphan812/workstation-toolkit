"""Regression tests for the filesystem and process-scan performance work.

The audit commands were rewritten to walk directories with ``os.scandir``
instead of ``Path.rglob`` and to run independent Git and Docker probes
concurrently. These tests pin the behaviour that must not change:

* the scanner reports the same total size as the old recursive walk;
* symlinked directories are not followed;
* the Android SDK audit measures the SDK once and still reports every
  package directory with the correct size;
* the repository summary reports the same dirty state, branches and remotes
  as the three separate Git calls it replaced;
* the Docker state parses the real ``docker system df`` table.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from workstation.core import fsscan


def _tree_size_reference(root: Path) -> int:
    """Total size computed the slow way, used as the expected value."""
    total = 0
    for item in root.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def test_dir_size_matches_the_recursive_walk(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_text("x" * 100)
    (tmp_path / "b" / "deep").mkdir(parents=True)
    (tmp_path / "b" / "deep" / "two.txt").write_text("y" * 250)
    (tmp_path / "top.txt").write_text("z" * 50)

    assert fsscan.dir_size_bytes(tmp_path) == _tree_size_reference(tmp_path)


def test_dir_size_of_empty_directory_is_zero(tmp_path):
    assert fsscan.dir_size_bytes(tmp_path) == 0


def test_dir_size_reports_the_same_total_in_megabytes(tmp_path):
    (tmp_path / "file.bin").write_bytes(b"0" * (3 * 1024 * 1024))
    assert fsscan.dir_size_mb(tmp_path) == pytest.approx(3.0)


def _make_directory_link(link: Path, target: Path) -> bool:
    """Create a directory link that points at *target*.

    A symbolic link needs a privilege that an unelevated Windows session
    does not have, so a directory junction is used when one can be created.
    Returns False when neither form is available.
    """
    import subprocess
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True,
        )
        return result.returncode == 0
    return False


def test_scanner_does_not_follow_symlinked_directories(tmp_path):
    """A link to another tree must not be descended into.

    Without this the scanner would count the linked files a second time.
    """
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_text("x" * 10)
    link = tmp_path / "link"
    if not _make_directory_link(link, target):
        pytest.skip("cannot create a directory link on this platform")

    # The link is reported but not descended into, so the target file is
    # counted exactly once.
    assert fsscan.dir_size_bytes(tmp_path) == 10


def test_scanner_does_not_follow_a_link_to_its_own_ancestor(tmp_path):
    """A link pointing back at an ancestor must not loop forever."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "file.txt").write_text("x" * 10)
    link = root / "loop"
    if not _make_directory_link(link, root):
        pytest.skip("cannot create a directory link on this platform")

    assert fsscan.dir_size_bytes(root) == 10


def test_scanner_survives_an_unreadable_directory(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "hidden.txt").write_text("x" * 10)
    (tmp_path / "visible.txt").write_text("y" * 20)
    try:
        os.chmod(blocked, 0o000)
    except OSError:
        pytest.skip("cannot change permissions on this platform")
    try:
        # The point is that the call returns rather than raising.
        size = fsscan.dir_size_bytes(tmp_path)
    finally:
        os.chmod(blocked, 0o700)
    assert size >= 20


def test_dir_size_by_child_reports_each_immediate_child(tmp_path):
    (tmp_path / "one").mkdir()
    (tmp_path / "one" / "a.txt").write_text("x" * 100)
    (tmp_path / "two").mkdir()
    (tmp_path / "two" / "b.txt").write_text("y" * 200)

    sizes = fsscan.dir_size_by_child(tmp_path, depth=1)
    assert sizes["one"] == 100
    assert sizes["two"] == 200


def test_dir_size_by_child_supports_a_second_level(tmp_path):
    (tmp_path / "family" / "child").mkdir(parents=True)
    (tmp_path / "family" / "child" / "file.txt").write_text("x" * 50)

    sizes = fsscan.dir_size_by_child(tmp_path, depth=2)
    assert sizes[os.path.join("family", "child")] == 50


def test_dir_size_by_child_levels_agrees_with_single_depth_calls(tmp_path):
    (tmp_path / "family" / "child").mkdir(parents=True)
    (tmp_path / "family" / "child" / "file.txt").write_text("x" * 50)
    (tmp_path / "loose.txt").write_text("y" * 25)

    levels = fsscan.dir_size_by_child_levels(tmp_path, (1, 2))
    assert levels[1] == fsscan.dir_size_by_child(tmp_path, depth=1)
    assert levels[2] == fsscan.dir_size_by_child(tmp_path, depth=2)


def test_android_sdk_audit_reports_packages_and_total(tmp_path, monkeypatch):
    from workstation.modules import development_audit

    sdk = tmp_path / "Sdk"
    (sdk / "build-tools" / "34.0.0").mkdir(parents=True)
    (sdk / "build-tools" / "34.0.0" / "aapt.exe").write_bytes(b"0" * 4096)
    (sdk / "platforms" / "android-34").mkdir(parents=True)
    (sdk / "platforms" / "android-34" / "android.jar").write_bytes(b"0" * 8192)

    monkeypatch.setenv("ANDROID_SDK_ROOT", str(sdk))
    monkeypatch.setenv("ANDROID_HOME", str(sdk))

    report = development_audit.android_sdk_audit()

    assert report["status"] == "available"
    # 4096 + 8192 = 12288 bytes in total. The reported value is rounded to
    # two decimals, so the comparison uses the rounded figure.
    assert report["total_mb"] == round(12288 / (1024 ** 2), 2)
    tools = {item["name"]: item for item in report["build_tools"]}
    assert tools["34.0.0"]["size_mb"] == round(4096 / (1024 ** 2), 2)
    platforms = {item["name"]: item for item in report["platforms"]}
    assert platforms["android-34"]["size_mb"] == round(8192 / (1024 ** 2), 2)
    # The per-package sizes must add up to the reported total.
    summed = sum(item["size_mb"] for group in
                 (report["build_tools"], report["platforms"]) for item in group)
    assert summed == pytest.approx(report["total_mb"], abs=0.01)


def test_repo_summary_matches_the_separate_git_helpers(tmp_path):
    """The combined Git call must agree with the three helpers it replaced."""
    from workstation.core.git import (
        get_remotes, get_repo_branches, get_repo_summary, is_repo_dirty,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)

    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (repo / "file.txt").write_text("hello")
    git("add", ".")
    # The commit needs an identity even when the global config has none, and
    # the environment may point at a different signing setup.
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false",
                    "commit", "--no-gpg-sign", "-m", "initial"],
                   capture_output=True, text=True, check=True)

    summary = get_repo_summary(str(repo))
    assert summary["dirty"] == is_repo_dirty(str(repo)) is False
    assert set(summary["branches"]) == set(get_repo_branches(str(repo)))
    assert summary["branches"]
    assert summary["remotes"] == get_remotes(str(repo))

    # A dirty working tree must be reported as dirty.
    (repo / "file.txt").write_text("changed")
    assert get_repo_summary(str(repo))["dirty"] is True


def test_scanner_descends_into_nested_directories(tmp_path):
    """A file buried several levels down must still be counted."""
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "buried.txt").write_text("x" * 77)

    assert fsscan.dir_size_bytes(tmp_path) == 77
    sizes = fsscan.dir_size_by_child(tmp_path, depth=1)
    assert sizes["a"] == 77


def test_scanner_counts_a_file_at_the_top_of_the_tree(tmp_path):
    (tmp_path / "top.txt").write_text("x" * 31)
    assert fsscan.dir_size_bytes(tmp_path) == 31


def test_docker_state_parses_the_system_df_table(monkeypatch):
    """``docker system df`` is parsed from the table form, not --format."""
    from workstation.core import docker

    table = (
        "TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE\n"
        "Images          1         1         24.05GB   0B (0%)\n"
        "Containers      5         5         20.48GB   0B (0%)\n"
        "Local Volumes   0         0         0B        0B\n"
        "Build Cache     0         0         0B        0B\n"
    )

    def fake_run(*args):
        if args[0] == "info":
            return "Server Version: 27.0.0", 0
        if args[0] == "system" and args[1] == "df":
            return table, 0
        if args[0] == "ps":
            return "alpha\nbeta\n", 0
        if args[0] == "volume":
            return "", 0
        return "", 0

    monkeypatch.setattr(docker, "_run", fake_run)
    state = docker.get_state()

    assert state.running is True
    assert state.containers == 2
    # The SIZE column is the fourth field: TYPE, TOTAL, ACTIVE, SIZE.
    assert state.images_size == "24.05GB"
    assert state.build_cache == "0B"


def test_docker_state_parses_a_non_zero_build_cache(monkeypatch):
    """The build cache row has a two-word label and its own size."""
    from workstation.core import docker

    table = (
        "TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE\n"
        "Images          3         2         12.5GB    4GB (30%)\n"
        "Local Volumes   2         1         1.5GB     0B\n"
        "Build Cache     12        0         2.1GB     1GB (50%)\n"
    )

    def fake_run(*args):
        if args[0] == "info":
            return "Server Version: 27.0.0", 0
        if args[0] == "system" and args[1] == "df":
            return table, 0
        if args[0] == "ps":
            return "", 0
        return "", 0

    monkeypatch.setattr(docker, "_run", fake_run)
    state = docker.get_state()

    assert state.images_size == "12.5GB"
    assert state.build_cache == "2.1GB"


def test_docker_build_cache_label_is_not_confused_with_local_volumes(monkeypatch):
    """'Local Volumes' must not be mistaken for the build cache row."""
    from workstation.core import docker

    table = (
        "TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE\n"
        "Images          1         1         24.05GB   0B (0%)\n"
        "Local Volumes   2         1         9.9GB     0B\n"
    )

    def fake_run(*args):
        if args[0] == "info":
            return "Server Version: 27.0.0", 0
        if args[0] == "system" and args[1] == "df":
            return table, 0
        if args[0] == "ps":
            return "", 0
        return "", 0

    monkeypatch.setattr(docker, "_run", fake_run)
    state = docker.get_state()

    assert state.images_size == "24.05GB"
    # There is no build cache row, so the value must stay unset.
    assert state.build_cache == "N/A"


def test_repo_summary_reports_the_local_branches(tmp_path):
    """The combined Git call must list the local branches."""
    from workstation.core.git import get_repo_summary

    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)

    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (repo / "file.txt").write_text("hello")
    git("add", ".")
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false",
                    "commit", "--no-gpg-sign", "-m", "initial"],
                   capture_output=True, text=True, check=True)
    git("branch", "feature/one")

    summary = get_repo_summary(str(repo))
    assert "main" in summary["branches"]
    assert "feature/one" in summary["branches"]


def test_excluded_directory_names_are_not_walked(tmp_path):
    """An excluded directory name is skipped at any depth."""
    (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
    (tmp_path / "node_modules" / "left-pad" / "index.js").write_text("x" * 500)
    (tmp_path / "src" / "node_modules").mkdir(parents=True)
    (tmp_path / "src" / "node_modules" / "dep.js").write_text("y" * 300)
    (tmp_path / "src" / "app.py").write_text("z" * 100)

    excluded = fsscan.dir_size_bytes(tmp_path, frozenset({"node_modules"}))
    assert excluded == 100


def test_repo_excludes_reduce_a_path_to_its_first_component(tmp_path, monkeypatch):
    """``node_modules/.cache`` must exclude ``node_modules``."""
    from workstation import config

    repos_file = tmp_path / "repos.json"
    repos_file.write_text(
        '{"repos": [], "exclude_patterns": ["node_modules/.cache", ".venv", "vendor"]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))

    assert config.load_repo_excludes() == ["node_modules", ".venv", "vendor"]


def test_orphaned_worktree_size_is_measured_in_full(tmp_path, monkeypatch):
    """An orphaned worktree reports the space deleting it would reclaim.

    The exclusions only apply to worktrees Git still knows about, so an
    under-reported reclaim figure can never mislead a deletion.
    """
    from workstation.core import worktree

    repo = tmp_path / "repo"
    wt = repo / ".worktrees" / "orphan"
    (wt / "node_modules" / "dep").mkdir(parents=True)
    (wt / "node_modules" / "dep" / "big.js").write_bytes(b"0" * (4 * 1024 * 1024))
    (wt / "src.py").write_bytes(b"0" * (1024 * 1024))

    monkeypatch.setattr(worktree, "get_git_worktrees", lambda _repo: {})

    report = worktree.audit_all_worktrees([str(repo)], frozenset({"node_modules"}))

    assert len(report["orphaned"]) == 1
    # 4 MB + 1 MB, with node_modules included.
    assert report["orphaned"][0].size_mb == pytest.approx(5.0, abs=0.01)
    assert report["total_orphaned_size_mb"] == pytest.approx(5.0, abs=0.01)


def test_known_worktree_size_skips_the_excluded_directories(tmp_path, monkeypatch):
    """A known worktree is measured with the exclusions applied.

    Its size is informational only, so the excluded dependency trees do not
    have to be walked.
    """
    from workstation.core import worktree

    repo = tmp_path / "repo"
    wt = repo / ".worktrees" / "known"
    (wt / "node_modules" / "dep").mkdir(parents=True)
    (wt / "node_modules" / "dep" / "big.js").write_bytes(b"0" * (4 * 1024 * 1024))
    (wt / "src.py").write_bytes(b"0" * (1024 * 1024))

    import os as _os
    normalised = _os.path.normcase(_os.path.normpath(str(wt)))
    monkeypatch.setattr(worktree, "get_git_worktrees", lambda _repo: {normalised: "main"})

    report = worktree.audit_all_worktrees([str(repo)], frozenset({"node_modules"}))

    assert len(report["known"]) == 1
    # Only the 1 MB source file; the 4 MB dependency tree is excluded.
    assert report["known"][0].size_mb == pytest.approx(1.0, abs=0.01)
    assert report["known"][0].size_mb < 5.0
    # Nothing is orphaned, so no reclaim figure is reported.
    assert report["total_orphaned_size_mb"] == 0
