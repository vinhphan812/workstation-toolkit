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
    backup = tmp_path / 'backup.txt'
    backup.write_text('changed')
    manifest = _write_manifest(tmp_path / 'manifest.json', [{'source': str(target), 'backup': str(backup), 'status':'backed_up', 'sha256': '0' * 64}])
    result = maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(tmp_path)])
    assert not result['restored']
    assert result['skipped'][0]['reason'] == 'checksum mismatch'


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


def test_restore_preserves_corrupt_stage_evidence_and_destination(tmp_path, monkeypatch):
    import builtins
    target = tmp_path / 'target.txt'
    target.write_text('original')
    backup = tmp_path / 'backup.txt'
    backup.write_text('trusted backup')
    manifest = _write_manifest(tmp_path / 'manifest.json', [{
        'source': str(target), 'backup': str(backup), 'status': 'backed_up',
        'sha256': _sha256(backup),
    }])
    real_open = builtins.open
    corrupted = False
    def corrupt_stage_on_reread(file, mode='r', *args, **kwargs):
        nonlocal corrupted
        if not corrupted and isinstance(file, (str, Path)) and '.restore-' in str(file) and mode == 'rb':
            corrupted = True
            Path(file).write_bytes(b'corrupted staged bytes')
        return real_open(file, mode, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', corrupt_stage_on_reread)
    report = maintenance.restore_backup(str(manifest), execute=True, yes=True, allowed_roots=[str(tmp_path)])
    assert not report['restored']
    mismatch = report['skipped'][0]
    assert mismatch['reason'] == 'post-copy checksum mismatch'
    evidence = Path(mismatch['evidence_path'])
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
