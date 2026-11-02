"""Documentation consistency tests.

These tests keep the documentation honest. A document that contradicts the
code is worse than no document, so the claims the documentation makes about
the command line, the configuration and the repository layout are checked
against the source.

The tests are deliberately about *consistency*, not about prose quality.
"""
from pathlib import Path
import ast
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
    ROOT / "CHANGELOG.md",
)


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
