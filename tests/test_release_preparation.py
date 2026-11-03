"""Regression tests for the release-preparation state of the repository.

These tests keep the published version, the changelog and the source in
agreement. A release that advertises one version while the package carries
another is defective, and the defect is invisible until somebody installs
the artefact.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "workstation" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"


def _pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert match, "pyproject.toml must declare a project version"
    return match.group(1)


def _package_version() -> str:
    text = INIT.read_text(encoding="utf-8")
    match = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"', text)
    assert match, "the package must declare __version__"
    return match.group(1)


def _changelog() -> str:
    return CHANGELOG.read_text(encoding="utf-8")


def test_the_declared_and_package_versions_agree():
    """`pip install` must not produce a different version than the source."""
    assert _pyproject_version() == _package_version(), (
        "pyproject.toml and __version__ must declare the same version")


def test_the_version_is_not_the_initial_release():
    """A guard against the version being left at the initial release while
    the changelog claims later releases exist."""
    assert _pyproject_version() != "0.1.0", (
        "the package version must be moved off the initial release")


def test_the_changelog_records_the_current_version():
    """The changelog must have a dated section for the version being shipped."""
    version = _pyproject_version()
    changelog = _changelog()
    assert re.search(rf"(?m)^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$",
                      changelog), (
        f"the changelog must have a dated section for {version}")


def test_every_changelog_version_has_a_link_definition():
    """Each version heading must be resolvable as a comparison or release link."""
    changelog = _changelog()
    versions = re.findall(r"(?m)^## \[(.+?)\]", changelog)
    assert versions, "the changelog must have version headings"
    for version in versions:
        assert re.search(rf"(?m)^\[{re.escape(version)}\]:\s+https://", changelog), (
            f"version {version} has no link definition")


def test_the_unreleased_link_compares_against_the_latest_release():
    """The `[Unreleased]` link must point at the newest release, not at the
    initial one."""
    version = _pyproject_version()
    changelog = _changelog()
    expected = (
        f"[Unreleased]: https://github.com/vinhphan812/workstation-toolkit"
        f"/compare/v{version}...HEAD")
    assert "Unreleased work is collected here" not in changelog
    assert "[Unreleased]: https://github.com/vinhphan812/workstation-toolkit/compare/v0.2.0...HEAD" in changelog
    assert "[0.2.0]: https://github.com/vinhphan812/workstation-toolkit/compare/v0.1.0...v0.2.0" in changelog


def test_the_release_section_records_a_link_to_the_previous_release():
    """The release section must compare against the previous release."""
    version = _pyproject_version()
    changelog = _changelog()
    assert f"[{version}]: https://github.com/vinhphan812/workstation-toolkit/compare/" \
        in changelog, (
        f"the {version} link must compare against the previous release")


def test_the_release_section_keeps_the_selected_change_scope():
    """A published release must state that its list is a curated selection,
    not a complete commit ledger."""
    changelog = _changelog().lower()
    assert "selected notable changes" in changelog, (
        "the release section must identify its entries as selected notable changes")
    assert not re.search(r"\b\d+ commits? across \d+ days?\b", changelog), (
        "do not state a commit/day total unless full commit coverage is verified")


def test_the_release_section_contains_no_stale_attribution():
    """A published release must not attribute a change to an unresolved
    placeholder."""
    changelog = _changelog()
    unreleased = changelog.split("## [", 2)[1] if changelog.count("## [") > 2 else ""
    assert "and this change" not in changelog.lower(), (
        "use the actual commit hash rather than 'and this change'")
    assert not re.search(r"`(?:HEAD|WORKTREE|PR)`", changelog), (
        "use an existing commit hash rather than a symbolic placeholder")
