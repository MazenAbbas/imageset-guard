"""Composition of discovery, inspection, and exact-duplicate checks."""

from __future__ import annotations

from pathlib import Path

from imageset_guard.discovery import discover
from imageset_guard.hashing import hash_candidates
from imageset_guard.inspection import inspect_candidates
from imageset_guard.models import ScanResult, build_scan_result
from imageset_guard.policy import Policy


def scan_dataset(dataset_root: Path, policy: Policy | None = None) -> ScanResult:
    """Run every implemented layer and return one canonical scan result.

    Operational failures remain data in ``scan_errors`` so unaffected files
    continue through the pipeline. Unexpected programming defects are not
    swallowed here; the CLI boundary maps them to its internal-error exit code.
    """
    active_policy = policy or Policy()
    discovered = discover(dataset_root)
    inspected = inspect_candidates(discovered.candidates, active_policy)
    hashed = hash_candidates(discovered.candidates, inspected)

    return build_scan_result(
        findings=(*discovered.findings, *inspected.findings, *hashed.findings),
        scan_errors=(
            *discovered.scan_errors,
            *inspected.scan_errors,
            *hashed.scan_errors,
        ),
        examined_file_count=inspected.examined_file_count,
    )
