"""Streaming SHA-256 and exact duplicate/leakage tests."""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

import pytest
from PIL import Image

from imageset_guard import codes, hashing
from imageset_guard.discovery import discover
from imageset_guard.discovery_models import DiscoveredImageCandidate
from imageset_guard.file_access import CandidateChangedError, FileIdentity
from imageset_guard.hashing import HASH_CHUNK_SIZE, hash_candidates, is_hash_eligible
from imageset_guard.hashing_models import HashingResult, HashRecord
from imageset_guard.inspection import inspect_candidates
from imageset_guard.inspection_models import CandidateInspection, InspectionResult
from imageset_guard.models import Category, Finding, ScanError, Severity


def _candidate(
    path: Path, relative_path: str, split: str, class_name: str
) -> DiscoveredImageCandidate:
    return DiscoveredImageCandidate(
        path.absolute(), relative_path, split, class_name, path.suffix.lower()
    )


def _save(path: Path, color: str = "red") -> None:
    Image.new("RGB", (5, 5), color).save(path, format="JPEG")


def _pipeline(
    candidates: list[DiscoveredImageCandidate],
) -> tuple[InspectionResult, HashingResult]:
    inspected = inspect_candidates(candidates)
    return inspected, hash_candidates(candidates, inspected)


def test_sha256_matches_hashlib_and_digest_is_not_in_findings(tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    _save(path)
    candidate = _candidate(path, "train/cats/a.jpg", "train", "cats")
    inspected, result = _pipeline([candidate])
    assert inspected.examined_file_count == 1
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.records[0].sha256 == expected
    assert result.findings == ()


def test_hashing_reads_in_bounded_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "a.jpg"
    _save(path)
    candidate = _candidate(path, "train/cats/a.jpg", "train", "cats")
    inspected = inspect_candidates([candidate])
    requested_sizes: list[int] = []
    real_hash = hashing._sha256_stream

    class RecordingStream:
        def __init__(self, wrapped: BinaryIO) -> None:
            self.wrapped = wrapped

        def read(self, size: int = -1) -> bytes:
            requested_sizes.append(size)
            return self.wrapped.read(size)

    @contextlib.contextmanager
    def wrapped_open(
        target: Path, *, expected_identity: FileIdentity | None = None
    ) -> Iterator[BinaryIO]:
        assert expected_identity is not None
        with target.open("rb") as raw:
            yield RecordingStream(raw)  # type: ignore[misc]

    monkeypatch.setattr(hashing, "open_regular_file_readonly", wrapped_open)
    result = hash_candidates([candidate], inspected)
    assert result.records
    assert requested_sizes and set(requested_sizes) == {HASH_CHUNK_SIZE}
    assert real_hash is hashing._sha256_stream


def test_duplicate_within_same_split_and_class_is_warning(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    _save(first)
    second.write_bytes(first.read_bytes())
    candidates = [
        _candidate(first, "train/cats/a.jpg", "train", "cats"),
        _candidate(second, "train/cats/b.jpg", "train", "cats"),
    ]
    _, result = _pipeline(candidates)
    assert [finding.code for finding in result.findings] == [codes.DUP_WITHIN_CLASS]
    assert result.findings[0].severity is Severity.WARNING
    assert result.findings[0].evidence == {"matches": "train/cats/a.jpg"}


def test_duplicate_across_classes_is_error(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    _save(first)
    second.write_bytes(first.read_bytes())
    candidates = [
        _candidate(first, "train/cats/a.jpg", "train", "cats"),
        _candidate(second, "train/dogs/b.jpg", "train", "dogs"),
    ]
    _, result = _pipeline(candidates)
    assert [finding.code for finding in result.findings] == [codes.DUP_ACROSS_CLASSES]
    assert result.findings[0].severity is Severity.ERROR


def test_duplicate_across_splits_is_leakage_error(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    _save(first)
    second.write_bytes(first.read_bytes())
    candidates = [
        _candidate(first, "train/cats/a.jpg", "train", "cats"),
        _candidate(second, "validation/cats/b.jpg", "validation", "cats"),
    ]
    _, result = _pipeline(candidates)
    assert [finding.code for finding in result.findings] == [codes.DUP_ACROSS_SPLITS]
    assert result.findings[0].severity is Severity.ERROR


def test_group_can_report_class_conflict_and_split_leakage(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    _save(first)
    second.write_bytes(first.read_bytes())
    candidates = [
        _candidate(first, "train/cats/a.jpg", "train", "cats"),
        _candidate(second, "test/dogs/b.jpg", "test", "dogs"),
    ]
    _, result = _pipeline(candidates)
    assert {finding.code for finding in result.findings} == {
        codes.DUP_ACROSS_CLASSES,
        codes.DUP_ACROSS_SPLITS,
    }


def test_three_member_group_does_not_miss_same_class_relationship(tmp_path: Path) -> None:
    paths = [tmp_path / name for name in ("a.jpg", "b.jpg", "c.jpg")]
    _save(paths[0])
    for path in paths[1:]:
        path.write_bytes(paths[0].read_bytes())
    candidates = [
        _candidate(paths[0], "train/cats/a.jpg", "train", "cats"),
        _candidate(paths[1], "train/dogs/b.jpg", "train", "dogs"),
        _candidate(paths[2], "train/dogs/c.jpg", "train", "dogs"),
    ]
    _, result = _pipeline(candidates)
    codes_by_path = {
        path: {finding.code for finding in result.findings if finding.relative_path == path}
        for path in ("train/dogs/b.jpg", "train/dogs/c.jpg")
    }
    assert codes_by_path["train/dogs/b.jpg"] == {codes.DUP_ACROSS_CLASSES}
    assert codes_by_path["train/dogs/c.jpg"] == {
        codes.DUP_WITHIN_CLASS,
        codes.DUP_ACROSS_CLASSES,
    }


def test_integrity_failure_is_not_hashed_but_privacy_finding_is(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jpg"
    gps = tmp_path / "gps.jpg"
    bad.write_bytes(b"not an image")
    exif = Image.Exif()
    exif[34853] = {1: "N"}
    Image.new("RGB", (4, 4)).save(gps, exif=exif)
    candidates = [
        _candidate(bad, "train/cats/bad.jpg", "train", "cats"),
        _candidate(gps, "train/cats/gps.jpg", "train", "cats"),
    ]
    inspected, result = _pipeline(candidates)
    assert result.eligible_file_count == 1
    assert [record.relative_path for record in result.records] == ["train/cats/gps.jpg"]
    assert is_hash_eligible(inspected.inspections[0]) is False
    assert is_hash_eligible(inspected.inspections[1]) is True


def test_hash_read_failure_is_sanitized_and_other_candidates_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    _save(first)
    _save(second, "blue")
    candidates = [
        _candidate(first, "train/cats/a.jpg", "train", "cats"),
        _candidate(second, "train/cats/b.jpg", "train", "cats"),
    ]
    inspected = inspect_candidates(candidates)
    real_hash_candidate = hashing._hash_candidate
    secret = "C:/Users/private-person/image.jpg"

    def sometimes_fails(
        candidate: DiscoveredImageCandidate, identity: FileIdentity
    ) -> tuple[HashRecord | None, ScanError | None]:
        if candidate.relative_path.endswith("a.jpg"):
            return None, hashing._scan_error(
                PermissionError(13, secret), candidate.relative_path, "read"
            )
        return real_hash_candidate(candidate, identity)

    monkeypatch.setattr(hashing, "_hash_candidate", sometimes_fails)
    result = hash_candidates(candidates, inspected)
    assert result.eligible_file_count == 2
    assert len(result.records) == 1
    assert result.scan_errors[0].code == codes.SYS_PERMISSION_DENIED
    assert secret not in repr(result)


def test_digest_never_appears_in_duplicate_finding_or_evidence(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    _save(first)
    second.write_bytes(first.read_bytes())
    candidates = [
        _candidate(first, "train/cats/a.jpg", "train", "cats"),
        _candidate(second, "validation/cats/b.jpg", "validation", "cats"),
    ]
    _, result = _pipeline(candidates)
    digest = result.records[0].sha256
    assert all(digest not in repr(finding) for finding in result.findings)


def test_candidate_and_inspection_path_sets_must_match(tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    _save(path)
    candidate = _candidate(path, "train/cats/a.jpg", "train", "cats")
    empty = InspectionResult((), (), (), 0)
    with pytest.raises(ValueError, match="same paths"):
        hash_candidates([candidate], empty)


def test_unexamined_candidate_is_not_hash_eligible() -> None:
    inspection = CandidateInspection(
        relative_path="train/cats/a.jpg",
        examined=False,
        findings=(),
        scan_errors=(
            hashing._scan_error(
                FileNotFoundError("secret absolute path"), "train/cats/a.jpg", "open"
            ),
        ),
        file_identity=None,
    )
    assert is_hash_eligible(inspection) is False


def test_integrity_warning_remains_hash_eligible() -> None:
    warning = Finding(
        code=codes.IMG_DECODER_WARNING,
        severity=Severity.WARNING,
        category=Category.INTEGRITY,
        message=codes.DEFAULT_MESSAGES[codes.IMG_DECODER_WARNING],
        relative_path="train/cats/a.jpg",
        remediation="review",
    )
    inspection = CandidateInspection(
        "train/cats/a.jpg", True, (warning,), (), FileIdentity(1, 2, 3, 4)
    )
    assert is_hash_eligible(inspection) is True


def test_different_bytes_do_not_produce_duplicate_findings(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    _save(first, "red")
    _save(second, "blue")
    candidates = [
        _candidate(first, "train/cats/a.jpg", "train", "cats"),
        _candidate(second, "validation/cats/b.jpg", "validation", "cats"),
    ]
    _, result = _pipeline(candidates)
    assert result.findings == ()


def test_result_is_deterministic_when_candidates_are_reversed(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    _save(first)
    second.write_bytes(first.read_bytes())
    candidates = [
        _candidate(first, "train/cats/a.jpg", "train", "cats"),
        _candidate(second, "test/cats/b.jpg", "test", "cats"),
    ]
    _, forward = _pipeline(candidates)
    _, reversed_result = _pipeline(list(reversed(candidates)))
    assert forward == reversed_result


def test_candidate_change_during_hash_discards_partial_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "a.jpg"
    _save(path)
    candidate = _candidate(path, "train/cats/a.jpg", "train", "cats")
    inspected = inspect_candidates([candidate])

    @contextlib.contextmanager
    def changed_open(
        _target: Path, *, expected_identity: FileIdentity | None = None
    ) -> Iterator[BinaryIO]:
        assert expected_identity is not None
        with path.open("rb") as stream:
            yield stream
        raise CandidateChangedError

    monkeypatch.setattr(hashing, "open_regular_file_readonly", changed_open)
    result = hash_candidates([candidate], inspected)
    assert result.records == ()
    assert result.scan_errors[0].code == codes.SYS_CANDIDATE_CHANGED
    assert result.eligible_file_count == 1


def test_discovery_inspection_hashing_integration_detects_split_leakage(
    tmp_path: Path,
) -> None:
    train = tmp_path / "train" / "cats" / "a.jpg"
    validation = tmp_path / "validation" / "cats" / "b.jpg"
    train.parent.mkdir(parents=True)
    validation.parent.mkdir(parents=True)
    _save(train)
    validation.write_bytes(train.read_bytes())

    discovered = discover(tmp_path)
    inspected = inspect_candidates(discovered.candidates)
    result = hash_candidates(discovered.candidates, inspected)

    assert discovered.scan_errors == ()
    assert inspected.scan_errors == ()
    assert [finding.code for finding in result.findings] == [codes.DUP_ACROSS_SPLITS]
    assert result.findings[0].relative_path == "validation/cats/b.jpg"
    assert result.findings[0].evidence == {"matches": "train/cats/a.jpg"}
