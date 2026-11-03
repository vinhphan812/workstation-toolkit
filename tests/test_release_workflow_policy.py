"""Policy tests for GitHub Actions workflows.

Every third-party action must use an immutable full commit SHA and include
its upstream version in a comment. The release workflow additionally keeps
write permission scoped to the publish job, and the Pages workflow grants
only the permissions needed to deploy.
"""
from pathlib import Path
import re

try:
    import yaml
except ImportError:  # pragma: no cover - reported as a test setup error
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE_WORKFLOW = WORKFLOWS / "release.yml"


def _workflow_paths():
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def _parse(path):
    if yaml is None:
        raise RuntimeError("workflow policy tests require PyYAML")
    text = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text.replace("\non:\n", "\n' on':\n", 1))
    assert isinstance(parsed, dict)
    return text, parsed


def _release_workflow():
    return _parse(RELEASE_WORKFLOW)


def test_every_workflow_is_covered_by_this_policy():
    paths = _workflow_paths()
    assert {path.name for path in paths} >= {"release.yml", "ci.yml", "docs.yml"}


def test_all_workflow_actions_are_immutable_full_shas_with_version_comments():
    for path in _workflow_paths():
        text, _ = _parse(path)
        references = re.findall(r"(?m)^\s+uses:\s+([^\s#]+)(?:\s+#\s*(.*))?$", text)
        assert references, f"{path.name} must use at least one action"
        for reference, comment in references:
            if reference.startswith("./"):
                continue
            _, separator, ref = reference.rpartition("@")
            assert separator and re.fullmatch(r"[0-9a-f]{40}", ref), (
                f"{path.name}: {reference} must pin a full commit SHA")
            assert comment and re.search(r"\bv\d", comment), (
                f"{path.name}: {reference} must record the upstream version")


def test_only_release_publish_job_can_write_repository_contents():
    _, workflow = _release_workflow()
    assert workflow.get("permissions") == {"contents": "read"}
    jobs = workflow["jobs"]
    write_jobs = [name for name, job in jobs.items()
                  if job.get("permissions", {}).get("contents") == "write"]
    assert write_jobs == ["publish"]
    assert jobs["publish"].get("needs") == "build"
    assert all(value != "write" for name, job in jobs.items() if name != "publish"
               for value in (job.get("permissions") or {}).values())


def test_pages_workflow_has_least_privilege_and_no_pull_request_trigger():
    path = WORKFLOWS / "docs.yml"
    _, workflow = _parse(path)
    assert workflow.get("permissions") == {"contents": "read"}
    deploy = workflow["jobs"]["deploy"]
    assert deploy.get("permissions") == {
        "contents": "read", "pages": "write", "id-token": "write"}
    assert "mkdocs build --strict" in path.read_text(encoding="utf-8")
    triggers = workflow.get("on", workflow.get(True, {}))
    assert "pull_request" not in triggers
