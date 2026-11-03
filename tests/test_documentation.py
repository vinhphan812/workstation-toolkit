"""Documentation consistency tests.

These tests keep the documentation honest. A document that contradicts the
code is worse than no document, so the claims the documentation makes about
the command line, the configuration and the repository layout are checked
against the source.

The tests are deliberately about *consistency*, not about prose quality.
"""
from pathlib import Path
import ast
import os
import re

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
CLI = ROOT / "src" / "workstation" / "cli.py"
CONFIG = ROOT / "src" / "workstation" / "config.py"
GITIGNORE = ROOT / ".gitignore"

DOCS = (
    README,
    CONTRIBUTING,
    ROOT / "docs" / "backup-permissions.md",
    ROOT / "docs" / "command-reference.md",
    ROOT / "docs" / "configuration.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "index.md",
    ROOT / "docs" / "templates" / "index.md",
    ROOT / "docs" / "templates" / "changelog_template.md",
    ROOT / "docs" / "templates" / "architecture_template.md",
    ROOT / "CHANGELOG.md",
)

DOCS_INDEX = ROOT / "docs" / "index.md"
TEMPLATES = ROOT / "docs" / "templates"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def _read(path):
    return path.read_text(encoding="utf-8")


def _cli_source():
    return _read(CLI)


def _documented_commands():
    """The command names the README and the command reference both mention."""
    text = _read(README) + "\n" + _read(ROOT / "docs" / "command-reference.md")
    return set(re.findall(r"python -m workstation ([a-z][a-z0-9-]*)", text))


def _parser_names():
    """Every subcommand the CLI actually defines."""
    source = _cli_source()
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_parser"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            names.add(node.args[0].value)
    return names


def _reference_sections():
    """The command names that have their own section in the command reference."""
    reference = _read(ROOT / "docs" / "command-reference.md")
    # A heading names one command, or a parent and a subcommand such as
    # `guard scan`; the first word is the top-level command.
    headings = [h.split()[0] for h in
                re.findall(r"^#{2,4} `([a-z][a-z0-9-]*(?: [a-z][a-z0-9-]*)?)`", reference, re.M)]
    # 'verify', 'scan' and 'kill' are nested subcommands and are documented
    # under their parent command rather than in a section of their own.
    return set(headings) | {"verify", "scan", "kill"}


def test_every_cli_subcommand_is_documented():
    """A command that exists but has no section in the reference is a gap."""
    missing = sorted(name for name in _parser_names() if name not in _reference_sections())
    assert not missing, f"no section in the command reference: {missing}"


def test_every_cli_subcommand_is_in_the_readme_command_table():
    """The README command table must list every command the CLI exposes."""
    text = _read(README)
    table = re.findall(r"^\| `([a-z][a-z0-9-]*)", text, re.M)
    listed = set(table)
    listed |= {"verify", "scan", "kill"}
    missing = sorted(name for name in _parser_names() if name not in listed)
    assert not missing, f"not in the README command table: {missing}"


def test_documented_commands_exist():
    """A command that is documented but does not exist is worse."""
    documented = _documented_commands()
    unknown = sorted(name for name in documented
                     if name not in _parser_names() and name not in {"verify", "scan", "kill"})
    assert not unknown, f"documented but not implemented: {unknown}"


def test_readme_table_of_contents_matches_its_headings():
    """A stale table of contents makes a long document unusable."""
    text = _read(README)
    headings = [re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-")
                for h in re.findall(r"^#{2,4} (.+)$", text, re.M)]
    anchors = re.findall(r"\]\(#([a-z0-9-]+)\)", text)
    assert not [a for a in anchors if a not in headings], "table of contents points at a missing heading"
    missing = [h for h in headings if h not in anchors and h != "contents"]
    assert not missing, f"headings missing from the table of contents: {missing}"


def _anchor_slugs(text):
    return [re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-")
            for h in re.findall(r"^#{1,6} (.+)$", text, re.M)]


