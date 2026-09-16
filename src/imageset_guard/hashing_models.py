"""Immutable, canonical results for exact-byte hashing and duplicate checks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from imageset_guard.discovery_models import validate_path_component
from imageset_guard.models import Finding, ScanError, finding_sort_key, scan_error_sort_key
from imageset_guard.models import validate_relative_path as _validate_relative_path

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_VALID_SPLITS = frozenset({"train", "validation", "test"})


@dataclass(frozen=True, slots=True)
class HashRecord:
    """Internal SHA-256 identity for one successfully read candidate.

    Digests are used for grouping only and are deliberately absent from
    findings and public report serialization.
    """

    relative_path: str
    split: str
    class_name: str
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.relative_path, str):
            raise ValueError("relative_path must be a str")
        _validate_relative_path(self.relative_path)
        if not isinstance(self.split, str) or self.split not in _VALID_SPLITS:
            raise ValueError("split must be train, validation, or test")
        validate_path_component(self.class_name, field_name="class_name")
        path_parts = self.relative_path.split("/")
        if len(path_parts) < 3 or path_parts[:2] != [self.split, self.class_name]:
            raise ValueError("relative_path must begin with the record's split and class_name")
        if not isinstance(self.sha256, str) or not _SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")


@dataclass(frozen=True, slots=True)
class HashingResult:
    """Canonical result of hashing all integrity-eligible candidates."""

    records: tuple[HashRecord, ...]
    findings: tuple[Finding, ...]
    scan_errors: tuple[ScanError, ...]
    eligible_file_count: int

    def __post_init__(self) -> None:
        paths = [record.relative_path for record in self.records]
        if paths != sorted(paths):
            raise ValueError("records must already be in canonical path order")
        if len(paths) != len(set(paths)):
            raise ValueError("records must not contain duplicate relative paths")
        if self.findings != tuple(sorted(self.findings, key=finding_sort_key)):
            raise ValueError("findings must already be in canonical order")
        if self.scan_errors != tuple(sorted(self.scan_errors, key=scan_error_sort_key)):
            raise ValueError("scan_errors must already be in canonical order")
        if isinstance(self.eligible_file_count, bool) or not isinstance(
            self.eligible_file_count, int
        ):
            raise ValueError("eligible_file_count must be an int")
        if self.eligible_file_count < len(self.records):
            raise ValueError("eligible_file_count cannot be smaller than successful records")
        if self.eligible_file_count != len(self.records) + len(self.scan_errors):
            raise ValueError(
                "each eligible candidate must produce one hash record or one scan_error"
            )
