"""Tests for imageset_guard.terminal: the plain-text human-readable renderer.

No external dependency; deterministic given a ScanResult (which already
carries its findings/scan_errors in sorted order).
"""

from __future__ import annotations

from imageset_guard.models import (
    Category,
    Finding,
    ScanError,
    Severity,
    build_scan_result,
)
from imageset_guard.profile_models import DatasetProfile
from imageset_guard.terminal import render_terminal


def _profile(**overrides: object) -> DatasetProfile:
    defaults: dict[str, object] = {
        "candidate_count": 2,
        "examined_count": 2,
        "accepted_count": 2,
        "rejected_count": 0,
        "file_count_by_split": {"train": 2},
        "file_count_by_class": {"cats": 1, "dogs": 1},
        "format_counts": {"JPEG": 2},
        "mode_counts": {"RGB": 2},
        "width_min": 10,
        "width_max": 20,
        "height_min": 10,
        "height_max": 20,
        "aspect_ratio_min": 1.0,
        "aspect_ratio_max": 1.0,
        "empty_classes": (),
        "class_balance_ratio": 1.0,
        "complete": True,
    }
    defaults.update(overrides)
    return DatasetProfile(**defaults)  # type: ignore[arg-type]


def test_render_terminal_pass_mentions_status_and_zero_counts() -> None:
    result = build_scan_result(findings=(), scan_errors=(), examined_file_count=4)
    text = render_terminal(result)
    assert "PASS" in text
    assert "4" in text


def test_render_terminal_lists_each_finding() -> None:
    finding = Finding(
        code="IMG001",
        severity=Severity.ERROR,
        category=Category.INTEGRITY,
        message="Image file is empty",
        relative_path="train/cats/a.jpg",
        remediation="Remove or replace the empty file.",
    )
    result = build_scan_result(findings=(finding,), scan_errors=(), examined_file_count=1)
    text = render_terminal(result)
    assert "IMG001" in text
    assert "train/cats/a.jpg" in text
    assert "Image file is empty" in text
    assert "FAIL" in text


def test_render_terminal_lists_each_scan_error_and_shows_incomplete() -> None:
    error = ScanError(
        code="SYS001",
        message="Permission denied",
        relative_path="train/dogs/locked.jpg",
        operation="open",
    )
    result = build_scan_result(findings=(), scan_errors=(error,), examined_file_count=1)
    text = render_terminal(result)
    assert "SYS001" in text
    assert "train/dogs/locked.jpg" in text
    assert "Permission denied" in text
    assert "INCOMPLETE" in text


def test_render_terminal_is_deterministic() -> None:
    finding_a = Finding(
        code="IMG001",
        severity=Severity.WARNING,
        category=Category.INTEGRITY,
        message="a",
        relative_path="a.jpg",
        remediation="r",
    )
    finding_b = Finding(
        code="IMG001",
        severity=Severity.WARNING,
        category=Category.INTEGRITY,
        message="b",
        relative_path="b.jpg",
        remediation="r",
    )
    result = build_scan_result(
        findings=(finding_b, finding_a), scan_errors=(), examined_file_count=2
    )
    assert render_terminal(result) == render_terminal(result)


def test_render_terminal_never_includes_absolute_paths() -> None:
    finding = Finding(
        code="IMG001",
        severity=Severity.WARNING,
        category=Category.INTEGRITY,
        message="m",
        relative_path="train/cats/a.jpg",
        remediation="r",
    )
    result = build_scan_result(findings=(finding,), scan_errors=(), examined_file_count=1)
    text = render_terminal(result)
    assert "C:\\" not in text
    assert not any(line.strip().startswith("/") for line in text.splitlines())


def test_render_terminal_without_profile_omits_profile_section() -> None:
    result = build_scan_result(findings=(), scan_errors=(), examined_file_count=0)
    assert "Profile:" not in render_terminal(result)


def test_render_terminal_with_profile_shows_split_and_class_facts() -> None:
    result = build_scan_result(findings=(), scan_errors=(), examined_file_count=2)
    text = render_terminal(result, _profile())
    assert "Profile:" in text
    assert "train=2" in text
    assert "Classes: 2" in text
    assert "JPEG=2" in text
    assert "10-20" in text


def test_render_terminal_shows_empty_classes_when_present() -> None:
    result = build_scan_result(findings=(), scan_errors=(), examined_file_count=0)
    profile = _profile(
        accepted_count=0,
        rejected_count=0,
        examined_count=0,
        file_count_by_class={"cats": 0},
        format_counts={},
        mode_counts={},
        width_min=None,
        width_max=None,
        height_min=None,
        height_max=None,
        aspect_ratio_min=None,
        aspect_ratio_max=None,
        empty_classes=("train/cats",),
        class_balance_ratio=None,
    )
    text = render_terminal(result, profile)
    assert "Empty classes: train/cats" in text


def test_render_terminal_flags_incomplete_profile() -> None:
    result = build_scan_result(findings=(), scan_errors=(), examined_file_count=2)
    profile = _profile(complete=False)
    text = render_terminal(result, profile)
    assert "Incomplete" in text
