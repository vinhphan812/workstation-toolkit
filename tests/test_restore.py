import hashlib
import json
from pathlib import Path
import pytest
import workstation.modules.maintenance as maintenance
from workstation.core.backup import _sha256

def _write_manifest(path, entries):
    path.write_text(json.dumps({'created_at': 'now', 'label': 'test', 'files': entries}))
    return path


def test_restore_skips_checksum_mismatch(tmp_path):
    target = tmp_path / 'target.txt'
    target.write_text('original destination')
    backup = tmp_path / 'backup.txt'
    backup.write_text('changed')
    manifest = _write_manifest(tmp_path / 'manifest.json', [{'source': str(target), 'backup': str(backup), 'status':'backed_up', 'sha256': '0' * 64}])
    result = maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(tmp_path)])
    assert not result['restored']
    assert result['ok'] is False
    mismatch = result['failed'][0]
    assert mismatch['reason'] == 'checksum mismatch'
    assert mismatch['expected_sha256'] == '0' * 64
    assert mismatch['actual_sha256'] == hashlib.sha256(b'changed').hexdigest()
    assert mismatch['evidence_path'] == str(backup)
    assert mismatch['source_preserved'] is True
    assert mismatch['backup_preserved'] is True
    assert target.read_text() == 'original destination'
    assert backup.read_bytes() == b'changed'


@pytest.mark.parametrize('sha', [None, '0' * 63, 'z' * 64])
def test_restore_rejects_missing_null_or_malformed_hash_before_mutation(tmp_path, sha):
    target = tmp_path / 'target.txt'
    target.write_text('original')
    backup = tmp_path / 'backup.txt'
    backup.write_text('backup')
    entry = {'source': str(target), 'backup': str(backup), 'status': 'backed_up'}
    if sha is not None:
        entry['sha256'] = sha
    manifest = _write_manifest(tmp_path / 'manifest.json', [entry])
    with pytest.raises(ValueError, match='invalid sha256'):
        maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(tmp_path)])
    assert target.read_text() == 'original'
    assert backup.read_text() == 'backup'


def test_cmd_restore_exits_nonzero_when_restore_report_fails(monkeypatch, capsys):
    import argparse
    import workstation.cli as cli
    import workstation.modules.maintenance as maintenance_module
    monkeypatch.setattr(maintenance_module, 'restore_backup', lambda manifest_path, **kwargs: {'ok': False, 'restored': [], 'skipped': [], 'failed': [{'reason': 'checksum mismatch'}]})
    args = argparse.Namespace(manifest='manifest.json', execute=True, yes=True, allowed_root=['D:/allowed'], json=False, save_report=None)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_restore(args)
    assert exc.value.code == 1
    assert 'checksum mismatch' in capsys.readouterr().out


def test_restore_preserves_corrupt_stage_evidence_and_destination(tmp_path, monkeypatch):
    import os
    target = tmp_path / 'target.txt'
    target.write_text('original')
    backup = tmp_path / 'backup.txt'
    backup.write_text('trusted backup')
    manifest = _write_manifest(tmp_path / 'manifest.json', [{
        'source': str(target), 'backup': str(backup), 'status': 'backed_up',
        'sha256': _sha256(backup),
    }])
    real_hash_staged = maintenance._hash_staged_file
    def corrupt_before_hash(name, parent_fd):
        if parent_fd is None:
            Path(name).write_bytes(b'corrupted staged bytes')
        else:
            fd = os.open(name, os.O_WRONLY | os.O_TRUNC, dir_fd=parent_fd)
            with os.fdopen(fd, 'wb') as staged:
                staged.write(b'corrupted staged bytes')
        return real_hash_staged(name, parent_fd)
    monkeypatch.setattr(maintenance, '_hash_staged_file', corrupt_before_hash)
    report = maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(tmp_path)])
    assert not report['restored']
    mismatch = report['failed'][0]
    assert report['ok'] is False
    assert mismatch['reason'] == 'post-copy checksum mismatch'
    assert mismatch['expected_sha256'] == _sha256(backup)
    evidence = Path(mismatch['evidence_path'])
    assert mismatch['actual_sha256'] == _sha256(evidence)
    assert mismatch['source_preserved'] is True
    assert mismatch['backup_preserved'] is True
    assert evidence.is_file() and evidence.read_bytes() == b'corrupted staged bytes'
    assert target.read_text() == 'original'
    assert backup.read_text() == 'trusted backup'


def test_restore_requires_allowed_root_without_mutation(tmp_path):
    target = tmp_path / 'new' / 'target.txt'
    root = tmp_path / 'backup'
    root.mkdir()
    payload = root / 'payload'
    payload.write_text('payload')
    manifest = _write_manifest(root / 'manifest.json', [{'source': str(target), 'backup': str(payload), 'status': 'backed_up'}])
    with pytest.raises(ValueError, match='requires at least one'):
        maintenance.restore_backup(str(manifest), execute=True, yes=True)
    assert not target.parent.exists()