def test_relative_links_between_documents_resolve():
    """Links must work both on GitHub and in a local checkout."""
    import os
    for document in DOCS:
        text = _read(document)
        base = document.parent
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            path_part, _, anchor = link.partition("#")
            if path_part:
                target = os.path.normpath(os.path.join(str(base), path_part))
                assert Path(target).exists(), f"broken link {link!r} in {document.name}"
                if anchor:
                    heading_text = _read(Path(target))
                    assert anchor in _anchor_slugs(heading_text), (
                        f"link {link!r} points at a missing heading in {document.name}")
            else:
                assert anchor in _anchor_slugs(text), (
                    f"link {link!r} points at a missing heading in {document.name}")


def _ignore_rules():
    """The ignore rules, with comments and blank lines removed."""
    return [line.strip() for line in _read(GITIGNORE).splitlines()
            if line.strip() and not line.strip().startswith("#")]


def _docs_relative_links(document):
    """The repository-relative targets of the Markdown links in a document."""
    base = document.parent
    targets = set()
    for link in re.findall(r"\]\(([^)]+)\)", _read(document)):
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        path_part, _, _anchor = link.partition("#")
        if not path_part:
            continue
        targets.add(os.path.normpath(os.path.join(str(base), path_part)))
    return targets


def test_the_documentation_index_links_every_document():
    """A document that no index reaches cannot be found.

    Each document has exactly one owning index: the templates belong to the
    template library index, everything else to the documentation index.
    """
    linked = _docs_relative_links(DOCS_INDEX)
    template_linked = _docs_relative_links(TEMPLATES / "index.md")
    for document in DOCS:
        if document in (README, CONTRIBUTING, CHANGELOG, DOCS_INDEX):
            continue
        # The template library index belongs to the documentation index; the
        # templates inside it belong to the library index.
        owner = linked
        if document.parent == TEMPLATES and document != TEMPLATES / "index.md":
            owner = template_linked
        assert str(document) in owner, (
            f"{document.relative_to(ROOT).as_posix()} is not linked from its index")


def test_every_document_is_reachable_from_an_index():
    """Every document under docs/ is linked from the index or the template index."""
    reachable = _docs_relative_links(DOCS_INDEX) | _docs_relative_links(TEMPLATES / "index.md")
    for document in sorted((ROOT / "docs").rglob("*.md")):
        if document == DOCS_INDEX:
            continue
        assert str(document) in reachable, (
            f"{document.relative_to(ROOT).as_posix()} is not reachable from an index")


def test_the_changelog_template_has_been_extracted():
    """The template lives in the template library, not inside the changelog."""
    template = TEMPLATES / "changelog_template.md"
    assert template.exists(), "the changelog template must live in docs/templates/"
    changelog = _read(CHANGELOG)
    # The template describes the structure with placeholders; the changelog
    # itself must not carry them.
    assert "YYYY-MM-DD" not in changelog, "the changelog still contains a date placeholder"
    assert "OWNER/REPO" not in changelog, "the changelog still contains a repository placeholder"
    assert "changelog_template.md" in changelog, (
        "the changelog must point at its own template")


def test_the_changelog_records_every_release_and_the_unreleased_work():
    """The changelog keeps its release structure and accurately scopes the list."""
    changelog = _read(CHANGELOG)
    versions = re.findall(r"^## \[(.+?)\]", changelog, re.M)
    assert "Unreleased" in versions, "the changelog must have an Unreleased section"
    assert "0.1.0" in versions, "the changelog must record the released version"
    for version in versions:
        assert re.search(rf"^\[{re.escape(version)}\]:\s+https://", changelog, re.M), (
            f"version {version} has no link definition")
    # The released version must be dated, and the unreleased section must not be.
    assert re.search(r"^## \[0\.1\.0\] - \d{4}-\d{2}-\d{2}$", changelog, re.M), (
        "a released version must carry its release date")
    assert re.search(r"^## \[Unreleased\]$", changelog, re.M), (
        "the unreleased section must not carry a date")


def test_the_changelog_does_not_claim_complete_commit_coverage():
    """A selected-change log must not imply a complete commit ledger."""
    changelog = _read(CHANGELOG).lower()
    assert "selected notable changes" in changelog, (
        "the unreleased section must identify its entries as selected notable changes")
    assert not re.search(r"\b\d+ commits? across \d+ days?\b", changelog), (
        "do not state a commit/day total unless full commit coverage is verified")
    for unsupported_claim in (
        "every commit", "all commits", "every non-merge commit",
    ):
        assert unsupported_claim not in changelog, (
            f"the changelog makes an unsupported completeness claim: {unsupported_claim}")


