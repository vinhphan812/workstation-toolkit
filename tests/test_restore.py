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
