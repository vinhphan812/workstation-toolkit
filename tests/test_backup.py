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


def test_backup_permissions_are_owner_only_on_posix(tmp_path, monkeypatch):
    import os
    import stat
    import workstation.core.backup as backup

    monkeypatch.setattr(backup, "BACKUPS_DIR", tmp_path / "backups")
    source = tmp_path / "secret.txt"
    source.write_text("sensitive")
    result = backup.backup_files("permissions", [str(source)])

    if os.name != "nt":
        backup_dir = Path(result["directory"])
        assert stat.S_IMODE(backup.BACKUPS_DIR.stat().st_mode) == 0o700
        assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(Path(result["files"][0]["backup"]).stat().st_mode) == 0o600
        assert stat.S_IMODE(Path(result["manifest"]).stat().st_mode) == 0o600


def test_backup_reports_the_permission_status_of_every_artifact(tmp_path, monkeypatch):
    import workstation.core.backup as backup

    monkeypatch.setattr(backup, "BACKUPS_DIR", tmp_path / "backups")
    source = tmp_path / "secret.txt"
    source.write_text("sensitive")
    result = backup.backup_files("reported", [str(source)])

    summary = result["permissions"]
    assert summary["platform"] in {"posix", "windows"}
    assert summary["enforced"] is True
    assert summary["status"] in {"enforced", "preserved"}
    # The root, the backup directory, the payload and the manifest.
    assert len(summary["results"]) == 4


def test_backup_manifest_records_the_permission_status(tmp_path, monkeypatch):
    import json
    import workstation.core.backup as backup

    monkeypatch.setattr(backup, "BACKUPS_DIR", tmp_path / "backups")
    source = tmp_path / "secret.txt"
    source.write_text("sensitive")
    result = backup.backup_files("manifest", [str(source)])

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["permissions"]["enforced"] is True
    assert manifest["permissions"]["platform"] in {"posix", "windows"}


def test_backup_manifest_covers_every_artifact_including_itself(tmp_path, monkeypatch):
    import json
    import workstation.core.backup as backup

    monkeypatch.setattr(backup, "BACKUPS_DIR", tmp_path / "backups")
    source = tmp_path / "secret.txt"
    source.write_text("sensitive")
    result = backup.backup_files("covered", [str(source)])

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    recorded = {entry["path"] for entry in manifest["permissions"]["results"]}
    # The root, the backup directory, the payload and the manifest itself.
    assert len(recorded) == 4
    assert str(Path(result["manifest"])) in recorded
    assert str(Path(result["files"][0]["backup"])) in recorded
    # The manifest and the returned report agree on the outcome.
    assert manifest["permissions"]["status"] == result["permissions"]["status"]
    assert manifest["permissions"]["enforced"] == result["permissions"]["enforced"]


def test_backup_removes_the_destination_when_the_manifest_cannot_be_restricted(tmp_path, monkeypatch):
    import workstation.core.backup as backup
    import workstation.core.permissions as permissions

    monkeypatch.setattr(backup, "BACKUPS_DIR", tmp_path / "backups")
    source = tmp_path / "secret.txt"
    source.write_text("sensitive")

    def boom(*_args, **_kwargs):
        return permissions.PermissionResult(
            permissions.STATUS_FAILED, permissions.platform_name(), "manifest",
            detail="simulated failure",
        )

    monkeypatch.setattr(backup.permissions, "write_private_text", boom)
    import pytest
    with pytest.raises(RuntimeError, match="could not be restricted"):
        backup.backup_files("manifest_failure", [str(source)])

    assert list((tmp_path / "backups").glob("*")) == []


def test_backup_aborts_and_removes_the_destination_when_a_payload_cannot_be_restricted(tmp_path, monkeypatch):
    import workstation.core.backup as backup
    import workstation.core.permissions as permissions

    monkeypatch.setattr(backup, "BACKUPS_DIR", tmp_path / "backups")
    source = tmp_path / "secret.txt"
    source.write_text("sensitive")

    def boom(*_args, **_kwargs):
        return permissions.PermissionResult(
            permissions.STATUS_FAILED, permissions.platform_name(), "payload",
            detail="chmod failed: simulated failure",
        )

    monkeypatch.setattr(backup, "_copy_private", boom)
    import pytest
    with pytest.raises(RuntimeError, match="could not be restricted"):
        backup.backup_files("failing", [str(source)])

    # The destination directory is removed, so no unprotected copy of the
    # payload is left behind.
    assert list((tmp_path / "backups").glob("*")) == []


def test_backup_reports_an_unsupported_platform_without_claiming_protection(tmp_path, monkeypatch):
    import shutil
    import workstation.core.backup as backup
    import workstation.core.permissions as permissions

    monkeypatch.setattr(backup, "BACKUPS_DIR", tmp_path / "backups")
    source = tmp_path / "secret.txt"
    source.write_text("sensitive")

    def unsupported(source_path, target_path):
        # The payload is copied, but the filesystem cannot express the
        # owner-only policy for it.
        shutil.copy2(source_path, target_path)
        return permissions.PermissionResult(
            permissions.STATUS_UNSUPPORTED, permissions.platform_name(), str(target_path),
            detail="this filesystem does not support POSIX permissions",
        )

    monkeypatch.setattr(backup, "_copy_private", unsupported)
    result = backup.backup_files("unsupported", [str(source)])

    summary = result["permissions"]
    assert summary["status"] == permissions.STATUS_UNSUPPORTED
    assert summary["enforced"] is False


def test_backup_restricts_the_backup_root_itself(tmp_path, monkeypatch):
    import os
    import stat
    import workstation.core.backup as backup

    monkeypatch.setattr(backup, "BACKUPS_DIR", tmp_path / "backups")
    source = tmp_path / "secret.txt"
    source.write_text("sensitive")
    backup.backup_files("root", [str(source)])

    if os.name != "nt":
        assert stat.S_IMODE(backup.BACKUPS_DIR.stat().st_mode) == 0o700


def test_backup_payload_is_not_readable_by_other_users(tmp_path, monkeypatch):
    import os
    import stat
    import workstation.core.backup as backup

    monkeypatch.setattr(backup, "BACKUPS_DIR", tmp_path / "backups")
    source = tmp_path / "secret.txt"
    source.write_text("sensitive")
    # The source itself is world readable; the copy must not inherit that.
    source.chmod(0o644)
    result = backup.backup_files("payload", [str(source)])

    if os.name != "nt":
        copied = Path(result["files"][0]["backup"])
        assert stat.S_IMODE(copied.stat().st_mode) == 0o600


def test_backup_does_not_widen_a_stricter_existing_backup_root(tmp_path, monkeypatch):
    import os
    import stat
    import workstation.core.backup as backup

    if os.name == "nt":
        return

    root = tmp_path / "backups"
    root.mkdir(mode=0o500)
    monkeypatch.setattr(backup, "BACKUPS_DIR", root)
    source = tmp_path / "secret.txt"
    source.write_text("sensitive")
    try:
        result = backup.backup_files("strict", [str(source)])
    except OSError:
        # A read-only root cannot receive the backup; that is reported by
        # the operating system, not silently worked around.
        return
    assert stat.S_IMODE(root.stat().st_mode) == 0o500
    assert Path(result["manifest"]).is_file()
