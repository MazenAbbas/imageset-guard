"""Tests for the typed data models in imageset_guard.models.

These pin the exact contract described in the approved specification:
Finding / ScanError / ScanSummary / ScanResult schemas, the ERROR >
INCOMPLETE > FAIL > WARN > PASS precedence rule, and the fact that findings
describe dataset problems only (never operational failures).
"""

from __future__ import annotations

import pytest

from imageset_guard.models import (
    Category,
    Finding,
    ResultStatus,
    ScanError,
    ScanResult,
    ScanSummary,
    Severity,
    build_scan_result,
    combine_statuses,
)

# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


def test_finding_accepts_valid_integrity_finding() -> None:
    finding = Finding(
        code="IMG001",
        severity=Severity.ERROR,
        category=Category.INTEGRITY,
        message="Image file is empty",
        relative_path="train/cats/img001.jpg",
        evidence={"byte_size": 0},
        remediation="Remove or replace the empty file.",
    )
    assert finding.code == "IMG001"
    assert finding.relative_path == "train/cats/img001.jpg"
    assert finding.evidence == {"byte_size": 0}


def test_finding_relative_path_defaults_to_none() -> None:
    finding = Finding(
        code="SPLIT001",
        severity=Severity.WARNING,
        category=Category.STRUCTURE,
        message="Class 'dogs' is empty in split 'validation'",
        remediation="Add images or remove the empty class directory.",
    )
    assert finding.relative_path is None


@pytest.mark.parametrize(
    ("category", "bad_code"),
    [
        (Category.INTEGRITY, "PRIV001"),
        (Category.PRIVACY, "IMG001"),
        (Category.LEAKAGE, "SPLIT001"),
        (Category.STRUCTURE, "DUP001"),
        (Category.INTEGRITY, "IMG1"),
        (Category.INTEGRITY, "img001"),
    ],
)
def test_finding_rejects_code_that_does_not_match_category(
    category: Category, bad_code: str
) -> None:
    with pytest.raises(ValueError, match="code"):
        Finding(
            code=bad_code,
            severity=Severity.ERROR,
            category=category,
            message="x",
            remediation="x",
        )


def test_finding_rejects_absolute_relative_path() -> None:
    with pytest.raises(ValueError, match="relative_path"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            relative_path="/etc/passwd",
            remediation="x",
        )


def test_finding_rejects_windows_drive_relative_path() -> None:
    with pytest.raises(ValueError, match="relative_path"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            relative_path="C:/Users/someone/dataset/train/cats/a.jpg",
            remediation="x",
        )


def test_finding_rejects_backslash_in_relative_path() -> None:
    with pytest.raises(ValueError, match="relative_path"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            relative_path="train\\cats\\a.jpg",
            remediation="x",
        )


def test_finding_rejects_parent_traversal_in_relative_path() -> None:
    with pytest.raises(ValueError, match="relative_path"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            relative_path="../outside/a.jpg",
            remediation="x",
        )


def test_finding_rejects_empty_message() -> None:
    with pytest.raises(ValueError, match="message"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="",
            remediation="x",
        )


def test_finding_rejects_empty_remediation() -> None:
    with pytest.raises(ValueError, match="remediation"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            remediation="",
        )


def test_finding_rejects_nested_evidence_value() -> None:
    with pytest.raises(ValueError, match="evidence"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            evidence={"nested": {"a": 1}},  # type: ignore[dict-item]
            remediation="x",
        )


