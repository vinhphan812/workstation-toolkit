"""Tests for the least-privilege backup permission policy.

The tests are platform aware: on POSIX they assert the resulting mode
bits, on Windows they assert the resulting DACL.  Both platforms assert
the same contract: no trustee other than the owner (plus SYSTEM and
Administrators on Windows) keeps access, and the owner keeps access.
"""
from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

import pytest

from workstation.core import permissions

posix_only = pytest.mark.skipif(os.name == 'nt', reason='POSIX mode bits')
windows_only = pytest.mark.skipif(os.name != 'nt', reason='Windows DACLs')


# --------------------------------------------------------------------------
# POSIX mode behaviour
# --------------------------------------------------------------------------


@posix_only
def test_created_directory_is_owner_only(tmp_path):
    target = tmp_path / 'private'
    result = permissions.create_directory(target)
    assert result.owner_only
    assert result.status == permissions.STATUS_ENFORCED
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


@posix_only
def test_enforce_directory_removes_group_and_other_access(tmp_path):
    target = tmp_path / 'loose'
    target.mkdir()
    target.chmod(0o755)
    result = permissions.enforce_directory(target)
    assert result.owner_only
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


@posix_only
def test_enforce_directory_preserves_a_stricter_owner_only_mode(tmp_path):
    target = tmp_path / 'strict'
    target.mkdir()
    target.chmod(0o500)
    result = permissions.enforce_directory(target)
    assert result.status == permissions.STATUS_PRESERVED
    # The stricter pre-existing mode is never widened.
    assert stat.S_IMODE(target.stat().st_mode) == 0o500


@posix_only
def test_enforce_file_removes_group_and_other_access(tmp_path):
    target = tmp_path / 'payload.txt'
    target.write_text('secret')
    target.chmod(0o644)
    result = permissions.enforce_file(target)
    assert result.owner_only
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@posix_only
def test_enforce_file_keeps_a_stricter_owner_only_mode(tmp_path):
    target = tmp_path / 'payload.txt'
    target.write_text('secret')
    target.chmod(0o400)
    result = permissions.enforce_file(target)
    assert result.status == permissions.STATUS_PRESERVED
    # Read-only stays read-only: the owner is not granted write access.
    assert stat.S_IMODE(target.stat().st_mode) == 0o400


@posix_only
def test_write_private_text_creates_the_file_owner_only(tmp_path):
    target = tmp_path / 'manifest.json'
    result = permissions.write_private_text(target, '{"a": 1}')
    assert result.owner_only
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_text() == '{"a": 1}'


@posix_only
def test_rewrite_private_text_keeps_the_file_owner_only(tmp_path):
    target = tmp_path / 'manifest.json'
    permissions.write_private_text(target, '{"a": 1}')
    target.chmod(0o400)
    permissions.rewrite_private_text(target, '{"a": 2}')
    assert stat.S_IMODE(target.stat().st_mode) == 0o400
    assert target.read_text() == '{"a": 2}'


@posix_only
def test_rewrite_private_text_reports_failure_to_restore_stricter_mode(tmp_path, monkeypatch):
    target = tmp_path / 'manifest.json'
    permissions.write_private_text(target, '{"a": 1}')
    target.chmod(0o400)
    real_chmod = os.chmod
    calls = 0

    def fail_restore(path, mode):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('restore denied')
        return real_chmod(path, mode)

    monkeypatch.setattr(permissions.os, 'chmod', fail_restore)
    result = permissions.rewrite_private_text(target, '{"a": 2}')
    assert result.status == permissions.STATUS_FAILED
    assert result.owner_only is False
    assert 'unable to restore original mode' in result.detail
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@posix_only
def test_rewrite_private_text_restores_the_mode_when_the_write_fails(tmp_path, monkeypatch):
    target = tmp_path / 'manifest.json'
    permissions.write_private_text(target, '{"a": 1}')
    target.chmod(0o400)

    def boom(*_args, **_kwargs):
        raise OSError('the write failed')

    monkeypatch.setattr(Path, 'write_text', boom)
    with pytest.raises(OSError):
        permissions.rewrite_private_text(target, '{"a": 2}')
    # The owner-only mode is restored even though the write failed, and the
    # file never becomes accessible to any other user.
    assert stat.S_IMODE(target.stat().st_mode) == 0o400


