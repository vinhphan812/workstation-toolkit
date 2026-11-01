"""Least-privilege permissions for backup artifacts.

Backups can contain sensitive configuration and SQLite state, so the
artifacts this toolkit creates are restricted to their owner:

* POSIX directories are ``0o700`` and files are ``0o600``.
* Windows DACLs are reduced to the creating account, the owner recorded in
  the security descriptor, ``SYSTEM`` and ``Administrators``.

Four rules shape this module.

**Never broaden access.**  A file that already carries a stricter
owner-only mode keeps it; group and other bits are removed and nothing is
added back.  A directory that is already owner-only keeps its exact mode.
On Windows the owner recorded in the descriptor is never revoked,
``SYSTEM`` and ``Administrators`` are kept only when the descriptor already
granted them access, and every other trustee is dropped.

**Never claim protection that was not verified.**  Every enforcement
attempt re-reads the resulting permissions and compares them against the
policy.  When a filesystem or platform cannot express the policy -- FAT or
exFAT volumes, some network shares, a missing ``icacls`` -- the result is
reported as ``unsupported`` instead of being reported as enforced, and an
unexpected error is reported as ``failed``.

**Never break the owner's own access.**  On Windows the owner is granted
access *before* inheritance is removed.  Stripping inherited entries from
a descriptor that only carried inherited entries would otherwise leave the
owner locked out of its own backup.  On POSIX the artifacts are created
with an owner-only mode from the first instant they exist, so a failing
``chmod`` can never leave a readable file behind.

**Prefer explicit over inherited.**  On Windows the resulting DACL is
written as explicit access for the allowed trustees, so it does not change
when the parent directory's permissions change later.
"""
from __future__ import annotations

import errno
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

DIRECTORY_MODE = 0o700
FILE_MODE = 0o600

STATUS_ENFORCED = 'enforced'
STATUS_PRESERVED = 'preserved'
STATUS_UNSUPPORTED = 'unsupported'
STATUS_FAILED = 'failed'

WINDOWS_SYSTEM_SID = 'S-1-5-18'
WINDOWS_ADMINISTRATORS_SID = 'S-1-5-32-544'

# SDDL aliases mapped to the numeric SID they stand for.  The numeric form
# is used for comparisons because account names are locale dependent.
_ALIAS_SIDS = {
    'AN': 'S-1-5-7',        # ANONYMOUS LOGON
    'AU': 'S-1-5-11',       # Authenticated Users
    'BA': 'S-1-5-32-544',   # BUILTIN\Administrators
    'BG': 'S-1-5-32-546',   # BUILTIN\Guests
    'BU': 'S-1-5-32-545',   # BUILTIN\Users
    'CO': 'S-1-3-0',        # Creator Owner
    'IU': 'S-1-5-4',        # Interactive Users
    'LS': 'S-1-5-19',       # Local Service
    'NS': 'S-1-5-20',       # Network Service
    'NU': 'S-1-5-7',        # Network
    'OW': 'S-1-3-4',        # OWNER RIGHTS
    'SY': 'S-1-5-18',       # NT AUTHORITY\SYSTEM
    'WD': 'S-1-1-0',        # Everyone
}

# FILE_ALL_ACCESS as reported by icacls when a trustee holds full control.
_FULL_ACCESS = {'FA', 'GA', '0X1F01FF', '0x1f01ff'}

# icacls output that means the filesystem cannot express the policy at all
# rather than the operation having failed.  "Access is denied" is
# deliberately not in this list: it means the descriptor could not be
# changed, which is a failure rather than a missing capability.
_UNSUPPORTED_MARKERS = (
    'not supported',
    'not implemented',
    'invalid parameter',
    'the parameter is incorrect',
    'is not a valid parameter',
    'is not available',
)

# Errno values that mean "this filesystem cannot express POSIX modes".
# A vfat or exfat mount rejects chmod with EPERM; a read-only mount with
# EROFS.  Neither is something the caller could fix.
_UNSUPPORTED_ERRNOS = {
    errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EPERM,
    errno.EROFS,
}


