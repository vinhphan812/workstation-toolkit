"""Config-driven project status, validation and safe command execution.

Configured commands are executable code.  Two execution modes are supported:

``argv``
    Executed without a shell.  Every argument is passed literally, so shell
    metacharacters in configured values are data and never syntax.

``shell``
    Interpreted by the platform shell.  This mode is only reachable through an
    explicit trusted-shell opt-in supplied by the operator (``--allow-shell``
    on the CLI, or ``WORKSTATION_ALLOW_SHELL=1`` for automation).  The opt-in
    deliberately does *not* live in the project configuration: a party able to
    edit the configuration must not be able to grant themselves the right to
    run arbitrary shell code.

``--execute`` runs the configured command with the privileges of the current
user, exactly as if the operator had typed it into a terminal.
"""
from __future__ import annotations
import os, subprocess
from workstation.config import load_projects
from workstation.core.command_spec import (
    CommandConfigError,
    parse_command,
    parse_environment,
    parse_timeout,
)

#: Environment variable used to opt into trusted-shell execution from
#: automation.  It is intentionally outside the project configuration.
ALLOW_SHELL_ENV = 'WORKSTATION_ALLOW_SHELL'


def _allow_shell_from_environment() -> bool:
    return os.environ.get(ALLOW_SHELL_ENV, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _find(name: str) -> dict | None:
    return next((project for project in load_projects() if project.get('name') == name), None)


def _commands_of(project: dict) -> dict:
    commands = project.get('commands', {})
    return commands if isinstance(commands, dict) else {}


def project_status(name: str | None = None) -> dict:
    projects = load_projects()
    if name:
        projects = [p for p in projects if p.get('name') == name]
    result = []
    for project in projects:
        path = project.get('path', '')
        exists = os.path.isdir(path)
        modes = {}
        for action, value in _commands_of(project).items():
            try:
                modes[action] = parse_command(value).mode
            except CommandConfigError:
                modes[action] = 'invalid'
        result.append({'name': project.get('name'), 'path': path, 'exists': exists, 'type': project.get('type'), 'commands': _commands_of(project), 'command_modes': modes})
    return {'projects': result}


def run_project_command(name: str, action: str, execute: bool = False, allow_shell: bool = False) -> dict:
    project = _find(name)
    if not project:
        return {'ok': False, 'error': f'project {name!r} not found'}
    path = project.get('path', '')
    if not isinstance(path, str) or not os.path.isdir(path):
        return {'ok': False, 'error': f'path missing: {path}'}
    command = _commands_of(project).get(action)
    if not command:
        return {'ok': False, 'error': f'action {action!r} not configured'}
    try:
        spec = parse_command(command)
        env_overrides = parse_environment(project.get('environment'))
        timeout = parse_timeout(project.get('timeouts'), action)
    except CommandConfigError as exc:
        return {'ok': False, 'error': f'invalid configuration: {exc}', 'command': command}
    report = {
        'ok': True,
        'cwd': path,
        'command': command,
        'notes': list(spec.notes),
        **spec.as_report(),
    }
    trusted_shell = allow_shell or _allow_shell_from_environment()
    if spec.requires_trusted_shell and not trusted_shell:
        report['requires_trusted_shell'] = True
        if not execute:
            # A dry run never executes anything; it only reports what would
            # have to be trusted in order to run.
            return {**report, 'ok': True, 'dry_run': True}
        return {
            **report,
            'ok': False,
            'dry_run': False,
            'error': (
                f'action {action!r} is configured as a shell command; '
                're-run with --allow-shell (or set WORKSTATION_ALLOW_SHELL=1) to trust it'
            ),
        }
    if not execute:
        return {**report, 'ok': True, 'dry_run': True}
    env = os.environ.copy()
    env.update(env_overrides)
    try:
        if spec.mode == 'shell':
            proc = subprocess.run(spec.shell, cwd=path, env=env, shell=True, text=True, capture_output=True, timeout=timeout)
        else:
            proc = subprocess.run(list(spec.argv), cwd=path, env=env, shell=False, text=True, capture_output=True, timeout=timeout)
        return {**report, 'ok': proc.returncode == 0, 'dry_run': False, 'exit_code': proc.returncode, 'output': (proc.stdout + proc.stderr)[-12000:]}
    except subprocess.TimeoutExpired:
        return {**report, 'ok': False, 'dry_run': False, 'error': 'command timed out'}
