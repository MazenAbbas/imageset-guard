"""Tests for imageset_guard.serialization: the canonical JSON report writer.

Per the approved specification: a fixed key order (alphabetical, via
sort_keys), UTF-8 with Arabic names preserved, relative paths only, no
timestamps/timings/environment metadata, and an atomic write (temp file in
the same directory, then os.replace) whose failures surface as
ReportWriteError so the CLI can map them to exit code 3.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from imageset_guard.models import (
    Category,
    Finding,
    ScanError,
    ScanResult,
    Severity,
    build_scan_result,
)
from imageset_guard.profile_models import DatasetProfile
from imageset_guard.serialization import (
    REPORT_SCHEMA_VERSION,
    ReportWriteError,
    serialize_report,
    serialize_scan_result,
    write_report,
    write_scan_result,
)


def _sample_profile() -> DatasetProfile:
    return DatasetProfile(
        candidate_count=3,
        examined_count=3,
        accepted_count=2,
        rejected_count=1,
        file_count_by_split={"train": 3},
        file_count_by_class={"قطط": 2, "dogs": 1},
        format_counts={"JPEG": 2},
        mode_counts={"RGB": 2},
        width_min=10,
        width_max=20,
        height_min=10,
        height_max=20,
        aspect_ratio_min=1.0,
        aspect_ratio_max=1.0,
        empty_classes=(),
        class_balance_ratio=2.0,
        complete=True,
    )


def _sample_result() -> ScanResult:
    findings = (
        Finding(
            code="IMG001",
            severity=Severity.ERROR,
            category=Category.INTEGRITY,
            message="Image file is empty",
            relative_path="train/قطط/img001.jpg",
            evidence={"byte_size": 0},
            remediation="Remove or replace the empty file.",
        ),
    )
    scan_errors = (
        ScanError(
            code="SYS001",
            message="Permission denied",
            relative_path="train/dogs/locked.jpg",
            operation="open",
        ),
    )
    return build_scan_result(findings=findings, scan_errors=scan_errors, examined_file_count=3)


def test_serialize_is_deterministic_byte_for_byte() -> None:
    result = _sample_result()
    first = serialize_scan_result(result)
    second = serialize_scan_result(result)
    assert first == second


def test_serialize_produces_valid_json_with_expected_top_level_keys() -> None:
    result = _sample_result()
    payload = json.loads(serialize_scan_result(result))
    assert set(payload) == {"status", "summary", "findings", "scan_errors"}
    # A scan_error is present alongside an error-severity finding, so
    # INCOMPLETE correctly outranks FAIL here (see test_models.py).
    assert payload["status"] == "incomplete"


def test_serialize_preserves_arabic_text_as_utf8_not_escaped() -> None:
    result = _sample_result()
    raw = serialize_scan_result(result)
    assert "قطط".encode() in raw
    assert b"\\u0642" not in raw  # not escaped to \uXXXX


def test_serialize_never_includes_forbidden_fields() -> None:
    result = _sample_result()
    raw_text = serialize_scan_result(result).decode("utf-8")
    for forbidden in ("timestamp", "duration", "elapsed", "username", "platform", "python_version"):
        assert forbidden not in raw_text


def test_serialize_only_uses_relative_paths() -> None:
    result = _sample_result()
    payload = json.loads(serialize_scan_result(result))
    for finding in payload["findings"]:
        if finding["relative_path"] is not None:
            assert not finding["relative_path"].startswith("/")
            assert ":" not in finding["relative_path"]


def test_serialize_finding_shape() -> None:
    result = _sample_result()
    payload = json.loads(serialize_scan_result(result))
    finding = payload["findings"][0]
    assert finding == {
        "code": "IMG001",
        "severity": "error",
        "category": "integrity",
        "message": "Image file is empty",
        "relative_path": "train/قطط/img001.jpg",
        "evidence": {"byte_size": 0},
        "remediation": "Remove or replace the empty file.",
    }


def test_serialize_scan_error_shape() -> None:
    result = _sample_result()
    payload = json.loads(serialize_scan_result(result))
    error = payload["scan_errors"][0]
    assert error == {
        "code": "SYS001",
        "message": "Permission denied",
        "operation": "open",
        "relative_path": "train/dogs/locked.jpg",
    }


def test_serialize_summary_shape() -> None:
    result = _sample_result()
    payload = json.loads(serialize_scan_result(result))
    assert payload["summary"] == {
        "examined_file_count": 3,
        "scan_error_count": 1,
        "finding_counts_by_severity": {"error": 1, "info": 0, "warning": 0},
    }


def test_write_scan_result_creates_exact_file_content(tmp_path: Path) -> None:
    result = _sample_result()
    output = tmp_path / "report.json"
    write_scan_result(result, output)
    assert output.read_bytes() == serialize_scan_result(result)


def test_write_scan_result_leaves_no_temp_file_on_success(tmp_path: Path) -> None:
    result = _sample_result()
    output = tmp_path / "report.json"
    write_scan_result(result, output)
    leftover = [p for p in tmp_path.iterdir() if p != output]
    assert leftover == []


def test_write_scan_result_raises_report_write_error_for_missing_parent(
    tmp_path: Path,
) -> None:
    result = _sample_result()
    output = tmp_path / "no-such-dir" / "report.json"
    with pytest.raises(ReportWriteError):
        write_scan_result(result, output)


def test_report_write_error_does_not_expose_output_path(tmp_path: Path) -> None:
    output = tmp_path / "private-person" / "report.json"
    with pytest.raises(ReportWriteError) as captured:
        write_scan_result(_sample_result(), output)
    assert str(output) not in str(captured.value)


def test_write_scan_result_failure_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    result = _sample_result()
    output = tmp_path / "no-such-dir" / "report.json"
    with pytest.raises(ReportWriteError):
        write_scan_result(result, output)
    assert list(tmp_path.iterdir()) == []


def test_write_scan_result_overwrites_existing_file_atomically(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    output.write_text("old content", encoding="utf-8")
    result = _sample_result()
    write_scan_result(result, output)
    assert output.read_bytes() == serialize_scan_result(result)


# ---------------------------------------------------------------------------
# allow_nan=False defense-in-depth
#
# Finding/ScanError already reject non-finite floats at construction time
# (see test_models.py). These tests simulate that primary defense being
# bypassed -- e.g. by a future refactoring bug -- to prove the serializer
# itself refuses to ever emit non-standard JSON tokens (NaN/Infinity/
# -Infinity), which a strict RFC 8259 parser would reject.
# ---------------------------------------------------------------------------


def _result_with_bypassed_non_finite_evidence(bad_value: float) -> ScanResult:
    result = _sample_result()
    finding = result.findings[0]
    # Bypass the frozen dataclass and its own validation to simulate a
    # defect that defeated the primary defense in Finding.__post_init__.
    object.__setattr__(finding, "evidence", {"ratio": bad_value})
    return result


@pytest.mark.parametrize(
    "bad_value",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_serialize_raises_instead_of_emitting_non_finite_tokens(bad_value: float) -> None:
    result = _result_with_bypassed_non_finite_evidence(bad_value)
    with pytest.raises(ValueError):
        serialize_scan_result(result)


def test_serialize_output_is_accepted_by_a_strict_json_parser() -> None:
    result = _sample_result()
    raw = serialize_scan_result(result)

    def _reject_non_standard_constants(token: str) -> float:
        raise ValueError(f"strict JSON parser encountered non-standard token: {token}")

    # A strict RFC 8259 parser has no NaN/Infinity/-Infinity literals at
    # all; this reproduces that behaviour and proves normal output never
    # trips it.
    parsed = json.loads(raw, parse_constant=_reject_non_standard_constants)
    assert parsed["status"] == "incomplete"


# ---------------------------------------------------------------------------
# v0.2: serialize_report / write_report (result + profile, schema version)
# ---------------------------------------------------------------------------


def test_serialize_report_includes_schema_version_and_profile() -> None:
    payload = json.loads(serialize_report(_sample_result(), _sample_profile()))
    assert payload["report_schema_version"] == REPORT_SCHEMA_VERSION == 1
    assert payload["profile"]["accepted_count"] == 2
    assert payload["profile"]["rejected_count"] == 1
    assert payload["profile"]["file_count_by_class"] == {"قطط": 2, "dogs": 1}


def test_serialize_report_is_a_strict_superset_of_serialize_scan_result() -> None:
    # Additive-only: every key/value serialize_scan_result would have
    # produced is still present, unchanged, in serialize_report's output.
    result = _sample_result()
    bare = json.loads(serialize_scan_result(result))
    full = json.loads(serialize_report(result, _sample_profile()))
    for key, value in bare.items():
        assert full[key] == value
    assert set(full) - set(bare) == {"report_schema_version", "profile"}


def test_serialize_report_is_deterministic() -> None:
    result, profile = _sample_result(), _sample_profile()
    assert serialize_report(result, profile) == serialize_report(result, profile)


def test_serialize_report_preserves_arabic_class_names_unescaped() -> None:
    raw = serialize_report(_sample_result(), _sample_profile())
    assert "قطط".encode() in raw
    assert b"\\u0642" not in raw


def test_write_report_creates_exact_file_content(tmp_path: Path) -> None:
    result, profile = _sample_result(), _sample_profile()
    output = tmp_path / "report.json"
    write_report(result, profile, output)
    assert output.read_bytes() == serialize_report(result, profile)


def test_write_report_failure_raises_report_write_error(tmp_path: Path) -> None:
    output = tmp_path / "no-such-dir" / "report.json"
    with pytest.raises(ReportWriteError):
        write_report(_sample_result(), _sample_profile(), output)
