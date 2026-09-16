"""Plain-text human-readable rendering of a ScanResult. No dependencies."""

from __future__ import annotations

from imageset_guard.models import Finding, ScanError, ScanResult, Severity


def _render_finding(finding: Finding) -> str:
    location = finding.relative_path if finding.relative_path is not None else "(dataset)"
    return f"  [{finding.severity.value.upper()}] {finding.code} {location}: {finding.message}"


def _render_scan_error(error: ScanError) -> str:
    location = error.relative_path if error.relative_path is not None else "(dataset)"
    return f"  [SCAN ERROR] {error.code} {location} ({error.operation}): {error.message}"


def render_terminal(result: ScanResult) -> str:
    """Render ``result`` as plain, deterministic text for a terminal."""
    lines = [f"Result: {result.status.value.upper()}"]

    summary = result.summary
    lines.append(f"Files examined: {summary.examined_file_count}")
    lines.append(f"Scan errors: {summary.scan_error_count}")
    counts = summary.finding_counts_by_severity
    lines.append(
        f"Findings: {counts[Severity.ERROR]} error, "
        f"{counts[Severity.WARNING]} warning, {counts[Severity.INFO]} info"
    )

    if result.findings:
        lines.append("")
        lines.append("Findings:")
        lines.extend(_render_finding(f) for f in result.findings)

    if result.scan_errors:
        lines.append("")
        lines.append("Scan errors:")
        lines.extend(_render_scan_error(e) for e in result.scan_errors)

    return "\n".join(lines) + "\n"
