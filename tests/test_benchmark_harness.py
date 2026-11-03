"""Regression tests for the committed benchmark harness.

The performance claims in this repository are only credible if the harness
that produced them is committed and works. These tests keep the harness
importable, side-effect free and honest about what it measured.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "benchmark.py"


def _run(*args, cwd=None):
    """Run the harness and return the completed process."""
    return subprocess.run(
        [sys.executable, str(HARNESS), *args],
        cwd=cwd or ROOT, capture_output=True, text=True, timeout=600,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})


def test_the_harness_is_committed():
    """The harness must live in the repository, not only in a scratch space."""
    assert HARNESS.exists(), "the benchmark harness must be committed"
    assert "scripts" in {part for part in HARNESS.parts}


def _make_repo(path):
    """Create a small committed git repository."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "file.txt").write_text("content", encoding="utf-8")
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "file.txt"],
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
         "commit", "-q", "-m", "initial"],
    ):
        subprocess.run(command, cwd=path, check=True, capture_output=True)
    return path


def test_the_harness_runs_and_reports_its_environment(tmp_path):
    """A run must produce a document that records where it was measured."""
    repo = _make_repo(tmp_path / "repo")
    result = _run("--repeats", "1", "--root", str(tmp_path), "--repo", str(repo),
                  "--require-clean", "--output", str(tmp_path / "result.json"))
    assert result.returncode == 0, result.stderr
    document = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    environment = document["environment"]
    for key in ("timestamp_utc", "platform", "python_version", "git_commit"):
        assert key in environment, f"the measurement must record {key}"
    assert environment["git_commit"], "the commit must be recorded"
    assert environment["git_dirty"] is False


def test_the_harness_records_the_measured_totals(tmp_path):
    """The measurement must carry the size it measured, not only a duration."""
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"x" * 4096)
    result = _run("--repeats", "1", "--root", str(tmp_path),
                  "--output", str(tmp_path / "result.json"))
    assert result.returncode == 0, result.stderr
    document = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    scan = document["scan"]
    assert scan["totals_match"] is True
    assert set(scan["strategies"]) == {"pathlib_rglob", "shared_scandir"}
    legacy = scan["strategies"]["pathlib_rglob"]
    current = scan["strategies"]["shared_scandir"]
    assert legacy["total_bytes"] == current["total_bytes"]
    assert legacy["total_bytes"] >= 4096, "the measured size must be reported"
    for strategy in scan["strategies"].values():
        for key in ("seconds_min", "seconds_median", "seconds_max"):
            assert key in strategy, f"the measurement must report {key}"


def test_the_harness_states_how_the_claim_must_be_read(tmp_path):
    """The document must identify this as a scoped scanner microbenchmark."""
    result = _run("--repeats", "1", "--root", str(tmp_path),
                  "--output", str(tmp_path / "result.json"))
    assert result.returncode == 0, result.stderr
    document = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    notes = " ".join(document["notes"]).lower()
    assert "no other work in flight" in notes
    assert "same-tree microbenchmark" in notes
    assert "do not" in notes and "end-to-end speedup" in notes


def test_the_harness_does_not_mutate_the_measured_tree(tmp_path):
    """The harness must not write into the tree it measures."""
    measured = tmp_path / "measured"
    measured.mkdir()
    (measured / "file.txt").write_text("content", encoding="utf-8")
    before = sorted(path.name for path in measured.iterdir())
    result = _run("--repeats", "1", "--root", str(measured),
                  "--output", str(tmp_path / "result.json"))
    assert result.returncode == 0, result.stderr
    after = sorted(path.name for path in measured.iterdir())
    assert before == after, "the harness must not add or remove files"


def test_require_clean_refuses_to_benchmark_a_dirty_repository(tmp_path):
    """Release measurements must not silently benchmark an uncommitted tree."""
    repo = _make_repo(tmp_path / "repo")
    (repo / "file.txt").write_text("changed", encoding="utf-8")
    result = _run("--repeats", "1", "--root", str(tmp_path), "--repo", str(repo),
                  "--require-clean")
    assert result.returncode == 2
    assert "repository is dirty" in result.stderr


def test_the_harness_rejects_an_invalid_root(tmp_path):
    """A missing tree must fail rather than report a measurement of nothing."""
    result = _run("--repeats", "1", "--root", str(tmp_path / "missing"))
    assert result.returncode != 0, "a missing root must be an error"
