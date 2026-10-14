from workstation.core.process import ProcessInfo, is_process_orphaned

def make_proc(**kwargs):
    data = dict(pid=999999, name="node", ram_mb=2048, ram_gb=2.0,
                cmdline="node worker.js", cwd="", parent_pid=1, status="running")
    data.update(kwargs)
    return ProcessInfo(**data)

def test_orphaned_when_cmdline_references_worktree():
    proc = make_proc(cmdline=r"node D:\repo\.worktrees\t_dead\worker.js")
    orphaned, reason = is_process_orphaned(proc)
    assert orphaned
    assert "orphaned" in reason
