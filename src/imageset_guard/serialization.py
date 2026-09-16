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
from typing import Any

from imageset_guard.models import Finding, ScanError, ScanResult, ScanSummary


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


def serialize_scan_result(result: ScanResult) -> bytes:
    """Render ``result`` as canonical, deterministic JSON bytes.

    ``allow_nan=False`` is defense in depth: ``Finding``/``ScanError``
    already reject non-finite evidence floats at construction time, so this
    should never trigger in practice, but it guarantees this function can
    never emit ``NaN``/``Infinity``/``-Infinity`` -- tokens a strict
    RFC 8259 JSON parser does not accept -- even if that primary defense
    were ever defeated by a future defect.
    """
    text = json.dumps(
        _result_to_dict(result),
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")


def write_scan_result(result: ScanResult, output_path: Path) -> None:
    """Atomically write ``result`` as canonical JSON to ``output_path``.

    Writes to a temporary file in ``output_path``'s own directory first,
    then swaps it into place with ``os.replace``, so a failure never leaves
    a partially written report at ``output_path`` and never disturbs a
    pre-existing file there until the new one is fully written. Any I/O
    failure (including a missing parent directory or a full disk) is
    raised as :class:`ReportWriteError`, and the temporary file is removed
    on a best-effort basis.
    """
    payload = serialize_scan_result(result)
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
