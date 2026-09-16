"""Best-effort, read-only opening of a stable regular file.

The helper is shared by image decoding and hashing. It rejects links and
non-regular files before opening, uses ``O_NOFOLLOW`` where available, compares
descriptor identity, and verifies that size and modification time did not
change while the descriptor was in use. This narrows common TOCTOU windows but
is not an atomic cross-platform security boundary.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class CandidateChangedError(Exception):
    """The path no longer names the same stable regular file."""


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """Non-serialized identity binding inspection bytes to hashing bytes."""

    device: int
    inode: int
    size: int
    modified_ns: int

    def __post_init__(self) -> None:
        for name in ("device", "inode", "size", "modified_ns"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative int")


def file_identity_from_stream(stream: BinaryIO) -> FileIdentity:
    """Capture the descriptor identity used to bind later hashing."""
    info = os.fstat(stream.fileno())
    return FileIdentity(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _identity_from_stat(info: os.stat_result) -> FileIdentity:
    return FileIdentity(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def same_file_identity(before: os.stat_result, after: os.stat_result) -> bool:
    """Compare identities, falling back to stable metadata if inode is unavailable."""
    if before.st_ino and after.st_ino:
        return before.st_dev == after.st_dev and before.st_ino == after.st_ino
    return before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns


def _is_redirecting_entry(info: os.stat_result) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return True
    tag = getattr(info, "st_reparse_tag", 0)
    mount_tag = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None)
    symlink_tag = getattr(stat, "IO_REPARSE_TAG_SYMLINK", None)
    return tag != 0 and tag in {mount_tag, symlink_tag}


def _unchanged_during_read(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        same_file_identity(before, after)
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
    )


@contextmanager
def open_regular_file_readonly(
    path: Path, *, expected_identity: FileIdentity | None = None
) -> Iterator[BinaryIO]:
    """Yield one read-only descriptor and reject detectable replacement/mutation."""
    before = os.lstat(path)
    if _is_redirecting_entry(before) or not stat.S_ISREG(before.st_mode):
        raise CandidateChangedError

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or not same_file_identity(before, opened):
            raise CandidateChangedError
        if expected_identity is not None and _identity_from_stat(opened) != expected_identity:
            raise CandidateChangedError
        with os.fdopen(fd, "rb", closefd=True) as stream:
            fd = -1
            yield stream
            finished = os.fstat(stream.fileno())
            if not _unchanged_during_read(opened, finished):
                raise CandidateChangedError
    finally:
        if fd >= 0:
            os.close(fd)
