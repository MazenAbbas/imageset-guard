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
from imageset_guard.terminal import render_terminal


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