@pytest.mark.parametrize(
    "bad_value",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_finding_rejects_non_finite_evidence_float(bad_value: float) -> None:
    with pytest.raises(ValueError, match="evidence"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            evidence={"ratio": bad_value},
            remediation="x",
        )


def test_finding_rejects_empty_string_evidence_key() -> None:
    with pytest.raises(ValueError, match="evidence"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            evidence={"": 1},
            remediation="x",
        )


def test_finding_accepts_finite_float_evidence() -> None:
    finding = Finding(
        code="IMG001",
        severity=Severity.ERROR,
        category=Category.INTEGRITY,
        message="x",
        evidence={"ratio": 0.5},
        remediation="x",
    )
    assert finding.evidence["ratio"] == 0.5


def test_finding_evidence_is_immutable() -> None:
    finding = Finding(
        code="IMG001",
        severity=Severity.ERROR,
        category=Category.INTEGRITY,
        message="x",
        evidence={"byte_size": 0},
        remediation="x",
    )
    with pytest.raises(TypeError):
        finding.evidence["byte_size"] = 1  # type: ignore[index]


def test_finding_is_frozen() -> None:
    finding = Finding(
        code="IMG001",
        severity=Severity.ERROR,
        category=Category.INTEGRITY,
        message="x",
        remediation="x",
    )
    with pytest.raises(AttributeError):
        finding.message = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ScanError
# ---------------------------------------------------------------------------


def test_scan_error_accepts_valid_error() -> None:
    error = ScanError(
        code="SYS001",
        message="Permission denied",
        relative_path="train/cats/locked.jpg",
        operation="open",
    )
    assert error.code == "SYS001"
    assert error.operation == "open"


def test_scan_error_rejects_non_sys_code() -> None:
    with pytest.raises(ValueError, match="code"):
        ScanError(code="IMG001", message="x", operation="open")


def test_scan_error_rejects_absolute_relative_path() -> None:
    with pytest.raises(ValueError, match="relative_path"):
        ScanError(
            code="SYS001",
            message="x",
            relative_path="/etc/passwd",
            operation="open",
        )


def test_scan_error_rejects_unknown_operation() -> None:
    with pytest.raises(ValueError, match="operation"):
        ScanError(code="SYS001", message="x", operation="delete")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ResultStatus precedence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], ResultStatus.PASS),
        ([ResultStatus.PASS], ResultStatus.PASS),
        ([ResultStatus.PASS, ResultStatus.WARN], ResultStatus.WARN),
        ([ResultStatus.WARN, ResultStatus.FAIL], ResultStatus.FAIL),
        ([ResultStatus.FAIL, ResultStatus.INCOMPLETE], ResultStatus.INCOMPLETE),
        ([ResultStatus.INCOMPLETE, ResultStatus.ERROR], ResultStatus.ERROR),
        (
            [ResultStatus.PASS, ResultStatus.WARN, ResultStatus.FAIL,
             ResultStatus.INCOMPLETE, ResultStatus.ERROR],
            ResultStatus.ERROR,
        ),
        ([ResultStatus.FAIL, ResultStatus.WARN, ResultStatus.PASS], ResultStatus.FAIL),
        ([ResultStatus.ERROR], ResultStatus.ERROR),
        ([ResultStatus.INCOMPLETE, ResultStatus.WARN], ResultStatus.INCOMPLETE),
        ([ResultStatus.INCOMPLETE, ResultStatus.PASS], ResultStatus.INCOMPLETE),
    ],
)
def test_combine_statuses_precedence(
    statuses: list[ResultStatus], expected: ResultStatus
) -> None:
    assert combine_statuses(statuses) is expected


# ---------------------------------------------------------------------------
# build_scan_result
# ---------------------------------------------------------------------------


def _finding(severity: Severity, path: str = "a.jpg", code: str = "IMG001") -> Finding:
    return Finding(
        code=code,
        severity=severity,
        category=Category.INTEGRITY,
        message="m",
        relative_path=path,
        remediation="r",
    )


def _scan_error(path: str = "a.jpg") -> ScanError:
    return ScanError(code="SYS001", message="m", relative_path=path, operation="open")


def test_build_scan_result_pass_when_nothing_found() -> None:
    result = build_scan_result(findings=(), scan_errors=(), examined_file_count=5)
    assert result.status is ResultStatus.PASS
    assert result.summary.examined_file_count == 5
    assert result.summary.scan_error_count == 0
    assert result.summary.finding_counts_by_severity == {
        Severity.INFO: 0,
        Severity.WARNING: 0,
        Severity.ERROR: 0,
    }


def test_build_scan_result_warn_when_only_warnings() -> None:
    result = build_scan_result(
        findings=(_finding(Severity.WARNING),), scan_errors=(), examined_file_count=1
    )
    assert result.status is ResultStatus.WARN


