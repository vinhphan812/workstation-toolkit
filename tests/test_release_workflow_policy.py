from pathlib import Path
import re
try:
    import yaml
except ImportError:  # pragma: no cover - reported as a test setup error
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _release_workflow():
    if yaml is None:
        raise RuntimeError("release workflow policy tests require PyYAML")
    # GitHub Actions uses the YAML 1.2 `on` key; PyYAML's YAML 1.1 resolver
    # treats it as boolean, so normalize only for policy inspection.
    text = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text.replace("\non:\n", "\n' on':\n", 1))
    assert isinstance(parsed, dict)
    return text, parsed


def test_release_actions_are_immutable_full_shas_with_version_comments():
    text, _ = _release_workflow()
    references = re.findall(r"(?m)^\s+uses:\s+([^\s#]+)(?:\s+#\s*(.*))?$", text)
    assert references, "release workflow must use at least one action"
    for reference, comment in references:
        if reference.startswith("./"):
            continue
        action, separator, ref = reference.rpartition("@")
        assert separator and re.fullmatch(r"[0-9a-f]{40}", ref), reference
        assert comment and re.search(r"\bv\d", comment), reference


def test_only_release_publish_job_can_write_repository_contents():
    _, workflow = _release_workflow()
    assert workflow.get("permissions") == {"contents": "read"}
    jobs = workflow["jobs"]
    assert jobs["build"].get("permissions") is None
    write_jobs = [name for name, job in jobs.items()
                  if job.get("permissions", {}).get("contents") == "write"]
    assert write_jobs == ["publish"]
    assert jobs["publish"].get("needs") == "build"
    assert all(value != "write" for name, job in jobs.items() if name != "publish"
               for value in (job.get("permissions") or {}).values())
