"""Configuration loading from TOML files."""
import os, json
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).parent.parent.parent  # src/workstation → toolkit root
CONFIG_DIR = os.environ.get("WORKSTATION_CONFIG", str(TOOLKIT_ROOT / "config"))

def load_local():
    path = Path(CONFIG_DIR) / "local.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None

def load_repos():
    path = Path(CONFIG_DIR) / "repos.json"
    if path.exists():
        with open(path) as f:
            j = json.load(f)
            return j.get("repos", [])
    return []

def load_projects():
    path = Path(CONFIG_DIR) / "projects.json"
    if path.exists():
        with open(path) as f:
            return json.load(f).get("projects", [])
    return []

def get_hermes_home():
    return os.environ.get("HERMES_HOME") or os.path.expandvars("%LOCALAPPDATA%\\hermes")

def get_hermes_profile():
    explicit = os.environ.get("HERMES_PROFILE_DIR")
    if explicit:
        return explicit

    # Hermes can set HERMES_HOME to either the installation root or the
    # active profile directory.  Detect a profile directory before appending
    # the conventional profiles/coordinator suffix.
    home = get_hermes_home()
    if os.path.basename(home).lower() == "coordinator" and os.path.basename(os.path.dirname(home)).lower() == "profiles":
        return home
    return os.path.join(home, "profiles", "coordinator")

