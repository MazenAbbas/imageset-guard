"""Tests for the shared read-only stable-file guard."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from imageset_guard import file_access
from imageset_guard.file_access import (
    CandidateChangedError,
    FileIdentity,
    file_identity_from_stream,
    open_regular_file_readonly,
)


def test_regular_file_is_opened_read_only_and_closed(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    with open_regular_file_readonly(path) as stream:
        assert stream.read() == b"abc"
        assert stream.writable() is False
    renamed = tmp_path / "renamed.bin"
    path.rename(renamed)
    assert renamed.is_file()


def test_directory_is_rejected_before_open(tmp_path: Path) -> None:
    with pytest.raises(CandidateChangedError), open_regular_file_readonly(tmp_path):
        raise AssertionError("must not yield")


def test_identity_mismatch_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    monkeypatch.setattr(file_access, "same_file_identity", lambda before, after: False)
    with pytest.raises(CandidateChangedError), open_regular_file_readonly(path):
        raise AssertionError("must not yield")


def test_detectable_mutation_during_read_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    with pytest.raises(CandidateChangedError), open_regular_file_readonly(path) as stream:
        assert stream.read() == b"abc"
        with path.open("ab") as writer:
            writer.write(b"changed")


def test_open_uses_no_write_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    real_open = os.open
    seen: list[int] = []

    def recording_open(target: Path, flags: int) -> int:
        seen.append(flags)
        return real_open(target, flags)

    monkeypatch.setattr(os, "open", recording_open)
    with open_regular_file_readonly(path):
        pass
    assert seen
    assert all(flags & os.O_WRONLY == 0 and flags & os.O_RDWR == 0 for flags in seen)


def test_expected_identity_binds_a_later_open_to_the_inspected_file(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"original")
    with open_regular_file_readonly(path) as stream:
        identity = file_identity_from_stream(stream)

    path.write_bytes(b"replacement")
    with pytest.raises(CandidateChangedError), open_regular_file_readonly(
        path, expected_identity=identity
    ):
        raise AssertionError("changed candidate must not be yielded")


@pytest.mark.parametrize(
    "values",
    [(-1, 0, 0, 0), (0, -1, 0, 0), (0, 0, -1, 0), (0, 0, 0, -1)],
)
def test_file_identity_rejects_negative_fields(values: tuple[int, int, int, int]) -> None:
    with pytest.raises(ValueError):
        FileIdentity(*values)