def test_unreleased_changelog_has_no_unexplained_current_pr_placeholders():
    """Current changelog entries must not use vague or non-resolving attribution."""
    changelog = _read(CHANGELOG)
    unreleased = changelog.split("## [0.1.0]", 1)[0]
    assert "and this change" not in unreleased.lower(), (
        "use the actual commit hash rather than 'and this change'")
    assert not re.search(r"`(?:HEAD|WORKTREE|PR)`", unreleased), (
        "use an existing commit hash rather than a symbolic placeholder")


def test_the_architecture_document_names_only_files_that_exist():
    """A path in the architecture document that has been deleted is a broken claim."""
    text = _read(ARCHITECTURE)
    package = ROOT / "src" / "workstation"
    referenced = set(re.findall(r"`([A-Za-z0-9_/]+\.py)`", text))
    assert referenced, "the architecture document must name the source files"
    for relative in sorted(referenced):
        # The document names the files the way the package is laid out, so a
        # path such as `core/disk.py` resolves inside the package.
        assert (package / relative).exists() or (ROOT / relative).exists(), (
            f"architecture names a missing file: {relative}")


def test_the_architecture_document_describes_every_module():
    """Every module of the toolkit must have a row in the architecture tables."""
    text = _read(ARCHITECTURE)
    package = ROOT / "src" / "workstation"
    modules = sorted(p.name for p in (package / "modules").glob("*.py")
                     if p.name != "__init__.py")
    assert modules, "the toolkit must have modules"
    for name in modules:
        row = f"| `modules/{name}` |"
        assert row in text, f"modules/{name} has no row in the architecture tables"


def test_the_architecture_document_has_a_row_for_every_core_module():
    """Every core module must have a row, so its responsibility is stated."""
    text = _read(ARCHITECTURE)
    package = ROOT / "src" / "workstation"
    modules = sorted(p.name for p in (package / "core").glob("*.py")
                     if p.name != "__init__.py")
    assert modules, "the toolkit must have core modules"
    for name in modules:
        row = f"| `core/{name}` |"
        assert row in text, f"core/{name} has no row in the architecture tables"


def test_the_architecture_document_has_a_row_for_every_adapter():
    """Every platform adapter must have a row."""
    text = _read(ARCHITECTURE)
    package = ROOT / "src" / "workstation"
    adapters = sorted(p.name for p in (package / "adapters").glob("*.py")
                      if p.name != "__init__.py")
    assert adapters, "the toolkit must have adapters"
    for name in adapters:
        row = f"| `adapters/{name}` |"
        assert row in text, f"adapters/{name} has no row in the architecture tables"


def test_the_architecture_document_states_the_measured_tree_size():
    """The line and file counts in the architecture document must be true."""
    text = _read(ARCHITECTURE)
    source = ROOT / "src" / "workstation"
    files = [p for p in source.rglob("*.py") if "__pycache__" not in p.parts]
    lines = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in files)
    assert f"| {len(files)} | {lines} |" in text, (
        "the architecture document must state the current source file and line counts")


def test_the_documentation_site_is_configured():
    """The MkDocs configuration must exist and name every published page."""
    config = ROOT / "mkdocs.yml"
    assert config.exists(), "the documentation site needs a mkdocs.yml"
    text = _read(config)
    for page in ("index.md", "architecture.md", "command-reference.md",
                 "configuration.md", "backup-permissions.md",
                 "templates/index.md", "templates/changelog_template.md",
                 "templates/architecture_template.md"):
        assert page in text, f"{page} is not in the site navigation"


def test_the_built_site_is_not_tracked():
    """The generated site must not be committed."""
    rules = _ignore_rules()
    assert "site/" in rules, "the generated documentation site must be gitignored"


def test_device_local_config_is_gitignored():
    """The loader reads config/local.json, so it must be ignored."""
    rules = _ignore_rules()
    assert "config/local.json" in rules, "config/local.json is read by the loader but not ignored"


