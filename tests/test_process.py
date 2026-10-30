from unittest.mock import patch

import psutil

from workstation.core.process import ProcessInfo, is_process_orphaned

def make_proc(**kwargs):
    data = dict(pid=999999, name="node", ram_mb=2048, ram_gb=2.0,
                cmdline="node worker.js", cwd="", parent_pid=1, status="running")
    data.update(kwargs)
    return ProcessInfo(**data)

def test_orphaned_when_cmdline_references_worktree():
    proc = make_proc(cmdline="node D:/repo/.worktrees/t_dead/worker.js")
    orphaned, reason = is_process_orphaned(proc)
    assert orphaned
    assert "orphaned" in reason


def test_missing_parent_with_existing_cwd_is_not_orphaned(tmp_path):
    with patch("workstation.core.process.psutil.Process", side_effect=psutil.NoSuchProcess(9998)):
        orphaned, reason = is_process_orphaned(make_proc(parent_pid=9998, cwd=str(tmp_path)))
    assert not orphaned
    assert reason == ""


def test_missing_cwd_is_orphaned_even_if_parent_is_alive(tmp_path):
    missing = tmp_path / "deleted-worktree"
    with patch("workstation.core.process.psutil.Process") as process:
        process.return_value.name.return_value = "python.exe"
        orphaned, reason = is_process_orphaned(make_proc(parent_pid=1234, cwd=str(missing)))
    assert orphaned
    assert reason == f"cwd does not exist: {missing}"


def test_empty_cwd_is_not_claimed_missing():
    with patch("workstation.core.process.psutil.Process", side_effect=psutil.NoSuchProcess(9998)):
        orphaned, reason = is_process_orphaned(make_proc(parent_pid=9998, cwd=""))
    assert not orphaned
    assert reason == ""