def test_restore_rejects_disallowed_destination_before_mutation(tmp_path):
    allowed = tmp_path / 'allowed'
    allowed.mkdir()
    outside = tmp_path / 'outside' / 'victim.txt'
    backup_root = tmp_path / 'backup'
    backup_root.mkdir()
    payload = backup_root / 'payload'
    payload.write_text('attacker payload')
    manifest = _write_manifest(backup_root / 'manifest.json', [{'source': str(outside), 'backup': str(payload), 'status': 'backed_up'}])
    with pytest.raises(ValueError, match='outside allowed roots'):
        maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(allowed)])
    assert not outside.parent.exists()


def test_restore_validates_missing_entry_source_policy(tmp_path):
    root = tmp_path / 'allowed'
    root.mkdir()
    manifest = _write_manifest(tmp_path / 'manifest.json', [{'source': 'relative.txt', 'status': 'missing'}])
    with pytest.raises(ValueError, match='source must be absolute'):
        maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(root)])


def test_restore_requires_explicit_execution_before_manifest_read(tmp_path):
    with pytest.raises(RuntimeError):
        maintenance.restore_backup(str(tmp_path / 'absent.json'))


def test_restore_rejects_invalid_schema_without_mutating_target(tmp_path):
    target = tmp_path / 'target.txt'
    target.write_text('original')
    manifest = _write_manifest(tmp_path / 'manifest.json', ['not an entry'])
    with pytest.raises(ValueError, match='expected object'):
        maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(tmp_path)])
    assert target.read_text() == 'original'


def test_restore_rejects_traversal_backup_path(tmp_path):
    outside = tmp_path / 'outside.txt'
    outside.write_text('attacker data')
    target = tmp_path / 'target.txt'
    target.write_text('original')
    root = tmp_path / 'backups'
    root.mkdir()
    manifest = _write_manifest(root / 'manifest.json', [{'source': str(target), 'backup': '../outside.txt', 'status': 'backed_up'}])
    with pytest.raises(ValueError, match='escapes manifest directory'):
        maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(tmp_path)])
    assert target.read_text() == 'original'


def test_restore_rejects_backup_symlink_escape(tmp_path):
    outside = tmp_path / 'outside.txt'
    outside.write_text('outside content')
    target = tmp_path / 'target.txt'
    target.write_text('original')
    root = tmp_path / 'backups'
    root.mkdir()
    link = root / 'linked.txt'
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks are unavailable')
    manifest = _write_manifest(root / 'manifest.json', [{'source': str(target), 'backup': str(link), 'status': 'backed_up'}])
    with pytest.raises(ValueError, match='escapes manifest directory'):
        maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(tmp_path)])
    assert target.read_text() == 'original'


def test_restore_rejects_non_absolute_destination(tmp_path):
    root = tmp_path / 'backups'
    root.mkdir()
    backup = root / 'payload'
    backup.write_text('payload')
    manifest = _write_manifest(root / 'manifest.json', [{'source': '../victim', 'backup': str(backup), 'status': 'backed_up'}])
    with pytest.raises(ValueError, match='source must be absolute'):
        maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(tmp_path)])


def test_restore_refuses_parent_symlink_swap_before_replace(tmp_path, monkeypatch):
    root = tmp_path / 'allowed'
    parent = root / 'nested'
    root.mkdir()
    parent.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = parent / 'victim.txt'
    target.write_text('original')
    payload = tmp_path / 'payload'
    payload.write_text('new bytes')
    manifest = _write_manifest(tmp_path / 'manifest.json', [{
        'source': str(target), 'backup': str(payload), 'status': 'backed_up',
        'sha256': hashlib.sha256(b'new bytes').hexdigest(),
    }])
    real_open_parent = maintenance._open_destination_parent
    def swap_then_open(source, roots):
        parent.rename(root / 'moved')
        try:
            parent.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip('directory symlinks unavailable')
        return real_open_parent(source, roots)
    monkeypatch.setattr(maintenance, '_open_destination_parent', swap_then_open)
    report = maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(root)])
    assert not report['restored']
    assert report['failed'][0]['reason'].startswith('destination parent unavailable:')
    assert not (outside / 'victim.txt').exists()
    assert (root / 'moved' / 'victim.txt').read_text() == 'original'


def test_restore_accepts_backup_files_manifest(tmp_path, monkeypatch):
    import workstation.core.backup as backup_module
    monkeypatch.setattr(backup_module, 'BACKUPS_DIR', tmp_path / 'backups')
    source = tmp_path / 'source.db'
    source.write_text('backup data')
    created = backup_module.backup_files('compat', [str(source)])
    source.write_text('changed')
    report = maintenance.restore_backup(created['manifest'], execute=True, yes=True, allowed_roots=[str(tmp_path)])
    assert report['restored'] == [str(source)]
    assert source.read_text() == 'backup data'
