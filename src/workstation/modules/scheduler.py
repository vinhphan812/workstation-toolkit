"""Opt-in health-report scheduling with platform-specific command generation."""
from __future__ import annotations
import platform, subprocess, sys
from pathlib import Path
from workstation.config import TOOLKIT_ROOT
from workstation.core.safety import require_execute

def schedule_plan(hour: int = 9) -> dict:
    command = f'"{sys.executable}" -m workstation --save-report diagnose'
    system = platform.system().lower()
    if system == 'windows':
        return {'platform': system, 'name': 'WorkstationToolkitDailyHealth', 'command': command, 'create_command': ['schtasks', '/Create', '/TN', 'WorkstationToolkitDailyHealth', '/SC', 'DAILY', '/ST', f'{hour:02}:00', '/TR', command, '/F']}
    if system == 'linux':
        return {'platform': system, 'command': command, 'cron': f'0 {hour} * * * cd {TOOLKIT_ROOT} && {command}'}
    if system == 'darwin':
        return {'platform': system, 'command': command, 'note': 'Create a LaunchAgent plist using this command.'}
    return {'platform': system, 'status': 'unsupported'}

def create_schedule(hour: int, execute: bool = False, yes: bool = False) -> dict:
    plan = schedule_plan(hour)
    if plan.get('platform') != 'windows': return {**plan, 'created': False}
    require_execute(execute, yes, 'schedule creation')
    result = subprocess.run(plan['create_command'], capture_output=True, text=True, timeout=30)
    return {**plan, 'created': result.returncode == 0, 'output': result.stdout + result.stderr}
