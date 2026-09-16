"""Tests for imageset_guard.profile: the streaming accumulator and
build_profile, which combines it with discovery's class_counts.
"""

from __future__ import annotations

from pathlib import Path

from imageset_guard.discovery_models import (
    ClassImageCount,
    DiscoveredImageCandidate,
    DiscoveryResult,
)
from imageset_guard.file_access import FileIdentity
from imageset_guard.inspection_models import CandidateInspection, InspectionResult
from imageset_guard.profile import ProfileAccumulator, build_profile


def _candidates(total: int) -> tuple[DiscoveredImageCandidate, ...]:
    return tuple(
        DiscoveredImageCandidate(
            absolute_path=Path.cwd() / "dataset" / "train" / "x" / f"{i}.jpg",
            relative_path=f"train/x/{i}.jpg",
            split="train",
            class_name="x",
            extension=".jpg",
        )
        for i in range(total)
    )


def _discovery(*counts: ClassImageCount, total_candidates: int = 0) -> DiscoveryResult:
    return DiscoveryResult(
        candidates=_candidates(total_candidates),
        findings=(),
        scan_errors=(),
        class_counts=counts,
    )


def _inspection(examined_file_count: int) -> InspectionResult:
    """Build an InspectionResult with exactly ``examined_file_count`` examined,
    path-distinct dummy inspections -- satisfying its own count invariant.
    """
    inspections = tuple(
        CandidateInspection(f"train/x/{i}.jpg", True, (), (), FileIdentity(1, i + 1, 1, 1))
        for i in range(examined_file_count)
    )
    return InspectionResult(
        inspections=inspections,
        findings=(),
        scan_errors=(),
        examined_file_count=examined_file_count,
    )


def test_accumulator_starts_empty() -> None:
    acc = ProfileAccumulator()
    assert acc.accepted_count == 0
    assert acc.format_counts == {}
    assert acc.width_bounds is None
    assert acc.aspect_ratio_bounds is None


def test_accumulator_tracks_bounds_and_counts_across_records() -> None:
    acc = ProfileAccumulator()
    acc.record_accepted(image_format="JPEG", mode="RGB", width=100, height=200)
    acc.record_accepted(image_format="PNG", mode="L", width=50, height=50)
    assert acc.accepted_count == 2
    assert acc.format_counts == {"JPEG": 1, "PNG": 1}
    assert acc.mode_counts == {"RGB": 1, "L": 1}
    assert acc.width_bounds == (50, 100)
    assert acc.height_bounds == (50, 200)
    lo, hi = acc.aspect_ratio_bounds  # type: ignore[misc]
    assert lo == 0.5  # 100/200
    assert hi == 1.0  # 50/50


def test_accumulator_properties_return_independent_copies() -> None:
    acc = ProfileAccumulator()
    acc.record_accepted(image_format="JPEG", mode="RGB", width=1, height=1)
    counts = acc.format_counts
    counts["JPEG"] = 999
    assert acc.format_counts == {"JPEG": 1}  # mutating the copy must not leak back


def test_build_profile_combines_class_counts_and_accumulator() -> None:
    discovery = _discovery(
        ClassImageCount(split="train", class_name="cats", candidate_count=2, is_complete=True),
        ClassImageCount(split="train", class_name="dogs", candidate_count=1, is_complete=True),
        ClassImageCount(
            split="validation", class_name="cats", candidate_count=0, is_complete=True
        ),
        total_candidates=3,
    )
    inspection = _inspection(examined_file_count=3)
    acc = ProfileAccumulator()
    acc.record_accepted(image_format="JPEG", mode="RGB", width=100, height=100)
    acc.record_accepted(image_format="JPEG", mode="RGB", width=200, height=100)
    acc.record_accepted(image_format="PNG", mode="RGBA", width=100, height=100)

    profile = build_profile(discovery, inspection, acc, scan_errors=())

    assert profile.candidate_count == 3
    assert profile.examined_count == 3
    assert profile.accepted_count == 3
    assert profile.rejected_count == 0
    assert profile.file_count_by_split == {"train": 3, "validation": 0}
    assert profile.file_count_by_class == {"cats": 2, "dogs": 1}
    assert profile.empty_classes == ("validation/cats",)
    assert profile.class_balance_ratio == 2.0  # cats=2, dogs=1
    assert profile.complete is True
    assert profile.width_min == 100 and profile.width_max == 200


def test_build_profile_marks_incomplete_when_any_subtree_is_incomplete() -> None:
    discovery = _discovery(
        ClassImageCount(split="train", class_name="cats", candidate_count=0, is_complete=False),
    )
    profile = build_profile(discovery, _inspection(0), ProfileAccumulator(), scan_errors=())
    assert profile.complete is False
    # An incomplete subtree's zero count must never be reported as "empty" --
    # we don't actually know that.
    assert profile.empty_classes == ()


def test_build_profile_marks_incomplete_when_scan_errors_exist() -> None:
    from imageset_guard.models import ScanError

    discovery = _discovery(
        ClassImageCount(split="train", class_name="cats", candidate_count=1, is_complete=True),
        total_candidates=1,
    )
    error = ScanError(
        code="SYS001", message="m", operation="open", relative_path="train/cats/a.jpg"
    )
    profile = build_profile(discovery, _inspection(1), ProfileAccumulator(), scan_errors=(error,))
    assert profile.complete is False


def test_build_profile_rejected_count_derived_from_examined_minus_accepted() -> None:
    discovery = _discovery(
        ClassImageCount(split="train", class_name="cats", candidate_count=2, is_complete=True),
        total_candidates=2,
    )
    acc = ProfileAccumulator()
    acc.record_accepted(image_format="JPEG", mode="RGB", width=10, height=10)
    profile = build_profile(discovery, _inspection(examined_file_count=2), acc, scan_errors=())
    assert profile.accepted_count == 1
    assert profile.rejected_count == 1


def test_build_profile_with_single_nonempty_class_has_no_balance_ratio() -> None:
    discovery = _discovery(
        ClassImageCount(split="train", class_name="cats", candidate_count=5, is_complete=True),
    )
    profile = build_profile(discovery, _inspection(0), ProfileAccumulator(), scan_errors=())
    assert profile.class_balance_ratio is None
