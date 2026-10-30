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
    manifest.write_text(json.dumps({'files': [{'source': str(target), 'backup': str(backup), 'status':'backed_up', 'sha256': 'wrong'}]}))
    result = maintenance.restore_backup(str(manifest), execute=True, yes=True)
    assert not result['restored']
    assert result['skipped'][0]['reason'] == 'checksum mismatch'


def _manifest(tmp_path, entries):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'files': entries}))
    return manifest


def test_restore_reports_post_copy_checksum_mismatch_as_failure(tmp_path, monkeypatch):
    """A copy that changes in flight must fail, not be reported as success."""
    target = tmp_path / 'target.txt'
    target.write_text('original-good-data')
    backup = tmp_path / 'backup.txt'
    backup.write_text('backup-payload')
    expected = _sha256(backup)
    manifest = _manifest(tmp_path, [{
        'source': str(target), 'backup': str(backup),
        'status': 'backed_up', 'sha256': expected,
    }])

    real_sha256 = maintenance._sha256
    calls = {'n': 0}

    def flaky_sha256(path):
        calls['n'] += 1
        # 1st call = pre-copy verification of the backup (matches manifest),
        # 2nd call = post-copy verification, where the copy got corrupted.
        if calls['n'] == 1:
            return real_sha256(path)
        return 'f' * 64

    monkeypatch.setattr(maintenance, '_sha256', flaky_sha256)
    result = maintenance.restore_backup(str(manifest), execute=True, yes=True)

    assert result['ok'] is False
    assert not result['restored']
    assert len(result['failed']) == 1
    failure = result['failed'][0]
    assert failure['reason'] == 'post-copy checksum mismatch'
    assert failure['expected_sha256'] == expected
    assert failure['actual_sha256'] == 'f' * 64

    # Recovery data preserved: destination untouched, backup still present.
    assert target.read_text() == 'original-good-data'
    assert backup.is_file()
    assert Path(failure['evidence_copy']).is_file()
    assert Path(failure['evidence_copy']).read_text() == 'backup-payload'


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
