"""Pure functions turning dataset facts into ``Category.POLICY`` findings.

Nothing here touches the filesystem or Pillow: every function takes plain
values already read by discovery/inspection and returns
:class:`~imageset_guard.models.Finding` objects. This keeps policy logic
independently testable with plain values, and keeps the meaning of every
existing SPLIT/IMG/PRIV/DUP finding code untouched -- a policy violation
is always reported through a new, distinct ``POLICYxxx`` code, never by
changing an existing code's severity or meaning.

Two kinds of checks live here, split by what they need to know:

- :func:`evaluate_image_policy` -- per-image checks (format, mode,
  dimensions, aspect ratio, EXIF/GPS-forbidden), called once per accepted
  candidate from ``imageset_guard.inspection`` with that candidate's own
  facts, so violations point at the exact file.
- :func:`evaluate_profile_policy` -- dataset-wide checks (minimum images
  per class, class-balance ratio) that can only be known once the whole
  dataset profile has been built.
"""

from __future__ import annotations

from imageset_guard import codes
from imageset_guard.models import Category, Finding, Severity, finding_sort_key
from imageset_guard.policy import Policy
from imageset_guard.profile_models import DatasetProfile


def _policy_finding(
    code: str,
    relative_path: str | None,
    evidence: dict[str, str | int | float | bool],
    remediation: str,
) -> Finding:
    return Finding(
        code=code,
        severity=Severity.ERROR,
        category=Category.POLICY,
        message=codes.DEFAULT_MESSAGES[code],
        relative_path=relative_path,
        evidence=evidence,
        remediation=remediation,
    )


def evaluate_image_policy(
    *,
    relative_path: str,
    image_format: str,
    mode: str,
    width: int,
    height: int,
    has_exif: bool,
    has_gps: bool,
    policy: Policy,
) -> list[Finding]:
    """Evaluate every per-image policy rule for one accepted candidate."""
    findings: list[Finding] = []

    if has_exif and policy.exif_policy == "forbid":
        findings.append(
            _policy_finding(
                codes.POLICY_EXIF_FORBIDDEN,
                relative_path,
                {"exif_present": True},
                "Remove EXIF metadata from this image, or relax exif_policy in your policy file.",
            )
        )
    if has_gps and policy.gps_policy == "forbid":
        findings.append(
            _policy_finding(
                codes.POLICY_GPS_FORBIDDEN,
                relative_path,
                {"gps_present": True},
                "Remove GPS metadata from this image, or relax gps_policy in your policy file.",
            )
        )
    if policy.allowed_formats is not None and image_format not in policy.allowed_formats:
        findings.append(
            _policy_finding(
                codes.POLICY_FORMAT_NOT_ALLOWED,
                relative_path,
                {"format": image_format},
                "Convert this image to an allowed format, or add it to allowed_formats.",
            )
        )
    if policy.allowed_modes is not None and mode not in policy.allowed_modes:
        findings.append(
            _policy_finding(
                codes.POLICY_MODE_NOT_ALLOWED,
                relative_path,
                {"mode": mode},
                "Convert this image to an allowed color mode, or add it to allowed_modes.",
            )
        )
    if policy.min_width is not None and width < policy.min_width:
        findings.append(
            _policy_finding(
                codes.POLICY_WIDTH_OUT_OF_BOUNDS,
                relative_path,
                {"width": width, "min_width": policy.min_width},
                "Replace this image with one that meets the configured minimum width.",
            )
        )
    if policy.max_width is not None and width > policy.max_width:
        findings.append(
            _policy_finding(
                codes.POLICY_WIDTH_OUT_OF_BOUNDS,
                relative_path,
                {"width": width, "max_width": policy.max_width},
                "Resize this image to meet the configured maximum width.",
            )
        )
    if policy.min_height is not None and height < policy.min_height:
        findings.append(
            _policy_finding(
                codes.POLICY_HEIGHT_OUT_OF_BOUNDS,
                relative_path,
                {"height": height, "min_height": policy.min_height},
                "Replace this image with one that meets the configured minimum height.",
            )
        )
    if policy.max_height is not None and height > policy.max_height:
        findings.append(
            _policy_finding(
                codes.POLICY_HEIGHT_OUT_OF_BOUNDS,
                relative_path,
                {"height": height, "max_height": policy.max_height},
                "Resize this image to meet the configured maximum height.",
            )
        )
    if height > 0:
        aspect_ratio = round(width / height, 6)
        if policy.min_aspect_ratio is not None and aspect_ratio < policy.min_aspect_ratio:
            findings.append(
                _policy_finding(
                    codes.POLICY_ASPECT_RATIO_OUT_OF_BOUNDS,
                    relative_path,
                    {"aspect_ratio": aspect_ratio, "min_aspect_ratio": policy.min_aspect_ratio},
                    "Crop or replace this image to meet the configured minimum aspect ratio.",
                )
            )
        if policy.max_aspect_ratio is not None and aspect_ratio > policy.max_aspect_ratio:
            findings.append(
                _policy_finding(
                    codes.POLICY_ASPECT_RATIO_OUT_OF_BOUNDS,
                    relative_path,
                    {"aspect_ratio": aspect_ratio, "max_aspect_ratio": policy.max_aspect_ratio},
                    "Crop or replace this image to meet the configured maximum aspect ratio.",
                )
            )

    return findings


def evaluate_profile_policy(profile: DatasetProfile, policy: Policy) -> tuple[Finding, ...]:
    """Evaluate every dataset-wide policy rule against the final profile."""
    findings: list[Finding] = []

    if policy.min_images_per_class is not None:
        for class_name, count in sorted(profile.file_count_by_class.items()):
            if count < policy.min_images_per_class:
                findings.append(
                    _policy_finding(
                        codes.POLICY_CLASS_TOO_SMALL,
                        None,
                        {
                            "class_name": class_name,
                            "count": count,
                            "minimum": policy.min_images_per_class,
                        },
                        "Add more images to this class, or lower min_images_per_class.",
                    )
                )

    if (
        policy.max_class_imbalance_ratio is not None
        and profile.class_balance_ratio is not None
        and profile.class_balance_ratio > policy.max_class_imbalance_ratio
    ):
        findings.append(
            _policy_finding(
                codes.POLICY_CLASS_IMBALANCE,
                None,
                {
                    "ratio": round(profile.class_balance_ratio, 3),
                    "maximum": policy.max_class_imbalance_ratio,
                },
                "Balance class sizes, or raise max_class_imbalance_ratio.",
            )
        )

    return tuple(sorted(findings, key=finding_sort_key))
