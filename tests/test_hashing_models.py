"""Contract tests for exact-hashing result models."""

from __future__ import annotations

import pytest

from imageset_guard.hashing_models import HashingResult, HashRecord


def _record(path: str = "train/cats/a.jpg", digest: str = "a" * 64) -> HashRecord:
    return HashRecord(path, "train", "cats", digest)


def test_hash_record_accepts_canonical_sha256() -> None:
    assert _record().sha256 == "a" * 64


@pytest.mark.parametrize(
    "digest",
    ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, 123, None],
)
def test_hash_record_rejects_noncanonical_digest(digest: object) -> None:
    with pytest.raises(ValueError, match="sha256"):
        HashRecord("train/cats/a.jpg", "train", "cats", digest)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("relative_path", "split", "class_name"),
    [
        ("train/cats/a.jpg", "test", "cats"),
        ("train/cats/a.jpg", "train", "dogs"),
        ("train/cats", "train", "cats"),
        ("train/cats/a.jpg", "train", "cats\nsecret"),
    ],
)
def test_hash_record_rejects_incoherent_or_unsafe_identity(
    relative_path: str, split: str, class_name: str
) -> None:
    with pytest.raises(ValueError):
        HashRecord(relative_path, split, class_name, "a" * 64)


def test_hashing_result_enforces_eligible_accounting() -> None:
    record = _record()
    assert HashingResult((record,), (), (), 1).eligible_file_count == 1
    with pytest.raises(ValueError, match="eligible"):
        HashingResult((record,), (), (), 0)
