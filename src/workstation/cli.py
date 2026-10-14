"""CLI entry point — python -m workstation."""
from __future__ import annotations

import argparse
import json
import sys

from workstation.config import load_repos
from workstation.core.reporting import write_report


def _emit(data: dict, args: argparse.Namespace, report_name: str | None = None) -> None:
    if getattr(args, "save_report", False) and report_name:
        paths = write_report(report_name, data)
        print(f"Reports: {paths['json']}\n         {paths['markdown']}")
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, default=str))


def cmd_diagnose(args):
    from workstation.modules import system
    report = system.full_diagnostic()
    system.print_diagnostic(report)
    _emit(report, args, "diagnose")


def cmd_storage(args):
    from workstation.modules import system
    report = system.storage_audit()
    system.print_storage(report)
    _emit(report, args, "storage")


def cmd_process(args):
    from workstation.core.process import list_processes, is_process_orphaned
    processes = []
    print(f"\n=== Heavy Processes (>{args.threshold} MB) ===")
    for proc in list_processes(args.threshold):
        orphaned, reason = is_process_orphaned(proc)
        item = {**proc.__dict__, "orphaned": orphaned, "reason": reason}
        processes.append(item)
        print(f"  {proc.ram_gb:>5.2f} GB  {proc.name} PID={proc.pid}{' ORPHANED' if orphaned else ''}")
        if proc.cmdline:
            print(f"      {proc.cmdline}")
    _emit({"processes": processes}, args, "process")


def cmd_git_identity(args):
    from workstation.core.git import check_all_identities, print_identity_report, fix_bad_identities
    repos = load_repos()
    audit = check_all_identities(repos)
    print_identity_report(audit)
    report = {"repos": [item.__dict__ for item in audit]}
    if args.fix:
        report["fix"] = fix_bad_identities(repos)
        print(f"Fix result: {report['fix']}")
    _emit(report, args, "git_identity")


def cmd_git_worktrees(args):
    from workstation.core.worktree import audit_all_worktrees, print_worktree_report, delete_orphaned
    audit = audit_all_worktrees(load_repos())
    print_worktree_report(audit)
    if args.execute:
        deleted = delete_orphaned(audit, confirm=not args.yes)
        print(f"Deleted: {len(deleted)}")
    report = {key: [item.__dict__ for item in value] if isinstance(value, list) else value for key, value in audit.items()}
    _emit(report, args, "worktrees")


def cmd_docker(args):
    from workstation.core.docker import get_state, prune_stopped, prune_images, prune_volumes
    report = get_state().__dict__
    print("\n=== Docker ===")
    print(json.dumps(report, indent=2))
    if args.prune:
        if not args.yes:
            raise SystemExit("Refusing cleanup without --yes.")
        report["prune_stopped"] = prune_stopped()
        if args.images:
            report["prune_images"] = prune_images()
        if args.volumes:
            report["prune_volumes"] = prune_volumes()
    _emit(report, args, "docker")


def cmd_docker_health(args):
    from workstation.modules.docker_health import docker_service_health
    report = docker_service_health(args.lines)
    print("\n=== Docker Service Health ===")
    for container in report.get("containers", []):
        print(f"\n[{container['name']}]\n{container['state_raw']}\n--- recent logs ---\n{container['recent_logs']}")
    _emit(report, args, "docker_health")


def cmd_docker_logs(args):
    from workstation.modules.docker_health import docker_log_tail
    report = docker_log_tail(args.container, args.lines)
    print(report["output"])
    _emit(report, args, f"docker_logs_{args.container}")


def cmd_hermes(args):
    from workstation.modules.hermes import hermes_health, print_hermes_report
    report = hermes_health()
    print_hermes_report(report)
    _emit(report, args, "hermes")


def cmd_repos(args):
    from workstation.modules.development_audit import repo_dirty_check, stale_branches, print_repo_check
    report = stale_branches() if args.stale_branches else repo_dirty_check()
    if args.stale_branches:
        print("\n=== Stale Local Branches ===")
        print(f"Candidates: {report['stale_count']}")
        for item in report["repos"]:
            if item["merged_local_branches"]:
                print(f"  {item['name']} ({item['default_branch']}): {', '.join(item['merged_local_branches'])}")
    else:
        print_repo_check(report)
    _emit(report, args, "stale_branches" if args.stale_branches else "repos")


