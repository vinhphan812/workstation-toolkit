"""Git utilities — cross-platform."""
import subprocess, os
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class GitIdentity:
    email: str
    name: str

@dataclass
class RepoIdentity:
    path: str
    name: str
    local_email: Optional[str]
    local_name: Optional[str]
    is_local: bool
    is_bad: bool

BAD_PATTERNS = [
    "hermes@agent.local",
    "hermes-agent@",
    "test@localhost",
    "user@example.com",
]

GOOD_PATTERNS = [
    "vinhphan812@gmail.com",
    "vpan812@students",
    "hermes-devops@opsswarm.local",
]

def run_git(repo: str, *args) -> tuple[str, int]:
    try:
        r = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip(), r.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return str(e), 1

def get_global_identity() -> Optional[GitIdentity]:
    try:
        r = subprocess.run(["git", "config", "--global", "user.email"],
                            capture_output=True, text=True, timeout=5)
        email = r.stdout.strip() if r.returncode == 0 else ""
        r = subprocess.run(["git", "config", "--global", "user.name"],
                            capture_output=True, text=True, timeout=5)
        name = r.stdout.strip() if r.returncode == 0 else ""
        if email:
            return GitIdentity(email=email, name=name)
    except FileNotFoundError:
        pass
    return None

def get_local_identity(repo: str) -> Optional[GitIdentity]:
    stdout, code = run_git(repo, "config", "--local", "user.email")
    if code != 0 or not stdout:
        return None
    email = stdout.strip()
    stdout, _ = run_git(repo, "config", "--local", "user.name")
    name = stdout.strip() if stdout else ""
    return GitIdentity(email=email, name=name)

def is_bad_identity(email: str) -> bool:
    return any(p in email for p in BAD_PATTERNS)

def is_good_identity(email: str) -> bool:
    return any(p in email for p in GOOD_PATTERNS)

def check_all_identities(repos: List[str]) -> List[RepoIdentity]:
    global_id = get_global_identity()
    results = []
    for repo in repos:
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        local = get_local_identity(repo)
        is_bad = local and is_bad_identity(local.email)
        results.append(RepoIdentity(
            path=repo,
            name=os.path.basename(repo),
            local_email=local.email if local else None,
            local_name=local.name if local else None,
            is_local=local is not None,
            is_bad=is_bad,
        ))
    return results

def unset_local_identity(repo: str) -> bool:
    run_git(repo, "config", "--local", "--unset", "user.email")
    run_git(repo, "config", "--local", "--unset", "user.name")
    # Verify
    local = get_local_identity(repo)
    return local is None

def fix_bad_identities(repos: List[str]) -> dict:
    results = check_all_identities(repos)
    fixed, failed = [], []
    for r in results:
        if r.is_bad:
            ok = unset_local_identity(r.path)
            if ok:
                fixed.append(r.name)
            else:
                failed.append(r.name)
    return {"fixed": fixed, "failed": failed}

def get_repo_branches(repo: str) -> List[str]:
    stdout, code = run_git(repo, "branch", "--format=%(refname:short)")
    if code != 0:
        return []
    return [b.strip() for b in stdout.splitlines() if b.strip()]

def is_repo_dirty(repo: str) -> bool:
    stdout, code = run_git(repo, "status", "--porcelain")
    return code == 0 and bool(stdout)

def get_remotes(repo: str) -> List[str]:
    stdout, code = run_git(repo, "remote", "-v")
    if code != 0:
        return []
    return list(dict.fromkeys(
        line.split()[1] for line in stdout.splitlines() if line.strip()
    ))


def print_identity_report(results: List[RepoIdentity]) -> None:
    """Print local Git identity overrides and flag dangerous values."""
    bad = [item for item in results if item.is_bad]
    local = [item for item in results if item.is_local]
    print("\n=== Git Identity Audit ===")
    print(f"Repos scanned: {len(results)}")
    print(f"Local overrides: {len(local)}")
    print(f"Bad overrides: {len(bad)}")
    for item in local:
        state = "BAD" if item.is_bad else "OK"
        print(f"  [{state}] {item.name}: {item.local_name or ''} <{item.local_email}>")
