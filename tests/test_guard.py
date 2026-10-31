"""Tests for the public guard CLI contract and safe audit implementation."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure this worktree's source package wins over any editable install from a
# neighbouring checkout in the developer environment.
SOURCE_ROOT = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SOURCE_ROOT)

import pytest
import psutil
from workstation.cli import build_parser
from workstation.modules.guard_audit import ProcessEvidence, _heuristic, kill_pid, parent_pid_is_orphaned, scan_processes

assert Path(__import__("workstation.cli", fromlist=["__file__"]).__file__).resolve().is_relative_to(Path(SOURCE_ROOT).resolve())

def evidence(exe="/opt/app", cmdline="app"):
    return ProcessEvidence(10, 2, 1.0, exe, cmdline, "/", "running")

def test_cli_network_inspector_default_and_bypass(monkeypatch, capsys):
    from workstation.cli import cmd_guard
    from workstation.modules import guard_audit
    monkeypatch.setattr(guard_audit.psutil, "process_iter", lambda: [])
    inspector = MagicMock(return_value={"status": "available", "count": 0, "connections": []})
    monkeypatch.setattr(guard_audit, "inspect_network_connections", inspector)
    cmd_guard(build_parser().parse_args(["guard", "scan"]))
    assert json.loads(capsys.readouterr().out)["network_inspection"]["status"] == "available"
    inspector.assert_called_once_with()
    inspector.reset_mock()
    cmd_guard(build_parser().parse_args(["guard", "scan", "--no-network"]))
    assert json.loads(capsys.readouterr().out)["network_inspection"]["status"] == "skipped"
    inspector.assert_not_called()


def test_network_permission_denied_is_compact_and_safe(monkeypatch):
    monkeypatch.setattr("workstation.modules.guard_audit.psutil.net_connections", lambda **kwargs: (_ for _ in ()).throw(psutil.AccessDenied()))
    assert scan_processes()["network_inspection"] == {"status": "unavailable", "reason": "AccessDenied", "count": None, "connections": []}


def test_cli_default_network_semantics(monkeypatch):
    from workstation.cli import cmd_guard
    from workstation.modules import guard_audit
    monkeypatch.setattr(guard_audit.psutil, "process_iter", lambda: [])
    with patch.object(guard_audit, "inspect_network_connections", return_value={"status": "available", "count": 0, "connections": []}) as inspector:
        cmd_guard(build_parser().parse_args(["guard", "scan"]))
        inspector.assert_called_once_with()


@pytest.mark.parametrize("name", ["AnyDesk.exe", "TeamViewer.exe"])
def test_remote_support_names_are_neutral(name):
    assert _heuristic(evidence(name, name)) == ([], "none")

def test_scans_all_processes(monkeypatch):
    procs = [MagicMock(pid=1), MagicMock(pid=2)]
    monkeypatch.setattr("workstation.modules.guard_audit.psutil.process_iter", lambda: iter(procs))
    monkeypatch.setattr("workstation.modules.guard_audit.collect_process_evidence", lambda p: evidence())
    assert len(scan_processes()["processes"]) == 2

def test_cli_kill_dry_run_and_execute_are_single_pid(monkeypatch, capsys):
    from workstation.cli import cmd_guard
    from workstation.modules import guard_audit
    with patch.object(guard_audit.psutil, "Process") as process:
        cmd_guard(build_parser().parse_args(["guard", "kill", "4321"]))
        assert json.loads(capsys.readouterr().out)["executed"] is False
        process.assert_not_called()
        cmd_guard(build_parser().parse_args(["guard", "kill", "4321", "--execute"]))
        assert json.loads(capsys.readouterr().out)["executed"] is True
        process.assert_called_once_with(4321)
        process.return_value.kill.assert_called_once_with()


def test_advisory_heuristic_never_auto_kills():
    row = scan_processes(no_network=True)
    assert "auto_kill" not in json.dumps(row).lower()


def test_pid_kill_dry_run_and_exactly_once():
    args = build_parser().parse_args(["guard", "kill", "4321"])
    assert not args.execute and kill_pid(args.pid)["action"] == "dry_run"
    args = build_parser().parse_args(["guard", "kill", "4321", "--execute"])
    with patch("workstation.modules.guard_audit.psutil.Process") as proc:
        assert kill_pid(args.pid, execute=args.execute)["action"] == "kill_requested"
    proc.assert_called_once_with(4321)
    proc.return_value.kill.assert_called_once_with()

def test_parent_pid_helper_treats_unknown_safely():
    assert not parent_pid_is_orphaned(0, lambda _: False)
    assert not parent_pid_is_orphaned("<unavailable>", lambda _: False)
    assert parent_pid_is_orphaned(55, lambda _: False)
    assert not parent_pid_is_orphaned(55, lambda _: True)
    assert not parent_pid_is_orphaned(55, lambda _: (_ for _ in ()).throw(psutil.AccessDenied()))
