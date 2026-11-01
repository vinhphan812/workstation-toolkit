from pathlib import Path
import hashlib
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


def test_backup_gives_same_named_sources_distinct_payloads(tmp_path, monkeypatch):
    import json
    import workstation.core.backup as backup
    monkeypatch.setattr(backup, 'BACKUPS_DIR', tmp_path / 'backups')
    left = tmp_path / 'left' / 'same.txt'
    right = tmp_path / 'right' / 'same.txt'
    left.parent.mkdir(); right.parent.mkdir()
    left.write_bytes(b'left bytes'); right.write_bytes(b'right bytes')
    result = backup.backup_files('collision', [str(left), str(right)])
    entries = result['files']
    assert len(entries) == 2
    payloads = [Path(entry['backup']) for entry in entries]
    assert len({str(payload) for payload in payloads}) == 2
    assert payloads[0].read_bytes() == b'left bytes'
    assert payloads[1].read_bytes() == b'right bytes'
    for entry, source in zip(entries, (left, right)):
        payload = Path(entry['backup'])
        assert entry['sha256'] == hashlib.sha256(payload.read_bytes()).hexdigest()
        assert entry['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
    assert [entry['backup'] for entry in manifest['files']] == [str(payload) for payload in payloads]


def test_backup_payload_names_avoid_case_insensitive_collisions(tmp_path, monkeypatch):
    import workstation.core.backup as backup
    monkeypatch.setattr(backup, 'BACKUPS_DIR', tmp_path / 'backups')
    upper = tmp_path / 'upper' / 'Same.txt'
    lower = tmp_path / 'lower' / 'same.txt'
    upper.parent.mkdir(); lower.parent.mkdir()
    upper.write_bytes(b'upper bytes'); lower.write_bytes(b'lower bytes')
    result = backup.backup_files('case', [str(upper), str(lower)])
    payloads = [Path(entry['backup']) for entry in result['files']]
    assert len({payload.name.casefold() for payload in payloads}) == 2
    assert sorted(payload.read_bytes() for payload in payloads) == [b'lower bytes', b'upper bytes']


def test_backup_payload_variant_never_shadows_another_source_name(tmp_path, monkeypatch):
    import workstation.core.backup as backup
    monkeypatch.setattr(backup, 'BACKUPS_DIR', tmp_path / 'backups')
    first = tmp_path / 'a' / 'same.txt'
    second = tmp_path / 'b' / 'same.txt'
    third = tmp_path / 'c' / 'same~1.txt'
    for path in (first, second, third):
        path.parent.mkdir()
    first.write_bytes(b'first'); second.write_bytes(b'second'); third.write_bytes(b'third')
    result = backup.backup_files('variant', [str(first), str(second), str(third)])
    payloads = [Path(entry['backup']) for entry in result['files']]
    assert len({payload.name.casefold() for payload in payloads}) == 3
    assert sorted(payload.read_bytes() for payload in payloads) == [b'first', b'second', b'third']


def test_backup_keeps_unique_payload_name_unchanged(tmp_path, monkeypatch):
    import workstation.core.backup as backup
    monkeypatch.setattr(backup, 'BACKUPS_DIR', tmp_path / 'backups')
    source = tmp_path / 'state.db'
    source.write_bytes(b'state')
    result = backup.backup_files('single', [str(source)])
    assert Path(result['files'][0]['backup']).name == 'state.db'


def test_backup_payload_never_overwrites_the_manifest(tmp_path, monkeypatch):
    import json
    import workstation.core.backup as backup
    monkeypatch.setattr(backup, 'BACKUPS_DIR', tmp_path / 'backups')
    source = tmp_path / 'manifest.json'
    source.write_bytes(b'payload bytes')
    result = backup.backup_files('named', [str(source)])
    payload = Path(result['files'][0]['backup'])
    assert payload.name != 'manifest.json'
    assert payload.read_bytes() == b'payload bytes'
    assert json.loads(Path(result['manifest']).read_text(encoding='utf-8'))['files'][0]['backup'] == str(payload)