def test_build_scan_result_fail_when_any_error_finding() -> None:
    result = build_scan_result(
        findings=(_finding(Severity.WARNING), _finding(Severity.ERROR)),
        scan_errors=(),
        examined_file_count=2,
    )
    assert result.status is ResultStatus.FAIL


def test_build_scan_result_incomplete_outranks_fail() -> None:
    result = build_scan_result(
        findings=(_finding(Severity.ERROR),),
        scan_errors=(_scan_error(),),
        examined_file_count=1,
    )
    assert result.status is ResultStatus.INCOMPLETE


def test_build_scan_result_never_produces_error_status() -> None:
    # ERROR is reserved for unexpected internal defects, decided outside
    # the normal findings/scan_errors flow -- build_scan_result must never
    # synthesize it on its own.
    result = build_scan_result(
        findings=(_finding(Severity.ERROR),),
        scan_errors=(_scan_error(),),
        examined_file_count=1,
    )
    assert result.status is not ResultStatus.ERROR


def test_build_scan_result_sorts_findings_deterministically() -> None:
    f_b = _finding(Severity.WARNING, path="b.jpg", code="IMG001")
    f_a = _finding(Severity.WARNING, path="a.jpg", code="IMG001")
    result = build_scan_result(findings=(f_b, f_a), scan_errors=(), examined_file_count=2)
    assert [f.relative_path for f in result.findings] == ["a.jpg", "b.jpg"]


def test_build_scan_result_sorts_scan_errors_deterministically() -> None:
    e_b = _scan_error(path="b.jpg")
    e_a = _scan_error(path="a.jpg")
    result = build_scan_result(
        findings=(), scan_errors=(e_b, e_a), examined_file_count=2
    )
    assert [e.relative_path for e in result.scan_errors] == ["a.jpg", "b.jpg"]


def test_scan_summary_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ScanSummary(
            examined_file_count=-1,
            finding_counts_by_severity={
                Severity.INFO: 0,
                Severity.WARNING: 0,
                Severity.ERROR: 0,
            },
            scan_error_count=0,
        )


def test_scan_summary_requires_all_severities() -> None:
    with pytest.raises(ValueError, match="Severity"):
        ScanSummary(
            examined_file_count=0,
            finding_counts_by_severity={Severity.INFO: 0},
            scan_error_count=0,
        )


# ---------------------------------------------------------------------------
# relative_path hardening
# ---------------------------------------------------------------------------


def test_finding_rejects_bare_dot_relative_path() -> None:
    with pytest.raises(ValueError, match="relative_path"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            relative_path=".",
            remediation="x",
        )


def test_finding_rejects_dot_segment_in_relative_path() -> None:
    with pytest.raises(ValueError, match="relative_path"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            relative_path="train/./cats.jpg",
            remediation="x",
        )


def test_finding_rejects_nul_character_in_relative_path() -> None:
    with pytest.raises(ValueError, match="relative_path"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            relative_path="train/cats/a\x00.jpg",
            remediation="x",
        )


@pytest.mark.parametrize("control_char", ["\x01", "\x07", "\x1f", "\x7f"])
def test_finding_rejects_control_characters_in_relative_path(control_char: str) -> None:
    with pytest.raises(ValueError, match="relative_path"):
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="x",
            relative_path=f"train/cats/a{control_char}.jpg",
            remediation="x",
        )


def test_finding_accepts_arabic_relative_path() -> None:
    finding = Finding(
        code="IMG001",
        severity=Severity.ERROR,
        category=Category.INTEGRITY,
        message="x",
        relative_path="train/قطط/صورة١.jpg",
        remediation="x",
    )
    assert finding.relative_path == "train/قطط/صورة١.jpg"


def test_finding_accepts_colon_not_in_drive_position() -> None:
    # Colons are valid on POSIX filesystems; only a leading drive-letter
    # pattern (e.g. "C:") is rejected, not colons in general.
    finding = Finding(
        code="IMG001",
        severity=Severity.ERROR,
        category=Category.INTEGRITY,
        message="x",
        relative_path="train/cats/photo:v2.jpg",
        remediation="x",
    )
    assert finding.relative_path == "train/cats/photo:v2.jpg"