@posix_only
def test_write_private_text_survives_a_umask_that_removes_the_write_bit(tmp_path, monkeypatch):
    # A creation mode is masked by the umask.  The file must still be
    # writable for its owner afterwards.
    monkeypatch.setattr(permissions.os, 'umask', lambda _: 0o222)
    target = tmp_path / 'manifest.json'
    result = permissions.write_private_text(target, '{"a": 1}')
    assert result.owner_only
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    target.write_text('{"a": 2}')
    assert target.read_text() == '{"a": 2}'


@posix_only
def test_create_directory_restricts_the_ancestors_it_creates(tmp_path):
    # mkdir(parents=True) would create the intermediate directory with the
    # filesystem default, which other users could read.
    nested = tmp_path / 'wide' / 'nested'
    permissions.create_directory(nested)
    assert stat.S_IMODE((tmp_path / 'wide').stat().st_mode) == 0o700
    assert stat.S_IMODE(nested.stat().st_mode) == 0o700


@posix_only
def test_create_directory_does_not_widen_an_existing_ancestor(tmp_path):
    existing = tmp_path / 'existing'
    existing.mkdir()
    existing.chmod(0o755)
    permissions.create_directory(existing / 'child')
    assert stat.S_IMODE(existing.stat().st_mode) == 0o755


@posix_only
def test_a_failing_chmod_is_reported_and_never_claimed_as_enforced(tmp_path, monkeypatch):
    target = tmp_path / 'payload.txt'
    target.write_text('secret')
    target.chmod(0o644)

    def boom(*_args, **_kwargs):
        raise PermissionError('chmod is not permitted here')

    monkeypatch.setattr(permissions.os, 'chmod', boom)
    result = permissions.enforce_file(target)
    assert not result.owner_only
    assert result.status == permissions.STATUS_FAILED
    assert 'chmod failed' in result.detail


@posix_only
def test_an_unsupported_filesystem_is_reported_as_unsupported(tmp_path, monkeypatch):
    target = tmp_path / 'payload.txt'
    target.write_text('secret')
    target.chmod(0o644)

    def boom(*_args, **_kwargs):
        # The numeric value of ENOTSUP is platform specific (95 on Linux,
        # 45 on macOS), so the symbolic constant is used.
        raise OSError(errno.ENOTSUP, os.strerror(errno.ENOTSUP))

    monkeypatch.setattr(permissions.os, 'chmod', boom)
    result = permissions.enforce_file(target)
    assert result.unsupported
    assert not result.owner_only


@posix_only
def test_describe_reports_the_current_mode(tmp_path):
    target = tmp_path / 'payload.txt'
    target.write_text('secret')
    target.chmod(0o600)
    described = permissions.describe(target)
    assert described['platform'] == 'posix'
    assert described['mode'] == '0600'
    assert described['owner_only'] is True


# --------------------------------------------------------------------------
# Windows DACL behaviour
# --------------------------------------------------------------------------


@windows_only
def test_created_directory_excludes_other_trustees(tmp_path):
    target = tmp_path / 'private'
    result = permissions.create_directory(target)
    assert result.owner_only
    described = permissions.describe(target)
    owner = permissions._current_user_sid()
    allowed = {owner, permissions.WINDOWS_SYSTEM_SID,
               permissions.WINDOWS_ADMINISTRATORS_SID}
    foreign = [sid for sid in described['trustees'] if sid not in allowed]
    assert foreign == []
    assert described['owner_only'] is True


@windows_only
def test_created_directory_keeps_the_owner_in_access(tmp_path):
    target = tmp_path / 'private'
    permissions.create_directory(target)
    # The owner can still create and read a file inside the directory.
    inner = target / 'probe.txt'
    inner.write_text('ok')
    assert inner.read_text() == 'ok'


@windows_only
def test_created_file_is_owner_only(tmp_path):
    target = tmp_path / 'payload.txt'
    result = permissions.write_private_text(target, 'secret')
    assert result.owner_only
    assert permissions.describe(target)['owner_only'] is True


@windows_only
def test_enforcing_a_directory_does_not_lock_the_owner_out(tmp_path):
    target = tmp_path / 'loose'
    target.mkdir()
    result = permissions.enforce_directory(target)
    assert result.owner_only
    inner = target / 'probe.txt'
    inner.write_text('ok')
    assert inner.read_text() == 'ok'


