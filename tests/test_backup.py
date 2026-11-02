from pathlib import Path
from workstation.core.backup import backup_files

def test_backup_files_copies_and_manifests(tmp_path, monkeypatch):
    import workstation.core.backup as backup
    monkeypatch.setattr(backup, 'BACKUPS_DIR', tmp_path / 'backups')
    original = tmp_path / 'original.txt'
    original.write_text('safe data')
    result = backup_files('unit', [str(original)])
    copied = Path(result['files'][0]['backup'])
    assert copied.read_text() == 'safe data'
    assert Path(result['manifest']).is_file()


def test_backup_preflight_blocks_before_creating_destination(tmp_path, monkeypatch):
    import workstation.core.backup as backup
    monkeypatch.setattr(backup, 'BACKUPS_DIR', tmp_path / 'backups')
    source = tmp_path / 'source.bin'
    source.write_bytes(b'x' * 1024)
    monkeypatch.setattr(backup, '_available_bytes', lambda _: 0)
    import pytest
    with pytest.raises(RuntimeError, match='Insufficient backup space'):
        backup.backup_files('blocked', [str(source)])
    assert list((tmp_path / 'backups').glob('*')) == []


def test_backup_manifest_version_and_read_only_verify(tmp_path, monkeypatch):
    import json
    import workstation.core.backup as backup
    monkeypatch.setattr(backup, 'BACKUPS_DIR', tmp_path / 'backups')
    source = tmp_path / 'source.bin'; source.write_bytes(b'large' * 200000)
    result = backup.backup_files('versioned', [str(source)])
    manifest = json.loads(Path(result['manifest']).read_text())
    assert manifest['version'] == backup.MANIFEST_VERSION
    payload = Path(manifest['files'][0]['backup'])
    before = payload.stat().st_mtime_ns
    assert backup.verify_backup(result['manifest'])['ok']
    assert payload.stat().st_mtime_ns == before
    payload.write_bytes(b'corrupt')
    report = backup.verify_backup(result['manifest'])
    assert not report['ok'] and report['failed'][0]['reason'] == 'checksum mismatch'


def test_verify_accepts_legacy_manifest_and_reports_missing(tmp_path):
    import json
    from workstation.core.backup import verify_backup
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'files': [{'source': '/gone', 'status': 'missing'}]}))
    report = verify_backup(str(manifest))
    assert not report['ok'] and report['failed'][0]['reason'] == 'source missing at backup time'


def test_manifest_rejects_unsupported_version(tmp_path):
    import json
    from workstation.core.backup import verify_backup
    manifest = tmp_path / 'manifest.json'; manifest.write_text(json.dumps({'version': 99, 'files': []}))
    import pytest
    with pytest.raises(ValueError, match='Unsupported backup manifest version'):
        verify_backup(str(manifest))
