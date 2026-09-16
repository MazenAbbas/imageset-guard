"""Immutable results produced by image-content inspection.

These models intentionally contain no absolute paths, exception strings,
timestamps, EXIF values, or pixel data.  The candidate's absolute path remains
an input-only implementation detail used while its file descriptor is open.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from imageset_guard.file_access import FileIdentity
from imageset_guard.models import (
    Finding,
    ScanError,
    finding_sort_key,
    scan_error_sort_key,
    validate_relative_path,
)

_T = TypeVar("_T")
_K = TypeVar("_K", bound="str | tuple[str, ...]")


def _require_canonical(items: Sequence[_T], *, key: Callable[[_T], _K], name: str) -> None:
    if list(items) != sorted(items, key=key):
        raise ValueError(f"{name} must already be in canonical sorted order")


@dataclass(frozen=True, slots=True)
class CandidateInspection:
    """The integrity/privacy outcome for one discovered candidate.

    ``examined`` means inspection reached a deterministic conclusion about the
    file's data.  Invalid, oversized, and unsupported multi-frame images count
    as examined.  A candidate blocked by an operational filesystem failure does
    not, and therefore has one or more ``scan_errors``.
    """

    relative_path: str
    examined: bool
    findings: tuple[Finding, ...]
    scan_errors: tuple[ScanError, ...]
    file_identity: FileIdentity | None = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.relative_path, str):
            raise ValueError("relative_path must be a str")
        validate_relative_path(self.relative_path)
        if not isinstance(self.examined, bool):
            raise ValueError("examined must be a bool")
        _require_canonical(self.findings, key=finding_sort_key, name="findings")
        _require_canonical(self.scan_errors, key=scan_error_sort_key, name="scan_errors")
        if self.examined and self.scan_errors:
            raise ValueError("an examined candidate must not contain scan_errors")
        if not self.examined and not self.scan_errors:
            raise ValueError("an unexamined candidate must contain a scan_error")
        if self.examined and self.file_identity is None:
            raise ValueError("an examined candidate must carry its file identity")
        if not self.examined and self.file_identity is not None:
            raise ValueError("an unexamined candidate must not carry a file identity")
        for finding in self.findings:
            if finding.relative_path != self.relative_path:
                raise ValueError("all findings must refer to the candidate")
        for error in self.scan_errors:
            if error.relative_path != self.relative_path:
                raise ValueError("all scan_errors must refer to the candidate")


@dataclass(frozen=True, slots=True)
class InspectionResult:
    """Canonical aggregate from inspecting a sequence of candidates."""

    inspections: tuple[CandidateInspection, ...]
    findings: tuple[Finding, ...]
    scan_errors: tuple[ScanError, ...]
    examined_file_count: int

    def __post_init__(self) -> None:
        paths = [item.relative_path for item in self.inspections]
        if paths != sorted(paths):
            raise ValueError("inspections must already be in canonical path order")
        if len(paths) != len(set(paths)):
            raise ValueError("inspections must not contain duplicate relative paths")
        _require_canonical(self.findings, key=finding_sort_key, name="findings")
        _require_canonical(self.scan_errors, key=scan_error_sort_key, name="scan_errors")
        if isinstance(self.examined_file_count, bool) or not isinstance(
            self.examined_file_count, int
        ):
            raise ValueError("examined_file_count must be an int")
        expected_count = sum(item.examined for item in self.inspections)
        if self.examined_file_count != expected_count:
            raise ValueError(
                "examined_file_count must equal the number of examined candidate results"
            )
        expected_findings = tuple(
            sorted(
                (finding for item in self.inspections for finding in item.findings),
                key=finding_sort_key,
            )
        )
        expected_errors = tuple(
            sorted(
                (error for item in self.inspections for error in item.scan_errors),
                key=scan_error_sort_key,
            )
        )
        if self.findings != expected_findings:
            raise ValueError("findings must exactly aggregate the candidate inspections")
        if self.scan_errors != expected_errors:
            raise ValueError("scan_errors must exactly aggregate the candidate inspections")