# ---------------------------------------------------------------------------
# ScanResult invariants
# ---------------------------------------------------------------------------


def _valid_result() -> ScanResult:
    return build_scan_result(findings=(), scan_errors=(), examined_file_count=0)


def test_scan_result_rejects_error_status() -> None:
    valid = _valid_result()
    with pytest.raises(ValueError, match="ERROR"):
        ScanResult(
            status=ResultStatus.ERROR,
            findings=valid.findings,
            scan_errors=valid.scan_errors,
            summary=valid.summary,
        )


def test_scan_result_rejects_status_inconsistent_with_findings() -> None:
    finding = _finding(Severity.ERROR)  # should force FAIL
    with pytest.raises(ValueError, match="status"):
        ScanResult(
            status=ResultStatus.PASS,
            findings=(finding,),
            scan_errors=(),
            summary=ScanSummary(
                examined_file_count=1,
                finding_counts_by_severity={
                    Severity.INFO: 0,
                    Severity.WARNING: 0,
                    Severity.ERROR: 1,
                },
                scan_error_count=0,
            ),
        )


def test_scan_result_rejects_summary_finding_counts_mismatch() -> None:
    finding = _finding(Severity.WARNING)
    with pytest.raises(ValueError, match="summary"):
        ScanResult(
            status=ResultStatus.WARN,
            findings=(finding,),
            scan_errors=(),
            summary=ScanSummary(
                examined_file_count=1,
                finding_counts_by_severity={
                    Severity.INFO: 0,
                    Severity.WARNING: 0,  # wrong: should be 1
                    Severity.ERROR: 0,
                },
                scan_error_count=0,
            ),
        )


def test_scan_result_rejects_summary_scan_error_count_mismatch() -> None:
    error = _scan_error()
    with pytest.raises(ValueError, match="summary"):
        ScanResult(
            status=ResultStatus.INCOMPLETE,
            findings=(),
            scan_errors=(error,),
            summary=ScanSummary(
                examined_file_count=1,
                finding_counts_by_severity={
                    Severity.INFO: 0,
                    Severity.WARNING: 0,
                    Severity.ERROR: 0,
                },
                scan_error_count=0,  # wrong: should be 1
            ),
        )


def test_scan_result_rejects_unsorted_findings() -> None:
    finding_a = _finding(Severity.WARNING, path="a.jpg")
    finding_b = _finding(Severity.WARNING, path="b.jpg")
    with pytest.raises(ValueError, match=r"sorted|order"):
        ScanResult(
            status=ResultStatus.WARN,
            findings=(finding_b, finding_a),  # wrong order
            scan_errors=(),
            summary=ScanSummary(
                examined_file_count=2,
                finding_counts_by_severity={
                    Severity.INFO: 0,
                    Severity.WARNING: 2,
                    Severity.ERROR: 0,
                },
                scan_error_count=0,
            ),
        )


def test_scan_result_rejects_unsorted_scan_errors() -> None:
    error_a = _scan_error(path="a.jpg")
    error_b = _scan_error(path="b.jpg")
    with pytest.raises(ValueError, match=r"sorted|order"):
        ScanResult(
            status=ResultStatus.INCOMPLETE,
            findings=(),
            scan_errors=(error_b, error_a),  # wrong order
            summary=ScanSummary(
                examined_file_count=2,
                finding_counts_by_severity={
                    Severity.INFO: 0,
                    Severity.WARNING: 0,
                    Severity.ERROR: 0,
                },
                scan_error_count=2,
            ),
        )


def test_scan_result_accepts_consistent_construction() -> None:
    finding = _finding(Severity.WARNING, path="a.jpg")
    result = ScanResult(
        status=ResultStatus.WARN,
        findings=(finding,),
        scan_errors=(),
        summary=ScanSummary(
            examined_file_count=1,
            finding_counts_by_severity={
                Severity.INFO: 0,
                Severity.WARNING: 1,
                Severity.ERROR: 0,
            },
            scan_error_count=0,
        ),
    )
    assert result.status is ResultStatus.WARN
