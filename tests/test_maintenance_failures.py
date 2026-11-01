import sqlite3

import pytest
import workstation.modules.maintenance as module


@pytest.mark.parametrize(('check', 'checkpoint', 'optimizer', 'post', 'stage'), [
    ('corrupt', [0, 0, 0], 0, 'ok', 'quick_check_before'),
    ('ok', [1, 0, 0], 0, 'ok', 'checkpoint'),
    ('ok', [0, 0, 0], 4, 'ok', 'optimize_exit'),
    ('ok', [0, 0, 0], 0, 'corrupt', 'quick_check_after'),
])
def test_required_stage_failures(tmp_path, monkeypatch, check, checkpoint, optimizer, post, stage):
    db = tmp_path / 'state.db'
    db.write_bytes(b'db')
    monkeypatch.setattr(module, 'get_hermes_profile', lambda: str(tmp_path))
    monkeypatch.setattr(module, 'require_free_space', lambda *_: 20)
    monkeypatch.setattr(module, 'backup_files', lambda *_: {})

    class Connection:
        def __init__(self, *_args, **_kwargs): self.reads = 0
        def execute(self, _sql): return self
        def fetchone(self):
            self.reads += 1
            return (check,) if self.reads == 1 else tuple(checkpoint)
        def close(self): pass
    class ReadOnly:
        def execute(self, _sql): return self
        def fetchone(self): return (post,)
        def close(self): pass
    connections = iter([Connection(), ReadOnly()])
    monkeypatch.setattr(module.sqlite3, 'connect', lambda *_args, **_kwargs: next(connections))
    class Process:
        returncode = optimizer
        stdout = stderr = ''
    monkeypatch.setattr(module.subprocess, 'run', lambda *_args, **_kwargs: Process())
    report = module.hermes_db_maintenance(execute=True, yes=True)
    assert report['ok'] is False
    assert any(item['stage'] == stage for item in report['failures'])


def test_successful_maintenance_reports_all_clear(tmp_path, monkeypatch):
    db = tmp_path / 'state.db'; db.write_bytes(b'db')
    monkeypatch.setattr(module, 'get_hermes_profile', lambda: str(tmp_path))
    monkeypatch.setattr(module, 'require_free_space', lambda *_: 20)
    monkeypatch.setattr(module, 'backup_files', lambda *_: {})
    class Connection:
        def __init__(self, *_args, **_kwargs): self.reads = 0
        def execute(self, _sql): return self
        def fetchone(self): self.reads += 1; return ('ok',) if self.reads == 1 else (0, 0, 0)
        def close(self): pass
    monkeypatch.setattr(module.sqlite3, 'connect', lambda *_args, **_kwargs: Connection())
    class Process:
        returncode = 0
        stdout = stderr = ''
    monkeypatch.setattr(module.subprocess, 'run', lambda *_args, **_kwargs: Process())
    report = module.hermes_db_maintenance(execute=True, yes=True)
    assert report['ok'] is True
    assert report['failures'] == []
