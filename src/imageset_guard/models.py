"""Typed data models for scan results.

These types describe *what a scan found*, never *how the tool is running*.
Nothing here carries a timestamp, an absolute path, a username, or version
metadata -- see ``imageset_guard.serialization`` for why that matters.

Findings describe dataset problems only. Operational failures (permission
denied, a file disappearing mid-scan, and similar) are represented by
``ScanError`` instead, and always push the overall result to ``INCOMPLETE``
-- see ``build_scan_result``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final, Literal

EvidenceValue = str | int | float | bool
Operation = Literal["stat", "open", "read", "walk"]

_KNOWN_OPERATIONS: Final[frozenset[str]] = frozenset({"stat", "open", "read", "walk"})


class Severity(Enum):
    """Severity of a single :class:`Finding`."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Category(Enum):
    """Category of a single :class:`Finding`, tied to its code prefix."""

    INTEGRITY = "integrity"
    PRIVACY = "privacy"
    LEAKAGE = "leakage"
    STRUCTURE = "structure"


_CODE_PREFIX_BY_CATEGORY: Final[dict[Category, str]] = {
    Category.INTEGRITY: "IMG",
    Category.PRIVACY: "PRIV",
    Category.LEAKAGE: "DUP",
    Category.STRUCTURE: "SPLIT",
}

_SCAN_ERROR_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^SYS\d{3}$")


class ResultStatus(Enum):
    """Overall outcome of a scan.

    Ordered by precedence, lowest first. ``combine_statuses`` picks the
    highest-precedence status among a set of candidates. ``ERROR`` is
    reserved for unexpected internal defects and is never produced by
    :func:`build_scan_result` -- only a caller reacting to an unhandled
    exception may report it.
    """

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    INCOMPLETE = "incomplete"
    ERROR = "error"

    @property
    def precedence(self) -> int:
        return _STATUS_PRECEDENCE[self]


_STATUS_PRECEDENCE: Final[dict[ResultStatus, int]] = {
    ResultStatus.PASS: 0,
    ResultStatus.WARN: 1,
    ResultStatus.FAIL: 2,
    ResultStatus.INCOMPLETE: 3,
    ResultStatus.ERROR: 4,
}


def combine_statuses(statuses: Sequence[ResultStatus] | list[ResultStatus]) -> ResultStatus:
    """Return the highest-precedence status among ``statuses``.

    An empty sequence combines to ``PASS`` (the identity element): "nothing
    to report" is the same as "nothing was wrong".
    """
    result = ResultStatus.PASS
    for status in statuses:
        if status.precedence > result.precedence:
            result = status
    return result


def validate_relative_path(value: str | None, *, field_name: str = "relative_path") -> None:
    if value is None:
        return
    if value == "":
        raise ValueError(f"{field_name} must not be empty; use None for 'no path'")
    if "\\" in value:
        raise ValueError(f"{field_name} must use forward slashes, got: {value!r}")
    if value.startswith("/"):
        raise ValueError(f"{field_name} must be relative, got absolute path: {value!r}")
    if re.match(r"^[A-Za-z]:", value):
        raise ValueError(f"{field_name} must be relative, got a drive path: {value!r}")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError(f"{field_name} must not contain control characters: {value!r}")
    # Colons are otherwise allowed: they are valid on POSIX filesystems, and
    # only the drive-letter pattern above is a portability concern here.
    # Windows-specific reserved-name portability is a discovery-time finding
    # (Phase 2), not part of this canonical relative-path contract.
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(
            f"{field_name} must not contain '.', '..', or empty segments: {value!r}"
        )


