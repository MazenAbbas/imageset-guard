"""Composition of discovery, inspection, profiling, and exact-duplicate checks."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from imageset_guard.discovery import Layout, discover
from imageset_guard.hashing import hash_candidates
from imageset_guard.inspection import inspect_candidates
from imageset_guard.models import ScanResult, build_scan_result
from imageset_guard.policy import Policy
from imageset_guard.policy_eval import evaluate_profile_policy
from imageset_guard.profile import ProfileAccumulator, build_profile
from imageset_guard.profile_models import DatasetProfile


def scan_dataset(
    dataset_root: Path,
    policy: Policy | None = None,
    *,
    layout: Layout = "split-class",
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[ScanResult, DatasetProfile]:
    """Run every implemented layer and return the canonical scan result
    together with the dataset's profile.

    Operational failures remain data in ``scan_errors`` so unaffected files
    continue through the pipeline. Unexpected programming defects are not
    swallowed here; the CLI boundary maps them to its internal-error exit code.
    """
    active_policy = policy or Policy()
    accumulator = ProfileAccumulator()
    discovered = discover(dataset_root, layout=layout)
    inspected = inspect_candidates(
        discovered.candidates,
        active_policy,
        profile_accumulator=accumulator,
        progress_callback=progress_callback,
    )
    hashed = hash_candidates(discovered.candidates, inspected)

    all_scan_errors = (*discovered.scan_errors, *inspected.scan_errors, *hashed.scan_errors)
    profile = build_profile(discovered, inspected, accumulator, scan_errors=all_scan_errors)
    policy_findings = evaluate_profile_policy(profile, active_policy)

    result = build_scan_result(
        findings=(*discovered.findings, *inspected.findings, *hashed.findings, *policy_findings),
        scan_errors=all_scan_errors,
        examined_file_count=inspected.examined_file_count,
    )
    return result, profile
