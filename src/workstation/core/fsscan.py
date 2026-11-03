"""Filesystem traversal helpers shared by the audit modules.

The naive way to measure a directory is ``Path.rglob("*")`` followed by
``is_file()`` and ``stat()`` on every entry. On Windows that costs two
syscalls per file, because ``DirEntry.is_file()`` is not served from the
``FindFileData`` cache the way ``is_dir()`` is. Profiling the audit
commands showed this dominating the runtime:

    android-cleanup-plan  ->  303,058 is_file() calls, 252,584 stat() calls
    git-worktrees         ->  923,830 scandir() calls

``os.scandir`` already returns the entry attributes, so a single
``entry.stat()`` per file is enough. The helpers here walk the tree
iteratively with an explicit stack instead of recursing, so a deep tree
cannot exhaust the interpreter stack, and they never follow symlinks.
"""
from __future__ import annotations

import os
from typing import Iterator, List

__all__ = ["iter_tree", "dir_size_bytes", "dir_size_mb", "largest_entries"]

# FILE_ATTRIBUTE_REPARSE_POINT. A Windows directory junction is a reparse
# point that still reports itself as a directory when the link is not
# followed, so it has to be excluded explicitly or the walk descends into a
# link and counts the linked files twice.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_link(entry: os.DirEntry) -> bool:
    """True when *entry* is a link that the walk must not descend into."""
    try:
        if entry.is_symlink():
            return True
        result = entry.stat(follow_symlinks=False)
    except OSError:
        # An entry that cannot be inspected is not descended into.
        return True
    if getattr(result, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
        return True
    return False


def iter_tree(root: os.PathLike | str, exclude: frozenset[str] = frozenset()) -> Iterator[os.DirEntry]:
    """Yield every entry under *root*, depth-first, without following links.

    Symbolic links and Windows directory junctions are reported but never
    descended into, so a link pointing at an ancestor cannot send the walk
    into an infinite loop and linked files are not counted twice.

    Directory names in *exclude* are skipped at any depth. The names are
    matched exactly, so ``.venv`` excludes every directory called ``.venv``.
    """
    stack: List[str] = [os.fspath(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        is_directory = entry.is_dir(follow_symlinks=False)
                        if is_directory and exclude and entry.name in exclude:
                            continue
                        if is_directory and not _is_link(entry):
                            stack.append(entry.path)
                    except OSError:
                        continue
                    yield entry
        except OSError:
            continue


def dir_size_bytes(root: os.PathLike | str, exclude: frozenset[str] = frozenset()) -> int:
    """Return the total size in bytes of every file under *root*.

    Unreadable directories and files are skipped rather than raising, which
    matches the behaviour the audit commands had before this helper existed.
    """
    total = 0
    for entry in iter_tree(root, exclude):
        try:
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    return total


def dir_size_by_child(root: os.PathLike | str, depth: int = 1,
                      exclude: frozenset[str] = frozenset()) -> dict[str, int]:
    """Return the size in bytes of each entry *depth* levels under *root*.

    With ``depth=1`` the keys are the immediate children of *root*; with
    ``depth=2`` they are ``"<child>/<grandchild>"``. One traversal yields
    both the total and the per-child breakdown. The Android SDK audit needs
    both, and measuring them separately walked the same files twice.
    """
    sizes: dict[str, int] = {}
    root_path = os.path.abspath(os.fspath(root))
    prefix_len = len(root_path) + 1
    for entry in iter_tree(root, exclude):
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            size = entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        path = os.path.abspath(entry.path)
        if not path.startswith(root_path):
            continue
        remainder = path[prefix_len:]
        parts = remainder.split(os.sep)
        if len(parts) < depth:
            continue
        key = os.sep.join(parts[:depth])
        sizes[key] = sizes.get(key, 0) + size
    return sizes


def dir_size_by_child_levels(root: os.PathLike | str, depths: tuple[int, ...],
                            exclude: frozenset[str] = frozenset()) -> dict[int, dict[str, int]]:
    """Return the per-child size breakdown for several depths in one pass.

    The key for depth *n* is the first *n* path components below *root*, and
    the value is the total size of every file beneath that key. A file
    deeper than *n* still counts towards the key it lives under, so depth 1
    always sums to the total size of the tree.

    Equivalent to calling :func:`dir_size_by_child` once per depth, but the
    directory tree is walked only once.
    """
    levels: dict[int, dict[str, int]] = {depth: {} for depth in depths}
    root_path = os.path.abspath(os.fspath(root))
    prefix_len = len(root_path) + 1
    for entry in iter_tree(root, exclude):
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            size = entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        path = os.path.abspath(entry.path)
        if not path.startswith(root_path):
            continue
        parts = path[prefix_len:].split(os.sep)
        for depth in depths:
            if len(parts) < depth:
                continue
            bucket = levels[depth]
            key = os.sep.join(parts[:depth])
            bucket[key] = bucket.get(key, 0) + size
    return levels


def dir_size_mb(root: os.PathLike | str, exclude: frozenset[str] = frozenset()) -> float:
    """Return the total size in megabytes of every file under *root*."""
    return dir_size_bytes(root, exclude) / (1024 ** 2)


def largest_entries(root: os.PathLike | str, top: int = 20) -> List[dict]:
    """Return the *top* largest files under *root*, newest scan included.

    Used to explain *why* a directory is large without walking it twice.
    """
    ranked = []
    for entry in iter_tree(root):
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            size = entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        ranked.append((size, entry.path))
    ranked.sort(reverse=True)
    return [{"path": path, "size_mb": round(size / (1024 ** 2), 2)} for size, path in ranked[:top]]
