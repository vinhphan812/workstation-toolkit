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


def test_backup_rejects_duplicate_basenames_before_copying(tmp_path, monkeypatch):
    import pytest
    import workstation.core.backup as backup
    monkeypatch.setattr(backup, 'BACKUPS_DIR', tmp_path / 'backups')
    left = tmp_path / 'left' / 'same.txt'
    right = tmp_path / 'right' / 'same.txt'
    left.parent.mkdir(); right.parent.mkdir()
    left.write_bytes(b'left bytes'); right.write_bytes(b'right bytes')
    with pytest.raises(ValueError, match='basename collision'):
        backup.backup_files('collision', [str(left), str(right)])
    assert not list((tmp_path / 'backups').glob('*'))
