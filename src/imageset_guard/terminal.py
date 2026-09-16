"""Plain-text human-readable rendering of a scan report. No dependencies."""

from __future__ import annotations

from imageset_guard.models import Finding, ScanError, ScanResult, Severity
from imageset_guard.profile_models import DatasetProfile


def _render_finding(finding: Finding) -> str:
    location = finding.relative_path if finding.relative_path is not None else "(dataset)"
    return f"  [{finding.severity.value.upper()}] {finding.code} {location}: {finding.message}"


def _render_scan_error(error: ScanError) -> str:
    location = error.relative_path if error.relative_path is not None else "(dataset)"
    return f"  [SCAN ERROR] {error.code} {location} ({error.operation}): {error.message}"


def _render_profile(profile: DatasetProfile) -> list[str]:
    lines = ["", "Profile:"]
    lines.append(
        f"  Candidates: {profile.candidate_count}  "
        f"Accepted: {profile.accepted_count}  Rejected: {profile.rejected_count}"
    )
    if profile.file_count_by_split:
        by_split = ", ".join(
            f"{split}={count}" for split, count in sorted(profile.file_count_by_split.items())
        )
        lines.append(f"  Files by split: {by_split}")
    lines.append(f"  Classes: {len(profile.file_count_by_class)}")
    if profile.class_balance_ratio is not None:
        lines.append(f"  Class-balance ratio (largest:smallest): {profile.class_balance_ratio:.2f}")
    if profile.empty_classes:
        lines.append(f"  Empty classes: {', '.join(profile.empty_classes)}")
    if profile.format_counts:
        by_format = ", ".join(
            f"{fmt}={count}" for fmt, count in sorted(profile.format_counts.items())
        )
        lines.append(f"  Formats: {by_format}")
    if profile.width_min is not None:
        lines.append(
            f"  Width: {profile.width_min}-{profile.width_max}  "
            f"Height: {profile.height_min}-{profile.height_max}"
        )
    if not profile.complete:
        lines.append(
            "  Incomplete: some subtree could not be fully read; these facts are partial."
        )
    return lines


def render_terminal(result: ScanResult, profile: DatasetProfile | None = None) -> str:
    """Render ``result`` (and ``profile``, if given) as plain, deterministic text."""
    lines = [f"Result: {result.status.value.upper()}"]

    summary = result.summary
    lines.append(f"Files examined: {summary.examined_file_count}")
    lines.append(f"Scan errors: {summary.scan_error_count}")
    counts = summary.finding_counts_by_severity
    lines.append(
        f"Findings: {counts[Severity.ERROR]} error, "
        f"{counts[Severity.WARNING]} warning, {counts[Severity.INFO]} info"
    )

    if profile is not None:
        lines.extend(_render_profile(profile))

    if result.findings:
        lines.append("")
        lines.append("Findings:")
        lines.extend(_render_finding(f) for f in result.findings)

    if result.scan_errors:
        lines.append("")
        lines.append("Scan errors:")
        lines.extend(_render_scan_error(e) for e in result.scan_errors)

    return "\n".join(lines) + "\n"
