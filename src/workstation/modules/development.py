"""Development environment modules."""
from workstation.core.git import check_all_identities, fix_bad_identities
from workstation.core.worktree import audit_all_worktrees
from workstation.config import load_repos

def full_dev_audit() -> dict:
    repos = load_repos()
    identities = check_all_identities(repos)
    worktrees = audit_all_worktrees(repos)
    return {
        "repos_scanned": len(repos),
        "bad_identities": [r for r in identities if r.is_bad],
        "good_local": [r for r in identities if r.is_local and not r.is_bad],
        "orphaned_worktrees": worktrees["orphaned"],
        "total_orphaned_size_mb": worktrees["total_orphaned_size_mb"],
    }

def fix_dev_identities() -> dict:
    repos = load_repos()
    return fix_bad_identities(repos)
