"""Configuration loading from JSON files."""
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

def load_repo_excludes() -> list[str]:
    """Return the directory names excluded while walking a repository.

    These are the names listed under ``exclude_patterns`` in ``repos.json``.
    They match a directory name at any depth, so ``.venv`` excludes every
    directory called ``.venv`` in the tree.

    An entry that is a path rather than a plain name, such as
    ``node_modules/.cache``, is reduced to its first component. Excluding
    ``node_modules/.cache`` only makes sense if the walk does not descend
    into ``node_modules`` in the first place, and the dependency tree
    inside it is the expensive part to walk.
    """
    path = Path(CONFIG_DIR) / "repos.json"
    if path.exists():
        try:
            with open(path) as f:
                j = json.load(f)
        except (OSError, ValueError):
            return []
        patterns = j.get("exclude_patterns", [])
        if isinstance(patterns, list):
            names = []
            for pattern in patterns:
                text = str(pattern).replace("\\", "/").strip("/")
                if not text:
                    continue
                names.append(text.split("/", 1)[0])
            return names
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