def test_ignored_config_files_are_the_ones_the_loader_reads():
    """Every file the loader reads must be ignored, so none can be committed."""
    source = _read(CONFIG)
    read_files = set(re.findall(r'CONFIG_DIR\) / "([^"]+)"', source))
    rules = _ignore_rules()
    for name in read_files:
        assert f"config/{name}" in rules, f"config/{name} is read but not ignored"


def test_toml_examples_are_not_loaded():
    """The documentation states that the TOML examples are never parsed."""
    source = _read(CONFIG)
    assert ".toml" not in source, "the loader must not read TOML files"
    example = _read(ROOT / "config" / "projects.toml.example")
    assert "not loaded" in example or "not read" in example


def _source_text():
    text = ""
    for module in (ROOT / "src" / "workstation").rglob("*.py"):
        text += module.read_text(encoding="utf-8")
    return text


def test_documented_environment_variables_exist_in_the_source():
    """An environment variable that the source never reads is a false claim."""
    source = _source_text()
    for name in ("WORKSTATION_CONFIG", "HERMES_HOME", "HERMES_PROFILE_DIR",
                 "HERMES_KANBAN_HOME", "WORKSTATION_ALLOW_SHELL"):
        assert name in source, f"{name} is documented but never read by the source"


def test_environment_variables_in_the_documentation_are_read_by_the_source():
    """Every environment variable named in the reference must be real."""
    source = _source_text()
    for document in (README, ROOT / "docs" / "configuration.md"):
        for name in set(re.findall(r"\| `([A-Z][A-Z0-9_]+)` \|", _read(document))):
            assert name in source, (
                f"{name} is documented in {document.name} but never read by the source")


def test_configuration_document_lists_the_real_files():
    """The configuration reference must name the files that exist."""
    configuration = _read(ROOT / "docs" / "configuration.md")
    for name in ("local.json", "repos.json", "projects.json"):
        assert name in configuration
        assert (ROOT / "config" / f"{name}.example").exists() or name == "local.json"


def test_documentation_uses_british_spelling():
    """The documented house style is British English."""
    american = re.compile(
        r"\b(behavior\w*|artifact\w*|organiz\w+|recogniz\w+|analyz\w+|"
        r"center\w*|defense\w*|fulfill\w*|modeling\w*)\b", re.I)
    for document in DOCS:
        found = sorted(set(m.group(0).lower() for m in american.finditer(_read(document))))
        assert not found, f"{document.name} uses American spelling: {found}"


def test_every_document_is_in_english():
    """No document may mix another language into its prose."""
    # A cheap but effective guard: Vietnamese and Chinese diacritics must not
    # appear in the documentation.
    non_ascii_words = re.compile(r"[\u00c0-\u1fff\u4e00-\u9fff]")
    for document in DOCS:
        offenders = sorted(set(non_ascii_words.findall(_read(document))))
        assert not offenders, f"{document.name} contains non-English characters"

def test_exit_codes_are_documented():
    """The command reference must state what each exit code means."""
    reference = _read(ROOT / "docs" / "command-reference.md")
    assert "## Exit codes" in reference, "the exit codes must be documented"
    for code in ("`0`", "`1`", "`2`"):
        assert f"| {code} |" in reference, f"exit code {code} is not documented"


def test_documented_exit_codes_match_the_cli_behaviour():
    """The documented exit codes must be the ones the CLI actually returns.

    Argparse rejects invalid arguments with exit code 2; the CLI signals a
    reported failure with exit code 1 and success with exit code 0.
    """
    import argparse
    import subprocess
    import sys

    python = sys.executable
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")

    def run(args):
        result = subprocess.run(
            [python, "-m", "workstation"] + args, cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=300)
        return result.returncode

    # Invalid arguments are rejected by the parser with exit code 2.
    assert run(["loc"]) == 2, "a missing required argument must exit 2"
    # A successful read-only command exits 0.
    assert run(["storage"]) == 0, "a successful command must exit 0"
    # A failure that prevents the command from running is reported as a
    # single line, not as a traceback.
    result = subprocess.run(
        [python, "-m", "workstation", "backup", "verify",
         str(ROOT / "no-such-manifest.json")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr, (
        "a failure must be reported cleanly, not as a traceback")
    assert len(result.stderr.strip().splitlines()) == 1, (
        "a failure must be reported as a single line")
