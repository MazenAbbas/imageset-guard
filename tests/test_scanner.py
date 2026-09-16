"""End-to-end composition tests for the real scan engine."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

import pytest
from PIL import Image

from imageset_guard import codes, scanner
from imageset_guard.discovery_models import DiscoveredImageCandidate
from imageset_guard.inspection import inspect_candidates as real_inspect_candidates
from imageset_guard.inspection_models import InspectionResult
from imageset_guard.models import ResultStatus
from imageset_guard.policy import Policy
from imageset_guard.scanner import scan_dataset
from imageset_guard.serialization import serialize_scan_result


def _save(path: Path, color: str = "red", *, size: tuple[int, int] = (5, 5)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG")


def test_valid_unique_dataset_passes_without_modifying_files(tmp_path: Path) -> None:
    image = tmp_path / "train" / "cats" / "a.jpg"
    _save(image)
    before = hashlib.sha256(image.read_bytes()).digest()
    result = scan_dataset(tmp_path)
    after = hashlib.sha256(image.read_bytes()).digest()
    assert result.status is ResultStatus.PASS
    assert result.summary.examined_file_count == 1
    assert before == after


def test_invalid_image_and_exact_split_duplicate_reach_one_result(tmp_path: Path) -> None:
    train = tmp_path / "train" / "cats" / "a.jpg"
    validation = tmp_path / "validation" / "cats" / "b.jpg"
    invalid = tmp_path / "train" / "cats" / "bad.jpg"
    _save(train)
    validation.parent.mkdir(parents=True)
    validation.write_bytes(train.read_bytes())
    invalid.write_bytes(b"not an image")

    result = scan_dataset(tmp_path)
    assert result.status is ResultStatus.FAIL
    assert {finding.code for finding in result.findings} == {
        codes.IMG_UNIDENTIFIED_IMAGE,
        codes.DUP_ACROSS_SPLITS,
    }
    assert result.summary.examined_file_count == 3


def test_policy_is_applied_by_composed_engine(tmp_path: Path) -> None:
    image = tmp_path / "train" / "cats" / "large.jpg"
    _save(image, size=(10, 10))
    result = scan_dataset(tmp_path, Policy(max_pixels=50))
    assert [finding.code for finding in result.findings] == [codes.IMG_PIXEL_LIMIT_EXCEEDED]


def test_report_has_no_absolute_path_or_internal_digest(tmp_path: Path) -> None:
    first = tmp_path / "train" / "cats" / "a.jpg"
    second = tmp_path / "test" / "cats" / "b.jpg"
    _save(first)
    second.parent.mkdir(parents=True)
    second.write_bytes(first.read_bytes())
    payload = serialize_scan_result(scan_dataset(tmp_path)).decode("utf-8")
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    assert str(tmp_path) not in payload
    assert digest not in payload


def test_scan_result_is_byte_deterministic(tmp_path: Path) -> None:
    _save(tmp_path / "train" / "cats" / "a.jpg")
    first = serialize_scan_result(scan_dataset(tmp_path))
    second = serialize_scan_result(scan_dataset(tmp_path))
    assert first == second


def test_replacement_between_inspection_and_hashing_makes_scan_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "train" / "cats" / "a.jpg"
    _save(image, "red")
    def inspect_then_replace(
        candidates: Iterable[DiscoveredImageCandidate], policy: Policy | None = None
    ) -> InspectionResult:
        result = real_inspect_candidates(candidates, policy)
        replacement = tmp_path / "replacement.jpg"
        _save(replacement, "blue")
        replacement.replace(image)
        return result

    monkeypatch.setattr(scanner, "inspect_candidates", inspect_then_replace)
    result = scan_dataset(tmp_path)
    assert result.status is ResultStatus.INCOMPLETE
    assert [error.code for error in result.scan_errors] == [codes.SYS_CANDIDATE_CHANGED]
    assert result.findings == ()
