"""Source line-of-code (LOC) auditing and report generation."""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

# Source code and configuration formats. Deliberately excludes generated and
# dependency trees by default so results describe the maintained project code.
LANGUAGES = {
    ".py": "Python", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C/C++", ".cpp": "C++",
    ".cs": "C#", ".dart": "Dart", ".php": "PHP", ".rb": "Ruby", ".sh": "Shell",
    ".ps1": "PowerShell", ".sql": "SQL", ".prisma": "Prisma", ".xml": "XML",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
    ".gradle": "Gradle", ".properties": "Properties",
}

DEFAULT_EXCLUDED_DIRS = {
    ".git", ".gradle", ".idea", ".next", ".nuxt", ".venv", "venv",
    "node_modules", "build", "dist", "out", "target", "coverage",
    "__pycache__", ".worktrees", "vendor", "generated", "bin", "obj",
}

COMMENT_PREFIXES = {
    "Python": ("#",), "Java": ("//", "/*", "*", "*/"), "Kotlin": ("//", "/*", "*", "*/"),
    "JavaScript": ("//", "/*", "*", "*/"), "TypeScript": ("//", "/*", "*", "*/"),
    "Go": ("//", "/*", "*", "*/"), "Rust": ("//", "/*", "*", "*/"),
    "C": ("//", "/*", "*", "*/"), "C/C++": ("//", "/*", "*", "*/"),
    "C++": ("//", "/*", "*", "*/"), "C#": ("//", "/*", "*", "*/"), "Dart": ("//", "/*", "*", "*/"),
    "PHP": ("//", "#", "/*", "*", "*/"), "Ruby": ("#",), "Shell": ("#",),
    "PowerShell": ("#", "<#", "#>"), "SQL": ("--", "/*", "*", "*/"),
    "Prisma": ("//",), "XML": ("<!--", "-->") , "JSON": (), "YAML": ("#",),
    "TOML": ("#",), "Gradle": ("//", "/*", "*", "*/"), "Properties": ("#", "!"),
}


def _count_file(path: Path, language: str) -> dict:
    """Count physical, blank, comment-only, and nonblank code lines."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"total": 0, "blank": 0, "comment": 0, "code": 0}
    prefixes = COMMENT_PREFIXES.get(language, ())
    blank = comment = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank += 1
        elif prefixes and stripped.startswith(prefixes):
            comment += 1
    return {"total": len(lines), "blank": blank, "comment": comment, "code": len(lines) - blank - comment}


def loc_audit(project_path: str, *, include_config: bool = False, top: int = 20) -> dict:
    """Measure source LOC under a project without following generated trees."""
    root = Path(project_path).resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"project path does not exist: {root}"}
    per_language: dict[str, Counter] = {}
    files = []
    excluded = set(DEFAULT_EXCLUDED_DIRS)
    for current, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in excluded]
        for name in names:
            file_path = Path(current) / name
            language = LANGUAGES.get(file_path.suffix.lower())
            if not language:
                continue
            if not include_config and language in {"JSON", "YAML", "TOML", "XML", "Properties"}:
                continue
            counts = _count_file(file_path, language)
            per_language.setdefault(language, Counter()).update(counts)
            files.append({"path": str(file_path.relative_to(root)), "language": language, **counts})
    files.sort(key=lambda item: (item["code"], item["total"]), reverse=True)
    totals = Counter()
    for value in per_language.values(): totals.update(value)
    return {
        "ok": True, "project": str(root), "include_config": include_config,
        "excluded_directories": sorted(excluded), "files": len(files),
        "total": dict(totals),
        "languages": {language: {"files": sum(1 for file in files if file["language"] == language), **dict(counts)} for language, counts in sorted(per_language.items())},
        "largest_files": files[:top],
    }


def print_loc(report: dict) -> None:
    if not report.get("ok"):
        print(f"LOC audit failed: {report['error']}")
        return
    total = report["total"]
    print(f"\n=== LOC Audit: {Path(report['project']).name} ===")
    print(f"Files: {report['files']:,}; total lines: {total.get('total', 0):,}; code: {total.get('code', 0):,}; blank: {total.get('blank', 0):,}; comment-only: {total.get('comment', 0):,}")
    print("\nBy language:")
    for language, counts in report["languages"].items():
        print(f"  {language:<14} files={counts['files']:>5,} code={counts.get('code',0):>8,} total={counts.get('total',0):>8,}")
    print("\nLargest source files by code LOC:")
    for item in report["largest_files"]:
        print(f"  {item['code']:>7,} code / {item['total']:>7,} total  {item['path']}")