def _freeze_evidence(evidence: Mapping[str, EvidenceValue]) -> Mapping[str, EvidenceValue]:
    for key, value in evidence.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"evidence keys must be non-empty strings, got: {key!r}")
        if not isinstance(value, str | int | float | bool):
            raise ValueError(
                f"evidence values must be flat scalars (str/int/float/bool); "
                f"key {key!r} has {type(value).__name__}"
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(
                f"evidence values must be finite; key {key!r} has non-finite float {value!r}"
            )
    return MappingProxyType(dict(evidence))


@dataclass(frozen=True, slots=True)
class Finding:
    """A single, dataset-only observation produced by a scan.

    ``evidence`` must stay small and non-sensitive: flat scalars only, no
    nested structures, and never a raw sensitive value (e.g. GPS
    coordinates) -- only facts like "a GPS tag is present".
    """

    code: str
    severity: Severity
    category: Category
    message: str
    relative_path: str | None = None
    evidence: Mapping[str, EvidenceValue] = field(default_factory=dict)
    remediation: str = ""

    def __post_init__(self) -> None:
        expected_prefix = _CODE_PREFIX_BY_CATEGORY[self.category]
        if not re.match(rf"^{expected_prefix}\d{{3}}$", self.code):
            raise ValueError(
                f"code {self.code!r} does not match category {self.category.value!r} "
                f"(expected pattern {expected_prefix}###)"
            )
        if not self.message:
            raise ValueError("message must not be empty")
        if not self.remediation:
            raise ValueError("remediation must not be empty")
        validate_relative_path(self.relative_path)
        object.__setattr__(self, "evidence", _freeze_evidence(self.evidence))


@dataclass(frozen=True, slots=True)
class ScanError:
    """A single operational failure that prevented examining a file.

    Distinct from :class:`Finding`: this describes a failure of the *scan*
    (permission denied, a file disappearing, etc.), not a property of the
    dataset. Any ``ScanError`` forces the overall result to ``INCOMPLETE``.
    """

    code: str
    message: str
    operation: Operation
    relative_path: str | None = None

    def __post_init__(self) -> None:
        if not _SCAN_ERROR_CODE_PATTERN.match(self.code):
            raise ValueError(f"code {self.code!r} must match pattern SYS###")
        if not self.message:
            raise ValueError("message must not be empty")
        if self.operation not in _KNOWN_OPERATIONS:
            raise ValueError(
                f"operation {self.operation!r} is not one of {sorted(_KNOWN_OPERATIONS)}"
            )
        validate_relative_path(self.relative_path)


@dataclass(frozen=True, slots=True)
class ScanSummary:
    """Aggregate counts for a scan. Contains no non-deterministic data."""

    examined_file_count: int
    finding_counts_by_severity: Mapping[Severity, int]
    scan_error_count: int

    def __post_init__(self) -> None:
        if self.examined_file_count < 0:
            raise ValueError("examined_file_count must be non-negative")
        if self.scan_error_count < 0:
            raise ValueError("scan_error_count must be non-negative")
        if set(self.finding_counts_by_severity) != set(Severity):
            raise ValueError(
                "finding_counts_by_severity must have exactly one entry per Severity"
            )
        for severity, count in self.finding_counts_by_severity.items():
            if count < 0:
                raise ValueError(f"count for {severity} must be non-negative")
        object.__setattr__(
            self,
            "finding_counts_by_severity",
            MappingProxyType(dict(self.finding_counts_by_severity)),
        )


def finding_sort_key(finding: Finding) -> tuple[str, str, str]:
    return (finding.relative_path or "", finding.code, finding.message)


def scan_error_sort_key(error: ScanError) -> tuple[str, str, str]:
    return (error.relative_path or "", error.code, error.operation)


def _derive_status(
    findings: Sequence[Finding], scan_errors: Sequence[ScanError]
) -> ResultStatus:
    """Derive the non-``ERROR`` status implied by ``findings``/``scan_errors``.

    ``ERROR`` is deliberately never a candidate here: it represents an
    unexpected internal defect, not a property of any dataset, and is
    never a valid :class:`ScanResult` status at all -- see
    ``ScanResult.__post_init__``.
    """
    candidates = [ResultStatus.PASS]
    if scan_errors:
        candidates.append(ResultStatus.INCOMPLETE)
    if any(f.severity is Severity.ERROR for f in findings):
        candidates.append(ResultStatus.FAIL)
    if any(f.severity is Severity.WARNING for f in findings):
        candidates.append(ResultStatus.WARN)
    return combine_statuses(candidates)


def _finding_counts(findings: Sequence[Finding]) -> dict[Severity, int]:
    counts = dict.fromkeys(Severity, 0)
    for f in findings:
        counts[f.severity] += 1
    return counts


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The complete, canonical outcome of a scan.

    Construction enforces internal consistency: ``status`` must be exactly
    what ``findings``/``scan_errors`` imply (and can never be ``ERROR`` --
    that status describes a tool defect, not a scan result), ``summary``'s
    counts must match ``findings``/``scan_errors`` exactly, and both
    sequences must already be in their canonical sorted order. There is no
    way to construct an inconsistent ``ScanResult``; :func:`build_scan_result`
    is simply the convenient path that computes all of this for you.

    Deliberately *not* enforced: any relationship between
    ``summary.examined_file_count`` and the distinct paths mentioned in
    ``findings``/``scan_errors``. A ``relative_path`` is not yet
    contractually guaranteed to always name exactly one file rather than,
    say, a class directory referenced by a structure finding -- that
    guarantee belongs to the discovery layer (Phase 2). Asserting a bound
    here now would encode an assumption about path semantics that hasn't
    been fixed yet.
    """

    status: ResultStatus
    findings: tuple[Finding, ...]
    scan_errors: tuple[ScanError, ...]
    summary: ScanSummary

    def __post_init__(self) -> None:
        if self.status is ResultStatus.ERROR:
            raise ValueError(
                "ResultStatus.ERROR is not a valid ScanResult status; it represents "
                "an unexpected internal defect outside of any scan result"
            )

        expected_status = _derive_status(self.findings, self.scan_errors)
        if self.status is not expected_status:
            raise ValueError(
                f"status {self.status!r} is inconsistent with findings/scan_errors "
                f"(expected {expected_status!r})"
            )

        expected_counts = _finding_counts(self.findings)
        if dict(self.summary.finding_counts_by_severity) != expected_counts:
            raise ValueError(
                "summary.finding_counts_by_severity does not match findings: "
                f"expected {expected_counts}, got "
                f"{dict(self.summary.finding_counts_by_severity)}"
            )
        if self.summary.scan_error_count != len(self.scan_errors):
            raise ValueError(
                "summary.scan_error_count does not match scan_errors: "
                f"expected {len(self.scan_errors)}, got {self.summary.scan_error_count}"
            )

        expected_findings_order = tuple(sorted(self.findings, key=finding_sort_key))
        if self.findings != expected_findings_order:
            raise ValueError("findings must already be in their canonical sorted order")

        expected_scan_errors_order = tuple(sorted(self.scan_errors, key=scan_error_sort_key))
        if self.scan_errors != expected_scan_errors_order:
            raise ValueError("scan_errors must already be in their canonical sorted order")


def build_scan_result(
    *,
    findings: Sequence[Finding],
    scan_errors: Sequence[ScanError],
    examined_file_count: int,
) -> ScanResult:
    """Build a :class:`ScanResult`, deriving its status and summary for you.

    This is the convenient construction path; it is not the only valid one
    -- ``ScanResult`` itself enforces the same consistency rules on any
    direct construction. Status derivation never produces
    ``ResultStatus.ERROR``: that status is reserved for unexpected internal
    defects handled outside this function, at the point where an unhandled
    exception is caught.
    """
    status = _derive_status(findings, scan_errors)

    summary = ScanSummary(
        examined_file_count=examined_file_count,
        finding_counts_by_severity=_finding_counts(findings),
        scan_error_count=len(scan_errors),
    )

    sorted_findings = tuple(sorted(findings, key=finding_sort_key))
    sorted_scan_errors = tuple(sorted(scan_errors, key=scan_error_sort_key))

    return ScanResult(
        status=status,
        findings=sorted_findings,
        scan_errors=sorted_scan_errors,
        summary=summary,
    )
