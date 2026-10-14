from pathlib import Path
import workstation.modules.projects as projects

def test_project_command_defaults_to_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, 'load_projects', lambda: [{
        'name': 'demo', 'path': str(tmp_path), 'commands': {'test': 'exit 1'}, 'timeouts': {}
    }])
    report = projects.run_project_command('demo', 'test')
    assert report['ok'] is True
    assert report['dry_run'] is True
    assert report['command'] == 'exit 1'
