# Backup permissions

On POSIX filesystems, backup creation restricts the backups root and each new
backup directory to mode `0700`, and each copied payload and manifest to `0600`.
The modes are applied immediately after creating/copying each entry. The
individual `chmod` operation is atomic, but creating a directory and then
changing its mode is not a single atomic operation; a brief interval can exist
with the filesystem's default mode. POSIX umask may narrow access further.
Existing backup-root ACLs are not queried or rewritten; chmod does not broaden
POSIX mode bits but may interact with ACL masks.

On Windows, this implementation does not edit or verify NTFS ACLs and leaves
inherited ACLs in place. Use a destination directory already secured for the
current user; owner-only ACL enforcement is not claimed. Network shares,
removable filesystems, and filesystems that ignore or translate POSIX mode bits
may not enforce these restrictions. Verify access controls on the destination
filesystem when backup confidentiality is required.
