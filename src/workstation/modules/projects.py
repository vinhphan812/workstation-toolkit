"""Config-driven project status, validation and safe command execution."""
from __future__ import annotations
import os, subprocess
from workstation.config import load_projects


def _find(name: str) -> dict | None:
    return next((project for project in load_projects() if project.get('name') == name), None)


def project_status(name: str | None = None) -> dict:
    projects = load_projects()
    if name:
        projects = [p for p in projects if p.get('name') == name]
    result = []
    for project in projects:
        path = project.get('path', '')
        exists = os.path.isdir(path)
        result.append({'name': project.get('name'), 'path': path, 'exists': exists, 'type': project.get('type'), 'commands': project.get('commands', {})})
    return {'projects': result}


def run_project_command(name: str, action: str, execute: bool = False) -> dict:
    project = _find(name)
    if not project:
        return {'ok': False, 'error': f'project {name!r} not found'}
    path = project.get('path', '')
    if not os.path.isdir(path):
        return {'ok': False, 'error': f'path missing: {path}'}
    command = project.get('commands', {}).get(action)
    if not command:
        return {'ok': False, 'error': f'action {action!r} not configured'}
    if not execute:
        return {'ok': True, 'dry_run': True, 'cwd': path, 'command': command}
    env = os.environ.copy()
    env.update(project.get('environment', {}))
    try:
        proc = subprocess.run(command, cwd=path, env=env, shell=True, text=True, capture_output=True, timeout=project.get('timeouts', {}).get(action, 900))
        return {'ok': proc.returncode == 0, 'dry_run': False, 'cwd': path, 'command': command, 'exit_code': proc.returncode, 'output': (proc.stdout + proc.stderr)[-12000:]}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'command timed out', 'command': command}
