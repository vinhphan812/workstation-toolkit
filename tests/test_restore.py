import json
from pathlib import Path
import pytest
import workstation.modules.maintenance as maintenance
from workstation.core.backup import _sha256

def test_restore_skips_checksum_mismatch(tmp_path):
    target = tmp_path / 'target.txt'
    backup = tmp_path / 'backup.txt'
    backup.write_text('changed')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'files': [{'source': str(target), 'backup': str(backup), 'status':'backed_up', 'sha256': '0' * 64}]}))
    result = maintenance.restore_backup(str(manifest), execute=True, yes=True)
    assert not result['restored']
    assert result['skipped'][0]['reason'] == 'checksum mismatch'


def _manifest(tmp_path, entries):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'files': entries}))
    return manifest


@pytest.mark.parametrize('digest', [None, '', 'not-a-digest', 'a' * 63, 'g' * 64])
def test_restore_rejects_missing_or_invalid_checksum_before_mutation(tmp_path, digest):
    target = tmp_path / 'target.txt'
    target.write_text('original-good-data')
    backup = tmp_path / 'backup.txt'
    backup.write_text('backup-payload')
    entry = {'source': str(target), 'backup': str(backup), 'status': 'backed_up'}
    if digest is not None:
        entry['sha256'] = digest

    result = maintenance.restore_backup(str(_manifest(tmp_path, [entry])), execute=True, yes=True)

    assert result['ok'] is True
    assert result['restored'] == []
    assert result['skipped'][0]['reason'] == 'invalid or missing sha256'
    assert target.read_text() == 'original-good-data'
    assert backup.read_text() == 'backup-payload'


def test_restore_reports_post_copy_checksum_mismatch_as_failure(tmp_path, monkeypatch):
    """Corrupted staged bytes fail and remain available as recovery evidence."""
    target = tmp_path / 'target.txt'
    target.write_bytes(b'original-good-data')
    backup = tmp_path / 'backup.txt'
    backup.write_bytes(b'backup-payload')
    expected = _sha256(backup)
    manifest = _manifest(tmp_path, [{
        'source': str(target), 'backup': str(backup),
        'status': 'backed_up', 'sha256': expected,
    }])

    real_copy2 = maintenance.shutil.copy2

    def corrupt_staged_copy(source, destination, *args, **kwargs):
        result = real_copy2(source, destination, *args, **kwargs)
        Path(destination).write_bytes(b'corrupted-staged-bytes')
        return result

    monkeypatch.setattr(maintenance.shutil, 'copy2', corrupt_staged_copy)
    result = maintenance.restore_backup(str(manifest), execute=True, yes=True)

    assert result['ok'] is False
    assert not result['restored']
    assert len(result['failed']) == 1
    failure = result['failed'][0]
    assert failure['reason'] == 'post-copy checksum mismatch'
    assert failure['expected_sha256'] == expected
    assert failure['actual_sha256'] == _sha256(Path(failure['evidence_copy']))
    assert target.read_bytes() == b'original-good-data'
    assert backup.read_bytes() == b'backup-payload'
    assert Path(failure['evidence_copy']).read_bytes() == b'corrupted-staged-bytes'


def test_restore_successful_restores_file(tmp_path):
    target = tmp_path / 'state.db'
    target.write_text('stale')
    backup = tmp_path / 'backup.bin'
    backup.write_bytes(b'fresh-payload')
    manifest = _manifest(tmp_path, [{
        'source': str(target), 'backup': str(backup),
        'status': 'backed_up', 'sha256': _sha256(backup),
    }])

    result = maintenance.restore_backup(str(manifest), execute=True, yes=True)

    assert result['ok'] is True
    assert result['restored'] == [str(target)]
    assert result['failed'] == []
    assert target.read_bytes() == b'fresh-payload'
    # No staging or evidence leftovers on the happy path.
    assert list(tmp_path.glob('*.restore-staging')) == []
    assert list(tmp_path.glob('*.restore-mismatch.bin')) == []