@windows_only
def test_enforcing_a_directory_drops_a_foreign_trustee(tmp_path):
    target = tmp_path / 'loose'
    target.mkdir()
    # Grant Everyone access, then restrict the directory.
    assert permissions._run_icacls(target, ['/grant', '*S-1-1-0:(OI)(CI)(M)'])[0] == 0
    assert 'S-1-1-0' in permissions._dacl_sids(permissions._read_dacl(target))

    result = permissions.enforce_directory(target)
    assert result.owner_only
    trustees = permissions._dacl_sids(permissions._read_dacl(target))
    assert 'S-1-1-0' not in trustees
    allowed = {permissions._current_user_sid(), permissions.WINDOWS_SYSTEM_SID,
               permissions.WINDOWS_ADMINISTRATORS_SID}
    assert [sid for sid in trustees if sid not in allowed] == []


@windows_only
def test_a_failing_icacls_is_reported_and_never_claimed_as_enforced(tmp_path, monkeypatch):
    target = tmp_path / 'private'
    target.mkdir()

    def boom(*_args, **_kwargs):
        return 1, 'Access is denied'

    monkeypatch.setattr(permissions, '_run_icacls', boom)
    result = permissions.enforce_directory(target)
    assert not result.owner_only
    assert result.status == permissions.STATUS_FAILED


@windows_only
def test_unreadable_post_enforcement_dacl_is_a_failure(tmp_path, monkeypatch):
    target = tmp_path / 'private'
    target.mkdir()
    real_read = permissions._read_dacl
    calls = 0

    def unreadable_after_write(path):
        nonlocal calls
        calls += 1
        if calls >= 2:
            return None
        return real_read(path)

    monkeypatch.setattr(permissions, '_read_dacl', unreadable_after_write)
    result = permissions.enforce_directory(target)
    assert result.status == permissions.STATUS_FAILED
    assert result.unsupported is False
    assert not result.owner_only
    assert 'unable to verify' in result.detail


@windows_only
def test_a_missing_icacls_is_reported_as_unsupported(tmp_path, monkeypatch):
    target = tmp_path / 'private'
    target.mkdir()

    def boom(*_args, **_kwargs):
        return 127, 'icacls.exe is not available'

    monkeypatch.setattr(permissions, '_run_icacls', boom)
    result = permissions.enforce_directory(target)
    assert result.unsupported
    assert not result.owner_only


@windows_only
def test_describe_reports_the_dacl_trustees(tmp_path):
    target = tmp_path / 'private'
    permissions.create_directory(target)
    described = permissions.describe(target)
    assert described['platform'] == 'windows'
    assert described['trustees']
    assert described['owner_only'] is True


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def test_summarize_reports_the_weakest_outcome():
    ok = permissions.PermissionResult(permissions.STATUS_ENFORCED, 'posix', '/a')
    unsupported = permissions.PermissionResult(permissions.STATUS_UNSUPPORTED, 'posix', '/b')
    failed = permissions.PermissionResult(permissions.STATUS_FAILED, 'posix', '/c')

    assert permissions.summarize([ok, ok])['status'] == permissions.STATUS_ENFORCED
    assert permissions.summarize([ok, ok])['enforced'] is True
    assert permissions.summarize([ok, unsupported])['status'] == permissions.STATUS_UNSUPPORTED
    assert permissions.summarize([ok, unsupported])['enforced'] is False
    assert permissions.summarize([ok, failed])['status'] == permissions.STATUS_FAILED
    assert permissions.summarize([ok, failed])['enforced'] is False


def test_summarize_of_an_empty_result_set_is_enforced():
    assert permissions.summarize([])['status'] == permissions.STATUS_ENFORCED
    assert permissions.summarize([])['enforced'] is True


def test_permission_result_serialises_to_a_dict():
    result = permissions.PermissionResult(
        permissions.STATUS_ENFORCED, 'posix', '/tmp/x', mode=0o600,
    )
    payload = result.as_dict()
    assert payload['status'] == permissions.STATUS_ENFORCED
    assert payload['mode'] == '0600'
    assert payload['owner_only'] is True
