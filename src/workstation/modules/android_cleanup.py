"""Android SDK cleanup planner based on declared Gradle SDK requirements."""
from __future__ import annotations
import os, re
from pathlib import Path
from workstation.modules.development_audit import android_sdk_audit


def android_cleanup_plan(repos: list[str]) -> dict:
    audit = android_sdk_audit()
    if audit.get('status') != 'available':
        return {'status': 'unavailable', 'reason': audit.get('reason')}
    required_compile, required_build = set(), set()
    sources = []
    patterns = [(r'compileSdk(?:Version)?\s*[= ]\s*["\']?(\d+)', required_compile), (r'buildToolsVersion\s*[= ]\s*["\']([\d.]+)', required_build)]
    for repo in map(Path, repos):
        if not repo.is_dir(): continue
        # Bounded traversal: skip massive generated/dependency trees before
        # descending, then inspect Gradle build descriptors only.
        gradle_files = []
        for current, directory_names, file_names in os.walk(repo):
            directory_names[:] = [name for name in directory_names if name not in {'.gradle', 'build', 'node_modules', '.git', '.worktrees', '.venv'}]
            for filename in file_names:
                if filename.endswith(('.gradle', '.gradle.kts')):
                    gradle_files.append(Path(current) / filename)
        for gradle in gradle_files:
            try: text = gradle.read_text(encoding='utf-8', errors='ignore')
            except OSError: continue
            for pattern, bucket in patterns:
                for match in re.finditer(pattern, text):
                    bucket.add(match.group(1)); sources.append({'file': str(gradle), 'match': match.group(0)})
    installed_platforms = audit['platforms']
    installed_tools = audit['build_tools']
    keep_platforms = {f'android-{api}' for api in required_compile}
    # Conservatively retain the two newest installed tools plus explicit requirements.
    sorted_tools = sorted(installed_tools, key=lambda x: tuple(int(p) for p in re.findall(r'\d+', x['name'])))
    keep_tools = set(required_build) | {entry['name'] for entry in sorted_tools[-2:]}
    remove_platforms = [entry for entry in installed_platforms if entry['name'] not in keep_platforms]
    remove_tools = [entry for entry in installed_tools if entry['name'] not in keep_tools]
    return {'status': 'plan_only', 'sdk_root': audit['sdk_root'], 'requirements': {'compile_sdk': sorted(required_compile), 'build_tools': sorted(required_build), 'sources': sources}, 'keep': {'platforms': sorted(keep_platforms), 'build_tools': sorted(keep_tools)}, 'candidates': {'platforms': remove_platforms, 'build_tools': remove_tools}, 'safety': 'Candidates require manual review. Use sdkmanager/uninstall only after project builds pass.'}


def print_android_plan(plan: dict) -> None:
    print('\n=== Android SDK Cleanup Plan ===')
    if plan.get('status') != 'plan_only': print(plan); return
    print(f"SDK: {plan['sdk_root']}")
    print(f"Detected compileSdk: {plan['requirements']['compile_sdk'] or 'none'}")
    print('Candidates only — no deletion:')
    for kind, entries in plan['candidates'].items():
        print(f"  {kind}: {', '.join(e['name'] for e in entries) or 'none'}")
