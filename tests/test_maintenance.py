from pathlib import Path
import workstation.modules.maintenance as module

def test_maintenance_is_dry_run_by_default(tmp_path, monkeypatch):
    db = tmp_path / 'state.db'; db.write_bytes(b'x')
    monkeypatch.setattr(module, 'get_hermes_profile', lambda: str(tmp_path))
    report = module.hermes_db_maintenance()
    assert report['ok'] is True
    assert report['dry_run'] is True