@dataclass(frozen=True)
class PermissionResult:
    """Outcome of one permission enforcement attempt."""

    status: str
    platform: str
    path: str
    mode: int | None = None
    trustees: tuple[str, ...] = ()
    detail: str = ''

    @property
    def owner_only(self) -> bool:
        """True when the artifact is verified to exclude every other user."""
        return self.status in (STATUS_ENFORCED, STATUS_PRESERVED)

    @property
    def unsupported(self) -> bool:
        return self.status == STATUS_UNSUPPORTED

    @property
    def failed(self) -> bool:
        return self.status == STATUS_FAILED

    def as_dict(self) -> dict:
        payload = {
            'status': self.status,
            'platform': self.platform,
            'path': self.path,
            'owner_only': self.owner_only,
            'detail': self.detail,
        }
        if self.mode is not None:
            payload['mode'] = format(self.mode, '04o')
        if self.trustees:
            payload['trustees'] = list(self.trustees)
        return payload


def platform_name() -> str:
    """Return ``windows`` or ``posix`` for the running platform."""
    return 'windows' if os.name == 'nt' else 'posix'


def summarize(results: list[PermissionResult]) -> dict:
    """Summarise permission results into a report section.

    ``enforced`` is true only when every artifact was verified owner-only.
    The overall ``status`` names the weakest outcome so a caller can report
    an unsupported filesystem instead of implying protection it never had.
    """
    statuses = [result.status for result in results]
    if not statuses:
        status = STATUS_ENFORCED
    elif STATUS_FAILED in statuses:
        status = STATUS_FAILED
    elif STATUS_UNSUPPORTED in statuses:
        status = STATUS_UNSUPPORTED
    elif all(item == STATUS_ENFORCED for item in statuses):
        status = STATUS_ENFORCED
    else:
        status = STATUS_PRESERVED
    return {
        'platform': platform_name(),
        'status': status,
        'enforced': all(result.owner_only for result in results),
        'results': [result.as_dict() for result in results],
    }


def desired_directory_mode(current: int) -> int | None:
    """Return the mode an existing directory should have.

    ``None`` means the directory is already owner-only and must be left
    exactly as it is: a stricter pre-existing mode is never widened.  A
    directory that is owner-only but not writable by its owner stays that
    way too, so the caller learns about it from the write that follows
    rather than from a silently widened mode.
    """
    if current & 0o077 == 0:
        return None
    return DIRECTORY_MODE


def desired_file_mode(current: int) -> int:
    """Return the mode an existing file should have.

    The owner's read bit is guaranteed so a restored payload stays
    readable, and the owner's write bit is kept when it was already
    present.  Group and other access is always removed.
    """
    return (current & FILE_MODE) | 0o400


def _create_restricted_ancestors(target: Path) -> None:
    """Create the missing ancestors of ``target`` with the owner-only mode.

    ``Path.mkdir(parents=True)`` creates the intermediate directories with
    the filesystem default, which on a permissive umask is readable by
    every other user.  The ancestors that this call creates are therefore
    created one at a time and given the owner-only mode.

    Only directories that are actually missing are touched; a directory
    that already exists is never modified.  The ancestors are outside the
    artifact that is reported to the caller, so a failure to restrict one
    of them is not turned into an error: the backup directory itself is
    still owner-only, and POSIX requires search permission on every
    directory along the path, so the payloads stay unreachable for other
    users regardless of the ancestor mode.
    """
    missing = []
    current = target.parent
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for path in reversed(missing):
        try:
            path.mkdir(mode=DIRECTORY_MODE)
        except FileExistsError:
            continue
        except OSError:
            continue
        if platform_name() == 'windows':
            try:
                _windows_enforce(path, is_directory=True, created=True)
            except OSError:
                continue
        else:
            try:
                os.chmod(path, DIRECTORY_MODE)
            except OSError:
                continue


