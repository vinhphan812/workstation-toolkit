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
    if not isinstance(path, str) or not os.path.isdir(path):
        return {'ok': False, 'error': f'path missing or invalid: {path}'}
    commands = project.get('commands', {})
    if not isinstance(commands, dict):
        return {'ok': False, 'error': 'commands must be an object'}
    command = commands.get(action)
    if command is None:
        return {'ok': False, 'error': f'action {action!r} not configured'}
    shell_mode = isinstance(command, str)
    if not shell_mode and (not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command)):
        return {'ok': False, 'error': 'command must be a non-empty string or argv array'}
    if shell_mode and project.get('trusted_shell') is not True and execute:
        return {'ok': False, 'error': 'string commands require trusted_shell: true; prefer argv arrays'}
    if not execute:
        return {'ok': True, 'dry_run': True, 'cwd': path, 'command': command}
    timeouts = project.get('timeouts', {})
    if not isinstance(timeouts, dict):
        return {'ok': False, 'error': 'timeouts must be an object'}
    timeout = timeouts.get(action, 900)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        return {'ok': False, 'error': 'timeout must be a positive number'}
    configured_env = project.get('environment', {})
    if not isinstance(configured_env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in configured_env.items()):
        return {'ok': False, 'error': 'environment must be an object of string values'}
    env = os.environ.copy()
    env.update(configured_env)
    try:
        proc = subprocess.run(command, cwd=path, env=env, shell=shell_mode, text=True, capture_output=True, timeout=timeout)
        return {'ok': proc.returncode == 0, 'dry_run': False, 'cwd': path, 'command': command, 'exit_code': proc.returncode, 'output': (proc.stdout + proc.stderr)[-12000:]}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'command timed out', 'command': command}
    except (OSError, ValueError) as exc:
        return {'ok': False, 'error': f'command execution failed: {exc}', 'command': command}
