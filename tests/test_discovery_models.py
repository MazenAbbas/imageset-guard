"""Tests for imageset_guard.discovery_models: typed, immutable discovery data.

Per the approved specification: absolute_path exists for internal use only
and must never leak into a report; relative_path/candidates/class_counts
must be canonically ordered and internally consistent, matching the same
discipline already enforced on ScanResult in imageset_guard.models.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from imageset_guard.discovery_models import (
    ClassImageCount,
    DiscoveredImageCandidate,
    DiscoveryResult,
)
from imageset_guard.models import Category, Finding, ScanError, Severity


def _candidate(
    relative_path: str = "train/cats/a.jpg",
    split: str = "train",
    class_name: str = "cats",
    extension: str = ".jpg",
    absolute_path: Path | None = None,
) -> DiscoveredImageCandidate:
    return DiscoveredImageCandidate(
        absolute_path=absolute_path or Path.cwd() / "dataset" / relative_path,
        relative_path=relative_path,
        split=split,
        class_name=class_name,
        extension=extension,
    )


def test_candidate_accepts_valid_values() -> None:
    candidate = _candidate()
    assert candidate.relative_path == "train/cats/a.jpg"
    assert candidate.split == "train"
    assert candidate.class_name == "cats"
    assert candidate.extension == ".jpg"


def test_candidate_is_frozen() -> None:
    candidate = _candidate()
    with pytest.raises(AttributeError):
        candidate.class_name = "dogs"  # type: ignore[misc]


def test_candidate_rejects_relative_absolute_path() -> None:
    with pytest.raises(ValueError, match="absolute_path"):
        DiscoveredImageCandidate(
            absolute_path=Path("relative/dataset/train/cats/a.jpg"),
            relative_path="train/cats/a.jpg",
            split="train",
            class_name="cats",
            extension=".jpg",
        )


def test_candidate_rejects_invalid_relative_path() -> None:
    with pytest.raises(ValueError, match="relative_path"):
        _candidate(relative_path="/absolute/train/cats/a.jpg")


@pytest.mark.parametrize("bad_split", ["", "TRAIN", "trains", "train/"])
def test_candidate_rejects_invalid_split(bad_split: str) -> None:
    with pytest.raises(ValueError, match="split"):
        _candidate(split=bad_split)


@pytest.mark.parametrize("bad_split", [[], {}, set(), 1, None, ("train",)])
def test_candidate_rejects_unhashable_or_non_str_split(bad_split: object) -> None:
    # Comparing an unhashable value against a frozenset membership check
    # must not leak a TypeError -- it's still just an invalid split.
    with pytest.raises(ValueError, match="split"):
        _candidate(split=bad_split)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_class_name", ["", "cats/nested", "cats\\nested", ".", "..", "a\nb"])
def test_candidate_rejects_invalid_class_name(bad_class_name: str) -> None:
    with pytest.raises(ValueError, match="class_name"):
        _candidate(class_name=bad_class_name)


def test_candidate_rejects_non_string_class_name() -> None:
    with pytest.raises(ValueError, match="class_name"):
        _candidate(class_name=None)  # type: ignore[arg-type]


def test_candidate_rejects_non_string_relative_path() -> None:
    with pytest.raises(ValueError, match="relative_path"):
        DiscoveredImageCandidate(
            absolute_path=Path.cwd() / "dataset" / "train" / "cats" / "a.jpg",
            relative_path=None,  # type: ignore[arg-type]
            split="train",
            class_name="cats",
            extension=".jpg",
        )


def test_candidate_rejects_non_string_extension() -> None:
    with pytest.raises(ValueError, match="extension"):
        _candidate(extension=None)  # type: ignore[arg-type]


def test_candidate_rejects_non_path_absolute_path() -> None:
    with pytest.raises(ValueError, match="absolute_path"):
        DiscoveredImageCandidate(
            absolute_path="/not/a/path/object",  # type: ignore[arg-type]
            relative_path="train/cats/a.jpg",
            split="train",
            class_name="cats",
            extension=".jpg",
        )


@pytest.mark.parametrize("extension", [".jpg", ".jpeg", ".png", ".webp"])
def test_candidate_accepts_canonical_extensions(extension: str) -> None:
    candidate = _candidate(extension=extension)
    assert candidate.extension == extension


@pytest.mark.parametrize(
    "bad_extension",
    [
        "",
        "jpg",
        ".JPG.",
        "jpg.",
        ".JPG",
        ".Jpeg",
        ".PNG",
        ".WEBP",
        ".jpg/evil",
        ".jpg\\evil",
        ".gif",
        ".bmp",
        ".tiff",
        ".jpg\n",
        123,
        None,
        [".jpg"],
    ],
)
def test_candidate_rejects_non_canonical_extension(bad_extension: object) -> None:
    with pytest.raises(ValueError, match="extension"):
        _candidate(extension=bad_extension)  # type: ignore[arg-type]


def test_candidate_has_no_public_serialization_helper() -> None:
    # Deliberately no to_dict()/asdict_public()/to_json() convenience: any
    # caller building a report must explicitly select safe fields rather
    # than being tempted to serialize this object (and its absolute_path)
    # wholesale.
    candidate = _candidate()
    for forbidden_attr in ("to_dict", "asdict_public", "to_json", "as_dict"):
        assert not hasattr(candidate, forbidden_attr)


def test_dataclasses_asdict_would_leak_absolute_path_so_callers_must_not_use_it() -> None:
    # Documents the real risk this design guards against: dataclasses.asdict
    # is generic stdlib machinery, not something this module can block, so
    # nothing in this codebase may call it on a DiscoveredImageCandidate.
    candidate = _candidate()
    leaky = dataclasses.asdict(candidate)
    assert "absolute_path" in leaky


# ---------------------------------------------------------------------------
# ClassImageCount
# ---------------------------------------------------------------------------


def test_class_image_count_accepts_valid_values() -> None:
    count = ClassImageCount(split="train", class_name="cats", candidate_count=3, is_complete=True)
    assert count.candidate_count == 3
    assert count.is_complete is True


def test_class_image_count_rejects_negative_count() -> None:
    with pytest.raises(ValueError, match="candidate_count"):
        ClassImageCount(split="train", class_name="cats", candidate_count=-1, is_complete=True)


def test_class_image_count_records_incompleteness_explicitly() -> None:
    # is_complete has no default: every call site must consciously decide
    # whether this count is a confirmed total or a partial/best-effort one.
    count = ClassImageCount(split="train", class_name="cats", candidate_count=1, is_complete=False)
    assert count.is_complete is False


@pytest.mark.parametrize("bad_is_complete", ["false", None, 0, 1])
def test_class_image_count_rejects_non_bool_is_complete(bad_is_complete: object) -> None:
    with pytest.raises(ValueError, match="is_complete"):
        ClassImageCount(
            split="train",
            class_name="cats",
            candidate_count=1,
            is_complete=bad_is_complete,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("bad_count", [True, False, 1.0, "1"])
def test_class_image_count_rejects_non_int_candidate_count(bad_count: object) -> None:
    with pytest.raises(ValueError, match="candidate_count"):
        ClassImageCount(
            split="train",
            class_name="cats",
            candidate_count=bad_count,  # type: ignore[arg-type]
            is_complete=True,
        )


@pytest.mark.parametrize("bad_split", ["", "TRAIN", "trains", "train/"])
def test_class_image_count_rejects_invalid_split(bad_split: str) -> None:
    with pytest.raises(ValueError, match="split"):
        ClassImageCount(split=bad_split, class_name="cats", candidate_count=1, is_complete=True)


@pytest.mark.parametrize("bad_split", [[], {}, set(), 1, None, ("train",)])
def test_class_image_count_rejects_unhashable_or_non_str_split(bad_split: object) -> None:
    with pytest.raises(ValueError, match="split"):
        ClassImageCount(
            split=bad_split,  # type: ignore[arg-type]
            class_name="cats",
            candidate_count=1,
            is_complete=True,
        )


@pytest.mark.parametrize(
    "bad_class_name", ["", "cats/nested", "cats\\nested", ".", "..", "a\nb", None]
)
def test_class_image_count_rejects_invalid_class_name(bad_class_name: object) -> None:
    with pytest.raises(ValueError, match="class_name"):
        ClassImageCount(
            split="train",
            class_name=bad_class_name,  # type: ignore[arg-type]
            candidate_count=1,
            is_complete=True,
        )


# ---------------------------------------------------------------------------
# DiscoveryResult
# ---------------------------------------------------------------------------


def _finding(path: str = "train", code: str = "SPLIT004") -> Finding:
    return Finding(
        code=code,
        severity=Severity.WARNING,
        category=Category.STRUCTURE,
        message="m",
        relative_path=path,
        remediation="r",
    )


def _scan_error(path: str = "train") -> ScanError:
    return ScanError(code="SYS001", message="m", relative_path=path, operation="open")


def test_discovery_result_accepts_consistent_construction() -> None:
    candidate = _candidate()
    count = ClassImageCount(split="train", class_name="cats", candidate_count=1, is_complete=True)
    result = DiscoveryResult(
        candidates=(candidate,),
        findings=(),
        scan_errors=(),
        class_counts=(count,),
    )
    assert result.candidates == (candidate,)


def test_discovery_result_rejects_unsorted_candidates() -> None:
    candidate_b = _candidate(relative_path="train/cats/b.jpg")
    candidate_a = _candidate(relative_path="train/cats/a.jpg")
    with pytest.raises(ValueError, match=r"sorted|order"):
        DiscoveryResult(
            candidates=(candidate_b, candidate_a),
            findings=(),
            scan_errors=(),
            class_counts=(),
        )


def test_discovery_result_rejects_duplicate_candidate_relative_path() -> None:
    candidate_1 = _candidate(relative_path="train/cats/a.jpg")
    candidate_2 = _candidate(relative_path="train/cats/a.jpg")
    with pytest.raises(ValueError, match="duplicate"):
        DiscoveryResult(
            candidates=(candidate_1, candidate_2),
            findings=(),
            scan_errors=(),
            class_counts=(),
        )


def test_discovery_result_rejects_unsorted_findings() -> None:
    finding_b = _finding(path="b")
    finding_a = _finding(path="a")
    with pytest.raises(ValueError, match=r"sorted|order"):
        DiscoveryResult(
            candidates=(),
            findings=(finding_b, finding_a),
            scan_errors=(),
            class_counts=(),
        )


def test_discovery_result_rejects_unsorted_scan_errors() -> None:
    error_b = _scan_error(path="b")
    error_a = _scan_error(path="a")
    with pytest.raises(ValueError, match=r"sorted|order"):
        DiscoveryResult(
            candidates=(),
            findings=(),
            scan_errors=(error_b, error_a),
            class_counts=(),
        )


def test_discovery_result_rejects_unsorted_class_counts() -> None:
    count_b = ClassImageCount(split="train", class_name="dogs", candidate_count=1, is_complete=True)
    count_a = ClassImageCount(split="train", class_name="cats", candidate_count=1, is_complete=True)
    with pytest.raises(ValueError, match=r"sorted|order"):
        DiscoveryResult(
            candidates=(),
            findings=(),
            scan_errors=(),
            class_counts=(count_b, count_a),
        )


def test_discovery_result_rejects_duplicate_class_counts() -> None:
    count_1 = ClassImageCount(split="train", class_name="cats", candidate_count=1, is_complete=True)
    count_2 = ClassImageCount(split="train", class_name="cats", candidate_count=2, is_complete=True)
    with pytest.raises(ValueError, match="duplicate"):
        DiscoveryResult(
            candidates=(),
            findings=(),
            scan_errors=(),
            class_counts=(count_1, count_2),
        )
