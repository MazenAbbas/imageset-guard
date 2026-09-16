"""Streaming SHA-256 and exact-duplicate leakage detection.

Only candidates whose Phase 3 result has no integrity error are eligible.
Files are reopened through the shared read-only file-access guard and hashed
in bounded chunks. Digests remain internal; findings identify duplicates using
relative paths only.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from typing import BinaryIO, Final

from imageset_guard import codes
from imageset_guard.discovery_models import DiscoveredImageCandidate
from imageset_guard.file_access import (
    CandidateChangedError,
    FileIdentity,
    open_regular_file_readonly,
)
from imageset_guard.hashing_models import HashingResult, HashRecord
from imageset_guard.inspection_models import CandidateInspection, InspectionResult
from imageset_guard.models import (
    Category,
    Finding,
    ScanError,
    Severity,
    finding_sort_key,
    scan_error_sort_key,
)

HASH_CHUNK_SIZE: Final = 1024 * 1024


def is_hash_eligible(inspection: CandidateInspection) -> bool:
    """Return whether inspection established safe, decodable image content."""
    return inspection.examined and not any(
        finding.category is Category.INTEGRITY and finding.severity is Severity.ERROR
        for finding in inspection.findings
    )


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(HASH_CHUNK_SIZE):
        digest.update(chunk)
    return digest.hexdigest()


def _scan_error(exc: OSError, relative_path: str, operation: str) -> ScanError:
    if isinstance(exc, PermissionError):
        code = codes.SYS_PERMISSION_DENIED
    elif isinstance(exc, FileNotFoundError):
        code = codes.SYS_PATH_VANISHED
    else:
        code = codes.SYS_STAT_OR_WALK_FAILURE
    return ScanError(
        code=code,
        message=codes.DEFAULT_MESSAGES[code],
        operation=operation,  # type: ignore[arg-type]
        relative_path=relative_path,
    )


def _changed_error(relative_path: str) -> ScanError:
    return ScanError(
        code=codes.SYS_CANDIDATE_CHANGED,
        message=codes.DEFAULT_MESSAGES[codes.SYS_CANDIDATE_CHANGED],
        operation="read",
        relative_path=relative_path,
    )


def _hash_candidate(
    candidate: DiscoveredImageCandidate, expected_identity: FileIdentity
) -> tuple[HashRecord | None, ScanError | None]:
    try:
        with open_regular_file_readonly(
            candidate.absolute_path, expected_identity=expected_identity
        ) as stream:
            try:
                digest = _sha256_stream(stream)
            except OSError as exc:
                return None, _scan_error(exc, candidate.relative_path, "read")
    except CandidateChangedError:
        return None, _changed_error(candidate.relative_path)
    except OSError as exc:
        return None, _scan_error(exc, candidate.relative_path, "open")

    return (
        HashRecord(
            relative_path=candidate.relative_path,
            split=candidate.split,
            class_name=candidate.class_name,
            sha256=digest,
        ),
        None,
    )


def _duplicate_finding(
    code: str,
    severity: Severity,
    duplicate: HashRecord,
    match: HashRecord,
) -> Finding:
    remediation = {
        codes.DUP_WITHIN_CLASS: "Remove the redundant copy if repeated weighting is unintended.",
        codes.DUP_ACROSS_CLASSES: (
            "Review the labels and remove or relabel the conflicting duplicate."
        ),
        codes.DUP_ACROSS_SPLITS: (
            "Keep this image in only one split to prevent evaluation leakage."
        ),
    }[code]
    return Finding(
        code=code,
        severity=severity,
        category=Category.LEAKAGE,
        message=codes.DEFAULT_MESSAGES[code],
        relative_path=duplicate.relative_path,
        evidence={"matches": match.relative_path},
        remediation=remediation,
    )


def _duplicate_findings(records: Iterable[HashRecord]) -> tuple[Finding, ...]:
    groups: dict[str, list[HashRecord]] = defaultdict(list)
    for record in records:
        groups[record.sha256].append(record)

    findings: list[Finding] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda record: record.relative_path)
        anchor = ordered[0]
        first_by_split_class: dict[tuple[str, str], HashRecord] = {
            (anchor.split, anchor.class_name): anchor
        }
        first_class_other_than_anchor: HashRecord | None = None
        first_split_other_than_anchor: HashRecord | None = None
        for duplicate in ordered[1:]:
            same_class = first_by_split_class.get(
                (duplicate.split, duplicate.class_name)
            )
            other_class = (
                anchor
                if duplicate.class_name != anchor.class_name
                else first_class_other_than_anchor
            )
            other_split = (
                anchor
                if duplicate.split != anchor.split
                else first_split_other_than_anchor
            )

            if same_class is not None:
                findings.append(
                    _duplicate_finding(
                        codes.DUP_WITHIN_CLASS, Severity.WARNING, duplicate, same_class
                    )
                )
            if other_class is not None:
                findings.append(
                    _duplicate_finding(
                        codes.DUP_ACROSS_CLASSES, Severity.ERROR, duplicate, other_class
                    )
                )
            if other_split is not None:
                findings.append(
                    _duplicate_finding(
                        codes.DUP_ACROSS_SPLITS, Severity.ERROR, duplicate, other_split
                    )
                )

            first_by_split_class.setdefault(
                (duplicate.split, duplicate.class_name), duplicate
            )
            if (
                first_class_other_than_anchor is None
                and duplicate.class_name != anchor.class_name
            ):
                first_class_other_than_anchor = duplicate
            if first_split_other_than_anchor is None and duplicate.split != anchor.split:
                first_split_other_than_anchor = duplicate

    return tuple(sorted(findings, key=finding_sort_key))


def hash_candidates(
    candidates: Iterable[DiscoveredImageCandidate], inspections: InspectionResult
) -> HashingResult:
    """Hash integrity-eligible candidates and report exact duplicate relationships."""
    ordered_candidates = sorted(candidates, key=lambda candidate: candidate.relative_path)
    candidate_paths = [candidate.relative_path for candidate in ordered_candidates]
    if len(candidate_paths) != len(set(candidate_paths)):
        raise ValueError("candidates must not contain duplicate relative paths")

    inspected_by_path = {
        inspection.relative_path: inspection for inspection in inspections.inspections
    }
    if set(candidate_paths) != set(inspected_by_path):
        raise ValueError("candidates and inspections must contain exactly the same paths")

    eligible = [
        candidate
        for candidate in ordered_candidates
        if is_hash_eligible(inspected_by_path[candidate.relative_path])
    ]
    records: list[HashRecord] = []
    scan_errors: list[ScanError] = []
    for candidate in eligible:
        identity = inspected_by_path[candidate.relative_path].file_identity
        if identity is None:  # CandidateInspection enforces this for examined results.
            raise AssertionError("eligible inspection has no file identity")
        record, error = _hash_candidate(candidate, identity)
        if record is not None:
            records.append(record)
        if error is not None:
            scan_errors.append(error)

    records.sort(key=lambda record: record.relative_path)
    scan_errors.sort(key=scan_error_sort_key)
    findings = _duplicate_findings(records)
    return HashingResult(
        records=tuple(records),
        findings=findings,
        scan_errors=tuple(scan_errors),
        eligible_file_count=len(eligible),
    )