def create_directory(path: Path | str) -> PermissionResult:
    """Create a directory that only its owner can reach.

    The directory is created here, so its permissions are set exactly
    rather than preserving whatever the platform happened to apply.  The
    resulting permissions are read back before the result is reported.

    ``FileExistsError`` propagates: callers that need a fresh directory
    must not silently adopt an existing one.
    """
    target = Path(path)
    _create_restricted_ancestors(target)
    target.mkdir(exist_ok=False, mode=DIRECTORY_MODE)
    if platform_name() == 'windows':
        return _windows_enforce(target, is_directory=True, created=True)
    return _apply_posix_mode(target, DIRECTORY_MODE)


def ensure_directory(path: Path | str) -> PermissionResult:
    """Restrict a directory to its owner, creating it when it is missing.

    A directory that this module creates gets an exact owner-only policy; a
    directory that already existed keeps a stricter owner-only mode instead
    of being widened.
    """
    target = Path(path)
    if target.exists():
        return enforce_directory(target)
    try:
        return create_directory(target)
    except FileExistsError:
        return enforce_directory(target)


def enforce_directory(path: Path | str) -> PermissionResult:
    """Restrict an existing directory to its owner.

    A directory that is already owner-only keeps its exact mode, so a
    stricter pre-existing configuration is never widened.
    """
    target = Path(path)
    if platform_name() == 'windows':
        return _windows_enforce(target, is_directory=True, created=False)
    return _enforce_posix(target, is_directory=True)


def enforce_file(path: Path | str) -> PermissionResult:
    """Restrict a file to its owner.

    A file that already carries a stricter owner-only mode keeps that mode:
    the owner is never granted write access it did not have.
    """
    target = Path(path)
    if platform_name() == 'windows':
        return _windows_enforce(target, is_directory=False, created=False)
    return _enforce_posix(target, is_directory=False)


def restrict_created_file(path: Path | str) -> PermissionResult:
    """Restrict a file that this process has just created.

    Unlike :func:`enforce_file` the exact owner-only mode is applied, because
    the file was created for this purpose and the intended mode is known.
    The result is read back, so a filesystem that cannot express the mode is
    reported as such rather than as enforced.
    """
    target = Path(path)
    if platform_name() == 'windows':
        return _windows_enforce(target, is_directory=False, created=True)
    return _apply_posix_mode(target, FILE_MODE)


def write_private_text(path: Path | str, text: str) -> PermissionResult:
    """Write a file so that it is never readable by another user.

    On POSIX the file is created with the owner-only mode from the very
    first instant it exists.  On Windows the file is created inside an
    already restricted directory and its DACL is verified afterwards.
    """
    target = Path(path)
    if platform_name() == 'windows':
        target.write_text(text, encoding='utf-8')
        return enforce_file(target)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        output.write(text)
    # The creation mode is masked by the process umask, which can take the
    # owner's write bit away.  The exact owner-only mode is applied again so
    # the file stays writable for its owner, and the result is verified.
    return restrict_created_file(target)


