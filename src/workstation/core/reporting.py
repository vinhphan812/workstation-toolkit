"""Persistent JSON and Markdown reports."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from workstation.config import TOOLKIT_ROOT

REPORTS_DIR = TOOLKIT_ROOT / "reports"

def write_report(name: str, data: dict[str, Any]) -> dict[str, str]:
    """Write a timestamped JSON report and a minimal Markdown summary."""
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = REPORTS_DIR / f"{stamp}_{name}"
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), **data}
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [f"# {name}", "", f"Generated: `{payload['generated_at']}`", "", "```json", json.dumps(payload, indent=2, default=str), "```", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
