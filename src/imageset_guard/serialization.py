"""Canonical, deterministic JSON reports.

The report is the tool's contract with automation: the same dataset and
policy must always produce the same bytes. To keep that true, this module
never writes a timestamp, a duration, an absolute path, a username, or any
platform/interpreter/Pillow version -- see SECURITY.md and README.md for
why. Keys are alphabetically sorted (``sort_keys=True``), text is UTF-8
with non-ASCII characters left as-is (``ensure_ascii=False``) so dataset
names in Arabic or any other script survive unescaped.

Writing is atomic: the report is written to a temporary file in the same
directory as the destination, then swapped into place with
``os.replace``, so a reader never observes a half-written report and a
failure never corrupts a pre-existing one.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Final

from imageset_guard.models import Finding, ScanError, ScanResult, ScanSummary
from imageset_guard.profile_models import DatasetProfile

#: The JSON report's own schema version, independent of the package
#: version. Bump only for a deliberate, documented change to the report's
#: field meanings; a purely additive field (a new optional key) does not
#: require a bump. Introduced in v0.2 -- earlier reports had no explicit
#: version field at all.
REPORT_SCHEMA_VERSION: Final = 1


class ReportWriteError(Exception):
    """Raised when the report cannot be written. Maps to exit code 3."""


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    return {
        "code": finding.code,
        "severity": finding.severity.value,
        "category": finding.category.value,
        "message": finding.message,
        "relative_path": finding.relative_path,
        "evidence": dict(finding.evidence),
        "remediation": finding.remediation,
    }


def _scan_error_to_dict(error: ScanError) -> dict[str, Any]:
    return {
        "code": error.code,
        "message": error.message,
        "operation": error.operation,
        "relative_path": error.relative_path,
    }


def _summary_to_dict(summary: ScanSummary) -> dict[str, Any]:
    return {
        "examined_file_count": summary.examined_file_count,
        "scan_error_count": summary.scan_error_count,
        "finding_counts_by_severity": {
            severity.value: count
            for severity, count in summary.finding_counts_by_severity.items()
        },
    }


def _result_to_dict(result: ScanResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "summary": _summary_to_dict(result.summary),
        "findings": [_finding_to_dict(f) for f in result.findings],
        "scan_errors": [_scan_error_to_dict(e) for e in result.scan_errors],
    }


def _profile_to_dict(profile: DatasetProfile) -> dict[str, Any]:
    return {
        "candidate_count": profile.candidate_count,
        "examined_count": profile.examined_count,
        "accepted_count": profile.accepted_count,
        "rejected_count": profile.rejected_count,
        "file_count_by_split": dict(profile.file_count_by_split),
        "file_count_by_class": dict(profile.file_count_by_class),
        "format_counts": dict(profile.format_counts),
        "mode_counts": dict(profile.mode_counts),
        "width_min": profile.width_min,
        "width_max": profile.width_max,
        "height_min": profile.height_min,
        "height_max": profile.height_max,
        "aspect_ratio_min": profile.aspect_ratio_min,
        "aspect_ratio_max": profile.aspect_ratio_max,
        "empty_classes": list(profile.empty_classes),
        "class_balance_ratio": profile.class_balance_ratio,
        "complete": profile.complete,
    }


def _report_to_dict(result: ScanResult, profile: DatasetProfile) -> dict[str, Any]:
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "profile": _profile_to_dict(profile),
        **_result_to_dict(result),
    }


def _dump_canonical_json(payload: dict[str, Any]) -> bytes:
    """Render ``payload`` as canonical, deterministic JSON bytes.

    ``allow_nan=False`` is defense in depth: ``Finding``/``ScanError``
    already reject non-finite evidence floats at construction time, so this
    should never trigger in practice, but it guarantees this function can
    never emit ``NaN``/``Infinity``/``-Infinity`` -- tokens a strict
    RFC 8259 JSON parser does not accept -- even if that primary defense
    were ever defeated by a future defect.
    """
    text = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")


def serialize_scan_result(result: ScanResult) -> bytes:
    """Render ``result`` alone as canonical, deterministic JSON bytes.

    Kept for callers that only have a bare :class:`ScanResult` (e.g. a
    hand-built one in a test); the public CLI report always includes the
    dataset profile too -- see :func:`serialize_report`.
    """
    return _dump_canonical_json(_result_to_dict(result))


def serialize_report(result: ScanResult, profile: DatasetProfile) -> bytes:
    """Render ``result`` and ``profile`` together as the full v0.2+ report."""
    return _dump_canonical_json(_report_to_dict(result, profile))


def _atomic_write(payload: bytes, output_path: Path) -> None:
    """Atomically write ``payload`` to ``output_path``.

    Writes to a temporary file in ``output_path``'s own directory first,
    then swaps it into place with ``os.replace``, so a failure never leaves
    a partially written report at ``output_path`` and never disturbs a
    pre-existing file there until the new one is fully written. Any I/O
    failure (including a missing parent directory or a full disk) is
    raised as :class:`ReportWriteError`, and the temporary file is removed
    on a best-effort basis.
    """
    directory = output_path.parent
    tmp_path: Path | None = None
    try:
        fd, tmp_name = _make_temp_file(directory, output_path.name)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            raise ReportWriteError("failed to write report") from exc
        try:
            os.replace(tmp_path, output_path)
        except OSError as exc:
            raise ReportWriteError("failed to finalize report") from exc
        tmp_path = None  # replaced successfully; nothing left to clean up
    except OSError as exc:
        raise ReportWriteError("failed to create report") from exc
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)


def _make_temp_file(directory: Path, base_name: str) -> tuple[int, str]:
    return tempfile.mkstemp(prefix=f".{base_name}.", suffix=".tmp", dir=directory)


def write_scan_result(result: ScanResult, output_path: Path) -> None:
    """Atomically write ``result`` alone as canonical JSON to ``output_path``."""
    _atomic_write(serialize_scan_result(result), output_path)


def write_report(result: ScanResult, profile: DatasetProfile, output_path: Path) -> None:
    """Atomically write the full v0.2+ report (result + profile) to ``output_path``."""
    _atomic_write(serialize_report(result, profile), output_path)
