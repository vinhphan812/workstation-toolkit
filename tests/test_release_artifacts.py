"""Regression tests for the release artefacts.

A release is only verifiable if the artefacts carry the material needed to
verify it: the changelog, the documentation sources and the benchmark
harness. These tests build the distribution artefacts and inspect them.

The build uses `uv build`, because the project environment is uv-managed and
has no `setuptools` installed; `python -m build --no-isolation` fails there
with "Backend 'setuptools.build_meta' is not available".
"""
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _version() -> str:
    import re
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert match
    return match.group(1)


def _build(outdir: Path, *flags: str):
    """Build the distribution artefacts, skipping if uv is unavailable."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not available on this machine")
    result = subprocess.run(
        [uv, "build", "--out-dir", str(outdir), *flags],
        cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, result.stdout + result.stderr
    return outdir


@pytest.fixture(scope="module")
def artefacts(tmp_path_factory):
    outdir = tmp_path_factory.mktemp("dist")
    _build(outdir)
    wheels = list(outdir.glob("*.whl"))
    sdists = list(outdir.glob("*.tar.gz"))
    assert wheels, "no wheel was built"
    assert sdists, "no source distribution was built"
    return wheels[0], sdists[0]


def test_the_wheel_carries_the_expected_version(artefacts):
    wheel, _ = artefacts
    assert f"workstation_toolkit-{_version()}-py3-none-any.whl" == wheel.name


def test_the_wheel_carries_every_source_module(artefacts):
    """A module missing from the wheel is a packaging defect."""
    wheel, _ = artefacts
    names = zipfile.ZipFile(wheel).namelist()
    modules = [name for name in names
               if name.startswith("workstation/") and name.endswith(".py")]
    assert len(modules) == 34, f"unexpected module count: {len(modules)}"
    for required in ("workstation/cli.py", "workstation/core/fsscan.py",
                     "workstation/core/worktree.py", "workstation/modules/system.py"):
        assert required in modules, f"{required} is missing from the wheel"


def test_the_source_distribution_carries_the_release_material(artefacts):
    """The changelog, the documentation and the harness must ship."""
    _, sdist = artefacts
    names = tarfile.open(sdist).getnames()
    suffixes = {name.split("/", 1)[1] for name in names if "/" in name}
    for required in ("CHANGELOG.md", "CONTRIBUTING.md", "README.md", "mkdocs.yml",
                     "scripts/benchmark.py", "docs/architecture.md",
                     "docs/index.md", "docs/command-reference.md",
                     "docs/templates/changelog_template.md"):
        assert required in suffixes, f"{required} is missing from the sdist"


def test_the_source_distribution_carries_the_tests(artefacts):
    """The tests must ship so a consumer can verify the release."""
    _, sdist = artefacts
    names = tarfile.open(sdist).getnames()
    tests = [name for name in names if "/tests/" in name and name.endswith(".py")]
    assert len(tests) >= 28, f"unexpected test count: {len(tests)}"
