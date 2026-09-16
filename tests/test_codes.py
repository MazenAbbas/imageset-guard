"""Tests pinning the central finding/scan-error code registry.

Every code discovery.py can emit must be declared here exactly once, with
exactly one default message, and must never be reused for a second, unrelated
meaning.
"""

from __future__ import annotations

import re

import pytest

from imageset_guard import codes
from imageset_guard.models import Category, Finding, ScanError, Severity


def _public_code_constants() -> dict[str, str]:
    return {
        name: value
        for name, value in vars(codes).items()
        if name.isupper() and isinstance(value, str) and name != "__name__"
    }


def test_all_split_codes_match_pattern_and_are_unique() -> None:
    split_codes = [v for v in _public_code_constants().values() if v.startswith("SPLIT")]
    assert split_codes, "expected at least one SPLIT code to be registered"
    for code in split_codes:
        assert re.fullmatch(r"SPLIT\d{3}", code), code
    assert len(split_codes) == len(set(split_codes)), "duplicate SPLIT code value"


def test_all_img_codes_match_pattern_and_are_unique() -> None:
    img_codes = [v for v in _public_code_constants().values() if v.startswith("IMG")]
    assert img_codes, "expected at least one IMG code to be registered"
    for code in img_codes:
        assert re.fullmatch(r"IMG\d{3}", code), code
    assert len(img_codes) == len(set(img_codes)), "duplicate IMG code value"


def test_all_sys_codes_match_pattern_and_are_unique() -> None:
    sys_codes = [v for v in _public_code_constants().values() if v.startswith("SYS")]
    assert sys_codes, "expected at least one SYS code to be registered"
    for code in sys_codes:
        assert re.fullmatch(r"SYS\d{3}", code), code
    assert len(sys_codes) == len(set(sys_codes)), "duplicate SYS code value"


def test_all_priv_codes_match_pattern_and_are_unique() -> None:
    priv_codes = [v for v in _public_code_constants().values() if v.startswith("PRIV")]
    assert priv_codes, "expected at least one PRIV code to be registered"
    for code in priv_codes:
        assert re.fullmatch(r"PRIV\d{3}", code), code
    assert len(priv_codes) == len(set(priv_codes)), "duplicate PRIV code value"


def test_all_dup_codes_match_pattern_and_are_unique() -> None:
    duplicate_codes = [v for v in _public_code_constants().values() if v.startswith("DUP")]
    assert duplicate_codes, "expected at least one DUP code to be registered"
    for code in duplicate_codes:
        assert re.fullmatch(r"DUP\d{3}", code), code
    assert len(duplicate_codes) == len(set(duplicate_codes)), "duplicate DUP code value"


def test_no_code_value_is_reused_across_two_constant_names() -> None:
    values = list(_public_code_constants().values())
    assert len(values) == len(set(values)), "a code value is assigned to two constant names"


def test_every_code_constant_has_exactly_one_default_message() -> None:
    constants = _public_code_constants()
    for name, code in constants.items():
        assert code in codes.DEFAULT_MESSAGES, f"{name} ({code}) has no default message"
    # No orphan messages for codes that no longer exist as constants either.
    declared_codes = set(constants.values())
    assert set(codes.DEFAULT_MESSAGES) == declared_codes


def test_default_messages_are_non_empty_strings() -> None:
    for code, message in codes.DEFAULT_MESSAGES.items():
        assert isinstance(message, str)
        assert message.strip(), f"{code} has an empty default message"


def test_link_skipped_code_value_is_stable() -> None:
    # SPLIT010's *meaning* was deliberately broadened (symlink -> any
    # link-like entry, including junctions) while still pre-release; its
    # *value* must stay SPLIT010, and the Python name must be the new one.
    assert codes.SPLIT_LINK_SKIPPED == "SPLIT010"
    assert not hasattr(codes, "SPLIT_SYMLINK_SKIPPED")


def test_new_codes_are_registered() -> None:
    assert codes.SPLIT_OPTIONAL_SPLIT_NOT_A_DIRECTORY == "SPLIT014"
    assert codes.IMG_NON_REGULAR_ENTRY == "IMG002"


@pytest.mark.parametrize(
    ("code_attr", "category"),
    [
        ("SPLIT_TRAIN_MISSING", Category.STRUCTURE),
        ("SPLIT_EMPTY_CLASS", Category.STRUCTURE),
        ("SPLIT_OPTIONAL_SPLIT_NOT_A_DIRECTORY", Category.STRUCTURE),
        ("IMG_UNSUPPORTED_EXTENSION", Category.INTEGRITY),
        ("IMG_NON_REGULAR_ENTRY", Category.INTEGRITY),
        ("IMG_UNIDENTIFIED_IMAGE", Category.INTEGRITY),
        ("IMG_DECODE_FAILED", Category.INTEGRITY),
        ("IMG_EXTENSION_FORMAT_MISMATCH", Category.INTEGRITY),
        ("IMG_PIXEL_LIMIT_EXCEEDED", Category.INTEGRITY),
        ("IMG_MULTIFRAME_UNSUPPORTED", Category.INTEGRITY),
        ("IMG_DECODER_WARNING", Category.INTEGRITY),
        ("PRIV_EXIF_PRESENT", Category.PRIVACY),
        ("PRIV_GPS_PRESENT", Category.PRIVACY),
        ("DUP_WITHIN_CLASS", Category.LEAKAGE),
        ("DUP_ACROSS_CLASSES", Category.LEAKAGE),
        ("DUP_ACROSS_SPLITS", Category.LEAKAGE),
    ],
)
def test_registered_codes_construct_a_valid_finding(code_attr: str, category: Category) -> None:
    code = getattr(codes, code_attr)
    finding = Finding(
        code=code,
        severity=Severity.WARNING,
        category=category,
        message=codes.DEFAULT_MESSAGES[code],
        remediation="See documentation.",
    )
    assert finding.code == code


def test_sys_code_constructs_a_valid_scan_error() -> None:
    code = codes.SYS_PERMISSION_DENIED
    error = ScanError(
        code=code,
        message=codes.DEFAULT_MESSAGES[code],
        operation="open",
    )
    assert error.code == code