def rewrite_private_text(path: Path | str, text: str) -> PermissionResult:
    """Replace the contents of a file that is already owner-only.

    The existing permissions are kept rather than reset, so updating a
    manifest cannot widen it.  The file has to exist already.

    A file that is already exactly owner-only is re-asserted and reported
    as ``enforced``, so that writing and then rewriting the same file
    yields the same status.  A strictly stricter file keeps its mode and is
    reported as ``preserved``.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(target)
    target.write_text(text, encoding='utf-8')
    if platform_name() == 'windows':
        return enforce_file(target)
    try:
        current = stat.S_IMODE(target.stat().st_mode)
    except OSError as exc:
        return PermissionResult(STATUS_FAILED, 'posix', str(target),
                                detail=f'unable to stat: {exc}')
    if current == FILE_MODE:
        # Re-asserting the mode the file already has changes nothing, but
        # it reports the outcome as enforced instead of merely preserved.
        return _apply_posix_mode(target, FILE_MODE)
    return _enforce_posix(target, is_directory=False)


def describe(path: Path | str) -> dict:
    """Describe the permissions currently in force on a path."""
    target = Path(path)
    payload = {'path': str(target), 'platform': platform_name()}
    if platform_name() == 'windows':
        dacl, owner = _read_security(target)
        trustees = tuple(_dacl_sids(dacl))
        payload['trustees'] = list(trustees)
        payload['owner_only'] = _is_owner_only(dacl, owner, trustees)
        return payload
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except OSError as exc:
        payload['mode'] = None
        payload['owner_only'] = False
        payload['detail'] = f'unable to stat: {exc}'
        return payload
    payload['mode'] = format(mode, '04o')
    payload['owner_only'] = mode & 0o077 == 0
    return payload


def _enforce_posix(path: Path, *, is_directory: bool) -> PermissionResult:
    platform = 'posix'
    try:
        current = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        return PermissionResult(STATUS_FAILED, platform, str(path),
                                detail=f'unable to stat: {exc}')

    desired = desired_directory_mode(current) if is_directory else desired_file_mode(current)
    if desired is None or current == desired:
        # Already owner-only; a stricter pre-existing mode is preserved.
        return PermissionResult(STATUS_PRESERVED, platform, str(path), mode=current,
                                detail='already restricted to the owner')
    return _apply_posix_mode(path, desired)


def _apply_posix_mode(path: Path, desired: int) -> PermissionResult:
    platform = 'posix'
    try:
        current = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        return PermissionResult(STATUS_FAILED, platform, str(path),
                                detail=f'unable to stat: {exc}')

    error = ''
    unsupported = False
    try:
        os.chmod(path, desired)
    except NotImplementedError as exc:
        return PermissionResult(STATUS_UNSUPPORTED, platform, str(path), mode=current,
                                detail=f'permissions are not supported here: {exc}')
    except OSError as exc:
        if getattr(exc, 'errno', None) not in _UNSUPPORTED_ERRNOS:
            return PermissionResult(STATUS_FAILED, platform, str(path), mode=current,
                                    detail=f'chmod failed: {exc}')
        # The filesystem refused the mode.  The end state is verified
        # below, so the outcome is reported as unsupported rather than as
        # a generic failure when the artifact is still owner-only.
        unsupported = True
        error = f'chmod failed: {exc}'

    try:
        observed = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        return PermissionResult(STATUS_FAILED, platform, str(path), mode=desired,
                                detail=f'unable to verify permissions: {exc}')

    if observed == desired:
        return PermissionResult(STATUS_ENFORCED, platform, str(path), mode=observed)
    if observed & 0o077 == 0:
        # The end state is owner-only even though it is not exactly the
        # requested mode: report the protection and keep the reason.
        return PermissionResult(STATUS_PRESERVED, platform, str(path), mode=observed,
                                detail=error or 'the filesystem kept a stricter owner-only mode')
    if unsupported:
        return PermissionResult(STATUS_UNSUPPORTED, platform, str(path), mode=observed,
                                detail=error or 'this filesystem does not support POSIX permissions')
    return PermissionResult(STATUS_FAILED, platform, str(path), mode=observed,
                            detail=error or f'expected mode {desired:04o}, observed {observed:04o}')


def _normalize_sid(value: str) -> str:
    value = value.strip()
    return _ALIAS_SIDS.get(value.upper(), value)


def _dacl_aces(dacl: str | None) -> list[list[str]]:
    """Return the raw ACE field lists of an SDDL DACL string."""
    if not dacl:
        return []
    return [ace.split(';') for ace in re.findall(r'\(([^()]*)\)', dacl)]


def _dacl_sids(dacl: str | None) -> list[str]:
    """Return the trustee SIDs of an SDDL DACL string."""
    sids = []
    for fields in _dacl_aces(dacl):
        if len(fields) < 2:
            continue
        sids.append(_normalize_sid(fields[-1]))
    return sids


def _owner_has_full_control(dacl: str | None, sid: str | None) -> bool:
    if not sid:
        return False
    for fields in _dacl_aces(dacl):
        if len(fields) < 3:
            continue
        if _normalize_sid(fields[-1]) != sid:
            continue
        if fields[2].upper() in _FULL_ACCESS:
            return True
    return False


def _is_owner_only(dacl: str | None, owner: str | None, trustees: tuple[str, ...]) -> bool:
    """True when a Windows descriptor excludes every foreign trustee."""
    if dacl is None or not owner:
        return False
    allowed = {WINDOWS_SYSTEM_SID, WINDOWS_ADMINISTRATORS_SID, owner}
    if any(sid not in allowed for sid in trustees):
        return False
    return _owner_has_full_control(dacl, owner)


def _current_user_sid() -> str | None:
    """Return the numeric SID of the account running this process."""
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes

        advapi = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)

        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.HANDLE)]
        advapi.OpenProcessToken.restype = wintypes.BOOL
        advapi.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi.GetTokenInformation.restype = wintypes.BOOL
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                                  ctypes.POINTER(ctypes.c_wchar_p)]
        advapi.ConvertSidToStringSidW.restype = wintypes.BOOL

        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008,
                                       ctypes.byref(token)):
            return None
        size = wintypes.DWORD(0)
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            return None
        # TOKEN_USER starts with a SID_AND_ATTRIBUTES whose first member is
        # the user SID pointer.
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text = ctypes.c_wchar_p()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            return None
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    except Exception:
        return None


def _system_binary(name: str) -> str | None:
    """Locate a Windows system binary without relying on PATH."""
    root = os.environ.get('SystemRoot') or os.environ.get('WINDIR')
    if root:
        candidate = Path(root) / 'System32' / name
        if candidate.exists():
            return str(candidate)
    return None


def _read_security(path: Path) -> tuple[str | None, str | None]:
    """Return ``(dacl_sddl, owner_sid)`` for a path.

    The DACL and the owner are read through the Win32 API rather than by
    parsing ``icacls`` output, and the DACL is requested on its own so the
    returned SDDL contains nothing but the access section.
    """
    if os.name != 'nt':
        return None, None
    try:
        import ctypes
        from ctypes import wintypes

        advapi = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)

        advapi.GetNamedSecurityInfoW.argtypes = [
            wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
        advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(wintypes.DWORD),
        ]
        advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL

        descriptor = ctypes.c_void_p()
        owner = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        rc = advapi.GetNamedSecurityInfoW(
            str(path), 1, 0x00000001 | 0x00000004,  # OWNER | DACL
            ctypes.byref(owner), None, ctypes.byref(dacl), None,
            ctypes.byref(descriptor),
        )
        if rc != 0:
            return None, None
        try:
            dacl_text = _sddl_text(advapi, kernel, descriptor, 0x00000004)
            owner_text = _sddl_text(advapi, kernel, descriptor, 0x00000001)
        finally:
            kernel.LocalFree(descriptor)
    except Exception:
        return None, None
    owner_sid = None
    if owner_text and owner_text.startswith('O:'):
        owner_sid = _normalize_sid(owner_text[2:].split(';')[0].strip())
    return dacl_text, owner_sid


def _sddl_text(advapi, kernel, descriptor, info: int) -> str | None:
    import ctypes

    text = ctypes.c_wchar_p()
    try:
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, info, ctypes.byref(text), None
        ):
            return None
        return text.value
    finally:
        kernel.LocalFree(text)


def _read_dacl(path: Path) -> str | None:
    dacl, _ = _read_security(path)
    return dacl


def _run_icacls(path: Path, arguments: list[str]) -> tuple[int, str]:
    binary = _system_binary('icacls.exe')
    if binary is None:
        return 127, 'icacls.exe is not available'
    try:
        completed = subprocess.run(
            [binary, str(path), *arguments], capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    output = (completed.stdout or b'') + (completed.stderr or b'')
    return completed.returncode, output.decode('utf-8', errors='replace')


def _icacls_unsupported(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _UNSUPPORTED_MARKERS)


def _windows_enforce(path: Path, *, is_directory: bool, created: bool) -> PermissionResult:
    """Restrict a Windows path to its owner and verify the resulting DACL.

    ``created`` marks a path this module created: those get the owner plus
    ``SYSTEM`` and ``Administrators``, matching the access a new Windows
    folder grants by default.  For a path that already existed the trustee
    set is never widened -- ``SYSTEM`` and ``Administrators`` are kept only
    when the descriptor already granted them access, and every other
    trustee is dropped.  The owner recorded in the descriptor is always
    kept so a backup is never taken away from the account that owns it.
    """
    platform = 'windows'
    if not path.exists():
        return PermissionResult(STATUS_FAILED, platform, str(path),
                                detail='the path does not exist')
    user_sid = _current_user_sid()
    if not user_sid:
        return PermissionResult(STATUS_UNSUPPORTED, platform, str(path),
                                detail='unable to determine the current user SID')

    dacl, owner_sid = _read_security(path)
    if dacl is None:
        return PermissionResult(STATUS_UNSUPPORTED, platform, str(path),
                                detail='unable to read the security descriptor')

    existing = tuple(_dacl_sids(dacl))
    owner = owner_sid or user_sid
    allowed = {owner}
    if created and is_directory:
        # A directory this module creates gets the same access a fresh
        # Windows folder has: the creating account, SYSTEM and
        # Administrators.  Files are not widened here -- a file created
        # inside the directory inherits the directory's entries, so the
        # existing-trustee rule below already keeps SYSTEM and
        # Administrators when the directory grants them.
        allowed.update({user_sid, WINDOWS_SYSTEM_SID, WINDOWS_ADMINISTRATORS_SID})
    else:
        # An existing path is never widened: SYSTEM and Administrators are
        # kept only when the descriptor already granted them access, and
        # the creating account is kept only when it was already a trustee
        # or it already owns the path.
        allowed.update({sid for sid in existing
                        if sid in {WINDOWS_SYSTEM_SID, WINDOWS_ADMINISTRATORS_SID}})
        if user_sid in existing or user_sid == owner:
            allowed.add(user_sid)
    foreign = [sid for sid in existing if sid not in allowed]

    if not foreign and _owner_has_full_control(dacl, owner):
        return PermissionResult(STATUS_PRESERVED, platform, str(path), trustees=existing,
                                detail='already restricted to the owner')

    flags = '(OI)(CI)' if is_directory else ''
    errors: list[str] = []
    # Grant first.  Removing inheritance on a descriptor that only carried
    # inherited entries would otherwise leave the owner without access.
    for sid in sorted(allowed):
        rc, message = _run_icacls(path, ['/grant:r', f'*{sid}:{flags}(F)'])
        if rc != 0:
            errors.append(f'grant {sid}: {message.strip()}')
            break
    if not errors:
        rc, message = _run_icacls(path, ['/inheritance:r'])
        if rc != 0:
            errors.append(f'inheritance: {message.strip()}')

    if not errors:
        # Drop any explicit entries for trustees outside the allowed set.
        for _ in range(16):
            current = _read_dacl(path)
            if current is None:
                errors.append('unable to re-read the security descriptor')
                break
            remaining = [sid for sid in _dacl_sids(current) if sid not in allowed]
            if not remaining:
                break
            for sid in remaining:
                rc, message = _run_icacls(path, ['/remove:g', f'*{sid}'])
                if rc != 0:
                    errors.append(f'remove {sid}: {message.strip()}')
                    break
            if errors:
                break
        else:
            errors.append('unable to clear foreign trustees')

    after = _read_dacl(path)
    if after is None:
        return PermissionResult(STATUS_UNSUPPORTED, platform, str(path), trustees=existing,
                                detail='; '.join(errors) or 'unable to verify the security descriptor')
    final = tuple(_dacl_sids(after))
    leftover = [sid for sid in final if sid not in allowed]
    if leftover or not _owner_has_full_control(after, owner):
        # The descriptor could not be reduced to the owner.  Report why
        # instead of claiming protection that is not in force.
        detail = '; '.join(errors) or f'the resulting DACL still grants access to {sorted(leftover)}'
        status = STATUS_UNSUPPORTED if _icacls_unsupported(detail) else STATUS_FAILED
        return PermissionResult(status, platform, str(path), trustees=final, detail=detail)
    if errors:
        # The end state is verified, but something went wrong on the way.
        return PermissionResult(STATUS_ENFORCED, platform, str(path), trustees=final,
                                detail='verified after: ' + '; '.join(errors))
    return PermissionResult(STATUS_ENFORCED, platform, str(path), trustees=final)
