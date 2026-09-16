"""Contract tests for immutable Phase 3 inspection results."""

from __future__ import annotations

import pytest

from imageset_guard.file_access import FileIdentity
from imageset_guard.inspection_models import CandidateInspection, InspectionResult
from imageset_guard.models import Category, Finding, ScanError, Severity

_IDENTITY = FileIdentity(1, 2, 3, 4)


def _finding(path: str = "train/cats/a.jpg") -> Finding:
    return Finding(
        code="IMG003",
        severity=Severity.ERROR,
        category=Category.INTEGRITY,
        message="bad image",
        relative_path=path,
        remediation="replace it",
    )


def _error(path: str = "train/cats/a.jpg") -> ScanError:
    return ScanError(code="SYS002", message="gone", operation="open", relative_path=path)


def test_examined_candidate_may_have_findings_but_not_scan_errors() -> None:
    result = CandidateInspection("train/cats/a.jpg", True, (_finding(),), (), _IDENTITY)
    assert result.examined is True


def test_unexamined_candidate_requires_scan_error() -> None:
    result = CandidateInspection("train/cats/a.jpg", False, (), (_error(),), None)
    assert result.examined is False


@pytest.mark.parametrize(
    ("examined", "errors"),
    [(True, (_error(),)), (False, ())],
)
def test_candidate_rejects_inconsistent_examined_state(
    examined: bool, errors: tuple[ScanError, ...]
) -> None:
    with pytest.raises(ValueError):
        CandidateInspection(
            "train/cats/a.jpg", examined, (), errors, _IDENTITY if examined else None
        )


def test_candidate_rejects_result_for_a_different_path() -> None:
    with pytest.raises(ValueError, match="refer"):
        CandidateInspection(
            "train/cats/a.jpg", True, (_finding("train/cats/b.jpg"),), (), _IDENTITY
        )


def test_inspection_result_enforces_aggregate_and_count() -> None:
    inspected = CandidateInspection(
        "train/cats/a.jpg", True, (_finding(),), (), _IDENTITY
    )
    result = InspectionResult((inspected,), inspected.findings, (), 1)
    assert result.examined_file_count == 1

    with pytest.raises(ValueError, match="examined_file_count"):
        InspectionResult((inspected,), inspected.findings, (), 0)
    with pytest.raises(ValueError, match="aggregate"):
        InspectionResult((inspected,), (), (), 1)


def test_inspection_result_rejects_duplicate_candidate_paths() -> None:
    first = CandidateInspection("train/cats/a.jpg", True, (), (), _IDENTITY)
    with pytest.raises(ValueError, match="duplicate"):
        InspectionResult((first, first), (), (), 2)


@pytest.mark.parametrize(
    ("examined", "identity"),
    [(True, None), (False, _IDENTITY)],
)
def test_candidate_identity_presence_matches_examined_state(
    examined: bool, identity: FileIdentity | None
) -> None:
    errors = () if examined else (_error(),)
    with pytest.raises(ValueError, match="file identity"):
        CandidateInspection("train/cats/a.jpg", examined, (), errors, identity)
