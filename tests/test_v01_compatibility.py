"""Golden compatibility: v0.1's report contract must survive v0.2 unchanged.

For a dataset scanned with no v0.2 policy fields configured, every
field/value the v0.1 report contract defined (status, summary, findings,
scan_errors, and their exact shapes) must be byte-identical in meaning to
before. v0.2 may only ever *add* new top-level keys (``report_schema_
version``, ``profile``) or new finding codes (``POLICYxxx``, never fired
unless a v0.2 policy field is explicitly set) -- it must never change,
remove, or silently repurpose anything v0.1 already promised.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from imageset_guard import codes
from imageset_guard.models import ResultStatus
from imageset_guard.scanner import scan_dataset
from imageset_guard.serialization import serialize_report


def _build_v01_style_dataset(root: Path) -> None:
    train_cat = root / "train" / "cats" / "a.jpg"
    train_cat.parent.mkdir(parents=True)
    Image.new("RGB", (5, 5), "red").save(train_cat, format="JPEG")

    validation_cat = root / "validation" / "cats" / "b.jpg"
    validation_cat.parent.mkdir(parents=True)
    validation_cat.write_bytes(train_cat.read_bytes())  # exact cross-split duplicate

    corrupt = root / "train" / "cats" / "bad.jpg"
    corrupt.write_bytes(b"not an image")


def test_default_policy_scan_produces_exactly_the_v01_findings(tmp_path: Path) -> None:
    _build_v01_style_dataset(tmp_path)
    result, _profile = scan_dataset(tmp_path)  # no policy: v0.1-identical behavior
    assert result.status is ResultStatus.FAIL
    assert {f.code for f in result.findings} == {
        codes.IMG_UNIDENTIFIED_IMAGE,
        codes.DUP_ACROSS_SPLITS,
    }
    assert result.scan_errors == ()


def test_report_json_is_v01_shape_plus_purely_additive_keys(tmp_path: Path) -> None:
    _build_v01_style_dataset(tmp_path)
    result, profile = scan_dataset(tmp_path)
    payload = json.loads(serialize_report(result, profile))

    v01_keys = {"status", "summary", "findings", "scan_errors"}
    assert v01_keys <= set(payload)
    assert set(payload) - v01_keys == {"report_schema_version", "profile"}

    assert payload["status"] == "fail"
    assert set(payload["summary"]) == {
        "examined_file_count",
        "scan_error_count",
        "finding_counts_by_severity",
    }
    for finding in payload["findings"]:
        assert set(finding) == {
            "code",
            "severity",
            "category",
            "message",
            "relative_path",
            "evidence",
            "remediation",
        }
    for error in payload["scan_errors"]:
        assert set(error) == {"code", "message", "operation", "relative_path"}


def test_v01_finding_codes_keep_their_original_category_and_severity(tmp_path: Path) -> None:
    _build_v01_style_dataset(tmp_path)
    result, _profile = scan_dataset(tmp_path)
    by_code = {f.code: f for f in result.findings}

    assert by_code[codes.IMG_UNIDENTIFIED_IMAGE].category.value == "integrity"
    assert by_code[codes.IMG_UNIDENTIFIED_IMAGE].severity.value == "error"
    assert by_code[codes.DUP_ACROSS_SPLITS].category.value == "leakage"
    assert by_code[codes.DUP_ACROSS_SPLITS].severity.value == "error"


def test_no_policy_configured_means_zero_policy_category_findings(tmp_path: Path) -> None:
    _build_v01_style_dataset(tmp_path)
    result, _profile = scan_dataset(tmp_path)
    assert all(f.category.value != "policy" for f in result.findings)
