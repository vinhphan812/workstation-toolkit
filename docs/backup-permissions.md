# Backup permissions

Backups can contain sensitive configuration and SQLite state, so every
artifact a backup creates is restricted to its owner. The policy lives in
`src/workstation/core/permissions.py`; `src/workstation/core/backup.py`
decides what has to be restricted and reports what happened.

## The policy

* POSIX directories are `0700` and files are `0600`.
* Windows DACLs are reduced to the creating account, the owner recorded in
  the security descriptor, `SYSTEM` and `Administrators`.

Four rules shape the implementation.

**Access is never broadened.** A file that already carries a stricter
owner-only mode keeps it; group and other bits are removed and nothing is
added back. A directory that is already owner-only keeps its exact mode. On
Windows the owner recorded in the descriptor is never revoked, `SYSTEM` and
`Administrators` are kept only when the descriptor already granted them
access, and every other trustee is dropped.

**Protection is never claimed without verification.** Every enforcement
attempt re-reads the resulting permissions and compares them against the
policy. When a filesystem or platform cannot express the policy — FAT or
exFAT volumes, some network shares, a missing `icacls` — the outcome is
reported as `unsupported` instead of `enforced`. An unexpected error is
reported as `failed`.

**The owner's own access is never broken.** On Windows the owner is granted
access *before* inheritance is removed: stripping inherited entries from a
descriptor that only carried inherited entries would otherwise leave the
owner locked out of its own backup. On POSIX the artifacts are created with
an owner-only mode from the first instant they exist, so a failing `chmod`
can never leave a readable file behind.

**Explicit beats inherited.** On Windows the resulting DACL is written as
explicit access for the allowed trustees, so it does not change when the
parent directory's permissions change later.

**Missing parents are created owner-only too.** `Path.mkdir(parents=True)`
would create the intermediate directories with the filesystem default, which
is readable by every other user on a permissive umask. The ancestors that a
backup creates are therefore created one at a time with the owner-only mode.
An ancestor that already existed is never modified, and it is never widened.

**A read-only artifact can still be rewritten.** The manifest is written
owner-only and then rewritten with its summary. A file the owner may read
but not write cannot be replaced in place, so the owner's write bit is added
for the duration of that write and the original mode is restored afterwards,
including when the write itself fails. The artifact stays owner-only
throughout, and a stricter pre-existing mode is preserved.

## What the caller sees

`backup_files()` returns a `permissions` section that names the weakest
outcome across every artifact it created, and the same section is recorded
in the manifest:

```json
{
  "permissions": {
    "platform": "posix",
    "status": "enforced",
    "enforced": true,
    "results": [ ... ]
  }
}
```

`status` is one of `enforced`, `preserved`, `unsupported` or `failed`, and
`enforced` is true only when every artifact was verified owner-only. A
`preserved` result means the artifact was already owner-only and its
stricter pre-existing configuration was kept.

`unsupported` is reported rather than raised: the backup still runs and the
outcome is stated honestly in the result and in the manifest. A `failed`
result is an error, because continuing would write the payload into a
location that is known not to be protected. When that happens the backup
aborts and removes the destination directory it created, so no unprotected
copy of sensitive data is left behind.

## Platform limitations

On POSIX the individual `chmod` operation is atomic, but creating a
directory and then changing its mode is not a single atomic operation; a
brief interval can exist with the filesystem's default mode. The artifacts
are created with an owner-only mode in the first place, so that interval
does not expose them. The POSIX umask may narrow access further.

Existing backup-root ACLs are not queried or rewritten on POSIX; `chmod` does
not broaden POSIX mode bits but may interact with ACL masks.

Network shares, removable filesystems, and filesystems that ignore or
translate POSIX mode bits may not enforce these restrictions at all. On such
a destination the result is reported as `unsupported` rather than as
`enforced`. Verify access controls on the destination filesystem when backup
confidentiality is required.