def cmd_toolchain(args):
    from workstation.modules.development_audit import toolchain_audit, java_home_audit, android_sdk_audit, print_toolchain
    if args.java:
        report, name = java_home_audit(), "java"
        print("\n=== Java Home Audit ===")
        print(json.dumps(report, indent=2))
    elif args.android:
        report, name = android_sdk_audit(), "android_sdk"
        print("\n=== Android SDK Audit ===")
        print(json.dumps(report, indent=2))
    else:
        report, name = toolchain_audit(), "toolchain"
        print_toolchain(report)
    _emit(report, args, name)



def cmd_forecast(args):
    from workstation.modules.storage_ops import disk_space_forecast, print_forecast
    report = disk_space_forecast()
    print_forecast(report)
    _emit(report, args, "disk_forecast")


def cmd_kanban(args):
    from workstation.modules.kanban import kanban_health, archive_plan, print_kanban_health, print_archive_plan
    if args.archive_plan is not None:
        report = archive_plan(args.archive_plan)
        print_archive_plan(report)
        _emit(report, args, "kanban_archive_plan")
    else:
        report = kanban_health()
        print_kanban_health(report)
        _emit(report, args, "kanban_health")


def cmd_project(args):
    from workstation.modules.projects import project_status, run_project_command
    if args.project_action == "status":
        report = project_status(args.project)
        print(json.dumps(report, indent=2))
        _emit(report, args, "project_status")
        return
    report = run_project_command(args.project, args.project_action, execute=args.execute)
    print(json.dumps(report, indent=2))
    _emit(report, args, f"project_{args.project}_{args.project_action}")
    if not report.get("ok"):
        raise SystemExit(1)




def cmd_kanban(args):
    from workstation.modules.kanban import kanban_health, archive_plan, archive_tasks
    if args.archive and args.archive_execute:
        report = archive_tasks(args.archive, board=args.board, execute=args.archive_execute, yes=args.yes)
    elif args.archive:
        report = archive_plan(args.archive)
    else:
        report = kanban_health()
    print(json.dumps(report, indent=2))
    _emit(report, args, f"kanban_{args.board or 'all'}")
    if not report.get("ok"): raise SystemExit(1)

def cmd_loc(args):
    from workstation.modules.loc import loc_audit, print_loc
    from workstation.modules.projects import project_status
    project_path = args.path
    project_name = args.project
    if project_name:
        statuses = project_status(project_name)['projects']
        if not statuses:
            raise SystemExit(f"Unknown project: {project_name}")
        project_path = statuses[0]['path']
    if not project_path:
        raise SystemExit("Provide --path PATH or --project PROJECT")
    report = loc_audit(project_path, include_config=args.include_config, top=args.top)
    print_loc(report)
    _emit(report, args, f"loc_{project_name or Path(project_path).name}")
    if not report.get('ok'):
        raise SystemExit(1)

def cmd_backup(args):
    from workstation.modules.maintenance import create_backup
    try:
        report = create_backup(args.label)
    except Exception as exc:
        raise SystemExit(f"Backup blocked: {exc}")
    print(json.dumps(report, indent=2))
    _emit(report, args, f"backup_{args.label}")


def cmd_restore(args):
    from workstation.modules.maintenance import restore_backup
    try:
        report = restore_backup(args.manifest, execute=args.execute, yes=args.yes)
    except Exception as exc:
        raise SystemExit(str(exc))
    print(json.dumps(report, indent=2))
    _emit(report, args, "restore")


def cmd_hermes_maintain(args):
    from workstation.modules.maintenance import hermes_db_maintenance, print_maintenance
    try:
        report = hermes_db_maintenance(execute=args.execute, yes=args.yes, min_free_gb=args.min_free_gb)
    except Exception as exc:
        raise SystemExit(str(exc))
    print_maintenance(report)
    _emit(report, args, "hermes_maintenance")
    if not report.get('ok'): raise SystemExit(1)


def cmd_android_plan(args):
    from workstation.modules.android_cleanup import android_cleanup_plan, print_android_plan
    report = android_cleanup_plan(load_repos())
    print_android_plan(report)
    _emit(report, args, "android_cleanup_plan")


