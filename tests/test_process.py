from unittest.mock import patch

import psutil

from workstation.core.process import ProcessInfo, is_process_orphaned, list_processes


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


class _FakeIterProc:
    """Stands in for the object returned by psutil.process_iter."""

    def __init__(self, pid, name, rss_mb):
        self.info = {"pid": pid, "name": name,
                     "memory_info": type("Mem", (), {"rss": int(rss_mb * 1024 ** 2)})()}


class _FakeProc:
    """Stands in for a reopened psutil.Process."""

    def __init__(self, pid, name, cmdline, cwd, ppid=1, status="running",
                 deny=()):
        self._pid, self._name = pid, name
        self._cmdline, self._cwd = cmdline, cwd
        self._ppid, self._status = ppid, status
        self._deny = set(deny)

    def cmdline(self):
        if "cmdline" in self._deny:
            raise psutil.AccessDenied(pid=self._pid)
        return self._cmdline

    def cwd(self):
        if "cwd" in self._deny:
            raise psutil.AccessDenied(pid=self._pid)
        return self._cwd

    def ppid(self):
        if "ppid" in self._deny:
            raise psutil.AccessDenied(pid=self._pid)
        return self._ppid

    def status(self):
        if "status" in self._deny:
            raise psutil.AccessDenied(pid=self._pid)
        return self._status


def _scan(monkeypatch, entries, threshold_mb=100):
    """Run list_processes against fake processes and record reopened pids."""
    reopened = []

    def fake_iter(_attrs):
        return [_FakeIterProc(pid, name, rss) for pid, name, rss in entries]

    def fake_process(pid):
        reopened.append(pid)
        for candidate in entries:
            if candidate[0] == pid:
                return _FakeProc(pid, candidate[1], [candidate[1], "worker"], "/tmp")
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "process_iter", fake_iter)
    monkeypatch.setattr(psutil, "Process", fake_process)
    return list_processes(threshold_mb), reopened


def test_scan_only_reopens_processes_above_the_threshold(monkeypatch):
    # The first phase must not open a process object for a process that is
    # below the threshold, because opening one is the expensive part.
    results, reopened = _scan(monkeypatch, [
        (100, "light", 10),
        (200, "heavy", 900),
    ], threshold_mb=100)
    assert [p.pid for p in results] == [200]
    assert reopened == [200]


def test_scan_keeps_a_process_whose_metadata_cannot_be_read(monkeypatch):
    # The single-pass scan tolerated an unreadable command line and working
    # directory by reporting blank values, so the two-phase scan must not
    # drop such a process entirely.
    def fake_iter(_attrs):
        return [_FakeIterProc(300, "protected", 900)]

    def fake_process(pid):
        return _FakeProc(pid, "protected", [], "/tmp", deny=("cmdline", "cwd"))

    monkeypatch.setattr(psutil, "process_iter", fake_iter)
    monkeypatch.setattr(psutil, "Process", fake_process)
    results = list_processes(100)
    assert [p.pid for p in results] == [300]
    assert results[0].cmdline == ""
    assert results[0].cwd == ""


def test_scan_excludes_system_processes(monkeypatch):
    # Windows system processes must never be reported as heavy processes.
    results, _ = _scan(monkeypatch, [
        (400, "Memory Compression", 800),
        (401, "Registry", 700),
        (402, "node", 900),
    ])
    assert [p.pid for p in results] == [402]


def test_scan_reports_results_sorted_by_memory(monkeypatch):
    results, _ = _scan(monkeypatch, [
        (500, "small", 900),
        (501, "big", 2000),
    ])
    assert [p.pid for p in results] == [501, 500]