def cmd_schedule(args):
    from workstation.modules.scheduler import schedule_plan, create_schedule
    if args.create:
        try:
            report = create_schedule(args.hour, execute=True, yes=args.yes)
        except Exception as exc:
            raise SystemExit(str(exc))
    else:
        report = schedule_plan(args.hour)
    print(json.dumps(report, indent=2))
    _emit(report, args, "schedule")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workstation", description="Cross-platform workstation diagnostic and maintenance toolkit")
    parser.add_argument("--json", action="store_true", help="Also output JSON")
    parser.add_argument("--save-report", action="store_true", help="Write timestamped JSON and Markdown reports")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diagnose", help="Full system diagnostic").set_defaults(func=cmd_diagnose)
    sub.add_parser("storage", help="Mounted drive capacity audit").set_defaults(func=cmd_storage)
    p = sub.add_parser("process", help="Heavy process audit"); p.add_argument("-t", "--threshold", type=int, default=500); p.set_defaults(func=cmd_process)
    p = sub.add_parser("git-identity", help="Git identity audit"); p.add_argument("--fix", action="store_true"); p.set_defaults(func=cmd_git_identity)
    p = sub.add_parser("git-worktrees", help="Git worktree audit"); p.add_argument("--execute", action="store_true"); p.add_argument("-y", "--yes", action="store_true"); p.set_defaults(func=cmd_git_worktrees)
    p = sub.add_parser("docker", help="Docker audit and explicit cleanup"); p.add_argument("--prune", action="store_true"); p.add_argument("--images", action="store_true"); p.add_argument("--volumes", action="store_true"); p.add_argument("-y", "--yes", action="store_true"); p.set_defaults(func=cmd_docker)
    p = sub.add_parser("docker-health", help="Running Docker services and recent logs"); p.add_argument("--lines", type=int, default=30); p.set_defaults(func=cmd_docker_health)
    p = sub.add_parser("docker-logs", help="Tail a Docker container log"); p.add_argument("container"); p.add_argument("--lines", type=int, default=100); p.set_defaults(func=cmd_docker_logs)
    sub.add_parser("hermes", help="Hermes health check").set_defaults(func=cmd_hermes)
    p = sub.add_parser("repos", help="Repository status audit"); p.add_argument("--stale-branches", action="store_true"); p.set_defaults(func=cmd_repos)
    p = sub.add_parser("toolchain", help="Developer toolchain audit"); p.add_argument("--java", action="store_true"); p.add_argument("--android", action="store_true"); p.set_defaults(func=cmd_toolchain)
    sub.add_parser("forecast", help="Disk pressure and managed-artifact forecast").set_defaults(func=cmd_forecast)
    p = sub.add_parser("kanban", help="Kanban health and optional archiving"); p.add_argument("--archive-plan", type=int, metavar="DAYS", dest="archive", help="List done tasks older than DAYS; omit --execute to preview"); p.add_argument("--board", help="Filter to one board"); p.add_argument("--execute", dest="archive_execute", action="store_true", help="Execute the archive (requires --archive-plan DAYS)"); p.add_argument("-y", "--yes", action="store_true"); p.set_defaults(func=cmd_kanban)
    p = sub.add_parser("project", help="Config-driven project status and commands"); p.add_argument("project", nargs="?", help="Project name; omit for all statuses"); p.add_argument("project_action", choices=["status", "test", "lint", "clean", "web-test"], default="status", nargs="?"); p.add_argument("--execute", action="store_true", help="Actually run configured command; default is dry-run"); p.set_defaults(func=cmd_project)
    p = sub.add_parser("loc", help="Source LOC audit and report"); group = p.add_mutually_exclusive_group(required=True); group.add_argument("--path"); group.add_argument("--project"); p.add_argument("--include-config", action="store_true"); p.add_argument("--top", type=int, default=20); p.set_defaults(func=cmd_loc)
    p = sub.add_parser("backup", help="Backup local config and Hermes state database"); p.add_argument("--label", default="workstation"); p.set_defaults(func=cmd_backup)
    p = sub.add_parser("restore", help="Restore files from a backup manifest"); p.add_argument("manifest"); p.add_argument("--execute", action="store_true"); p.add_argument("-y", "--yes", action="store_true"); p.set_defaults(func=cmd_restore)
    p = sub.add_parser("hermes-maintain", help="Backup/checkpoint/optimize Hermes DB; explicit and disk-gated"); p.add_argument("--execute", action="store_true"); p.add_argument("-y", "--yes", action="store_true"); p.add_argument("--min-free-gb", type=float, default=15.0); p.set_defaults(func=cmd_hermes_maintain)
    sub.add_parser("android-cleanup-plan", help="Read-only Android SDK cleanup plan from Gradle requirements").set_defaults(func=cmd_android_plan)
    p = sub.add_parser("schedule", help="Preview or opt-in create daily health report schedule"); p.add_argument("--hour", type=int, default=9); p.add_argument("--create", action="store_true"); p.add_argument("-y", "--yes", action="store_true"); p.set_defaults(func=cmd_schedule)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
