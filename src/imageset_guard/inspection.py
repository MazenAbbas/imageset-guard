"""Safe, local integrity and privacy inspection for discovered image files.

Each candidate is opened read-only and processed in isolation.  Pillow's
``verify()`` checks file structure without decoding pixels; the same already
opened file is then rewound, reopened through Pillow, and ``load()`` is called
to force a full decode.  No decoder exception text or EXIF value enters a
result.

The filesystem can still change between any check and use.  ``O_NOFOLLOW`` is
used where available and descriptor identity is checked, but this is best-
effort hardening rather than a security boundary (notably on Windows).
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterable
from typing import BinaryIO, Final

from PIL import Image, ImageFile, UnidentifiedImageError

from imageset_guard import codes
from imageset_guard.discovery_models import CANDIDATE_EXTENSIONS, DiscoveredImageCandidate
from imageset_guard.file_access import (
    CandidateChangedError,
    FileIdentity,
    file_identity_from_stream,
    open_regular_file_readonly,
)
from imageset_guard.inspection_models import CandidateInspection, InspectionResult
from imageset_guard.models import (
    Category,
    Finding,
    ScanError,
    Severity,
    finding_sort_key,
    scan_error_sort_key,
)
from imageset_guard.policy import SUPPORTED_FORMATS, Policy
from imageset_guard.policy_eval import evaluate_image_policy
from imageset_guard.profile import ProfileAccumulator

_FORMAT_BY_EXTENSION: Final[dict[str, str]] = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}
_GPS_INFO_TAG: Final = 34853


def _finding(
    code: str,
    severity: Severity,
    category: Category,
    relative_path: str,
    remediation: str,
    *,
    evidence: dict[str, str | int | float | bool] | None = None,
) -> Finding:
    return Finding(
        code=code,
        severity=severity,
        category=category,
        message=codes.DEFAULT_MESSAGES[code],
        relative_path=relative_path,
        evidence=evidence or {},
        remediation=remediation,
    )


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


def _data_failure(
    relative_path: str, code: str, file_identity: FileIdentity
) -> CandidateInspection:
    remediation = {
        codes.IMG_UNIDENTIFIED_IMAGE: (
            "Remove the file or replace it with a valid JPEG, PNG, or WebP image."
        ),
        codes.IMG_DECODE_FAILED: "Remove the file or replace it with a complete, decodable image.",
        codes.IMG_PIXEL_LIMIT_EXCEEDED: (
            "Resize or remove the image so it stays within the configured pixel limit."
        ),
    }[code]
    finding = _finding(
        code,
        Severity.ERROR,
        Category.INTEGRITY,
        relative_path,
        remediation,
    )
    return CandidateInspection(relative_path, True, (finding,), (), file_identity)


def _operational_failure(
    candidate: DiscoveredImageCandidate, exc: OSError
) -> CandidateInspection:
    error = _scan_error(exc, candidate.relative_path, "open")
    return CandidateInspection(candidate.relative_path, False, (), (error,), None)


def _changed_failure(candidate: DiscoveredImageCandidate) -> CandidateInspection:
    error = ScanError(
        code=codes.SYS_CANDIDATE_CHANGED,
        message=codes.DEFAULT_MESSAGES[codes.SYS_CANDIDATE_CHANGED],
        operation="open",
        relative_path=candidate.relative_path,
    )
    return CandidateInspection(candidate.relative_path, False, (), (error,), None)


def _inspect_stream(
    stream: BinaryIO,
    candidate: DiscoveredImageCandidate,
    policy: Policy,
    file_identity: FileIdentity,
    profile_accumulator: ProfileAccumulator | None,
) -> CandidateInspection:
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise RuntimeError(
            "Pillow's process-wide LOAD_TRUNCATED_IMAGES setting is enabled; "
            "ImageSet Guard requires strict decoding"
        )

    findings: list[Finding] = []

    with warnings.catch_warnings(record=True) as decoder_warnings:
        warnings.simplefilter("always")
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(stream) as image:
                detected_format = image.format
                width, height = image.size
                mode = image.mode
                frame_count = int(getattr(image, "n_frames", 1))

                pixel_count = width * height
                if pixel_count > policy.max_pixels:
                    return _data_failure(
                        candidate.relative_path,
                        codes.IMG_PIXEL_LIMIT_EXCEEDED,
                        file_identity,
                    )

                expected_format = _FORMAT_BY_EXTENSION[candidate.extension]
                if detected_format != expected_format:
                    findings.append(
                        _finding(
                            codes.IMG_EXTENSION_FORMAT_MISMATCH,
                            Severity.ERROR,
                            Category.INTEGRITY,
                            candidate.relative_path,
                            "Rename the file to match its detected format, or convert it "
                            "to the expected format.",
                            evidence={
                                "expected_format": expected_format,
                                "detected_format": (
                                    detected_format
                                    if detected_format in SUPPORTED_FORMATS
                                    else "OTHER"
                                ),
                            },
                        )
                    )

                if detected_format not in SUPPORTED_FORMATS:
                    return CandidateInspection(
                        candidate.relative_path,
                        True,
                        tuple(sorted(findings, key=finding_sort_key)),
                        (),
                        file_identity,
                    )

                if frame_count > 1:
                    findings.append(
                        _finding(
                            codes.IMG_MULTIFRAME_UNSUPPORTED,
                            Severity.ERROR,
                            Category.INTEGRITY,
                            candidate.relative_path,
                            "Replace it with a single-frame JPEG, PNG, or WebP image.",
                            evidence={
                                "frame_count": frame_count,
                                "detected_format": detected_format,
                            },
                        )
                    )
                    return CandidateInspection(
                        candidate.relative_path,
                        True,
                        tuple(sorted(findings, key=finding_sort_key)),
                        (),
                        file_identity,
                    )

                image.verify()

            stream.seek(0)
            with Image.open(stream) as decoded:
                decoded.load()
                exif = decoded.getexif()
                has_exif = bool(exif)
                has_gps = _GPS_INFO_TAG in exif
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            return _data_failure(
                candidate.relative_path, codes.IMG_PIXEL_LIMIT_EXCEEDED, file_identity
            )
        except UnidentifiedImageError:
            return _data_failure(
                candidate.relative_path, codes.IMG_UNIDENTIFIED_IMAGE, file_identity
            )
        except (OSError, SyntaxError, ValueError):
            return _data_failure(candidate.relative_path, codes.IMG_DECODE_FAILED, file_identity)

    if decoder_warnings:
        findings.append(
            _finding(
                codes.IMG_DECODER_WARNING,
                Severity.WARNING,
                Category.INTEGRITY,
                candidate.relative_path,
                "Review the image and replace it if the decoder warning cannot be resolved.",
                evidence={"decoder_warning_present": True},
            )
        )

    if has_exif:
        findings.append(
            _finding(
                codes.PRIV_EXIF_PRESENT,
                Severity.WARNING,
                Category.PRIVACY,
                candidate.relative_path,
                "Review the metadata and remove it before sharing if it is not required.",
                evidence={"exif_present": True},
            )
        )
    if has_gps:
        findings.append(
            _finding(
                codes.PRIV_GPS_PRESENT,
                Severity.ERROR,
                Category.PRIVACY,
                candidate.relative_path,
                "Remove GPS metadata before using or sharing this image.",
                evidence={"gps_present": True},
            )
        )

    has_integrity_error = any(
        f.category is Category.INTEGRITY and f.severity is Severity.ERROR for f in findings
    )
    if not has_integrity_error and detected_format is not None:
        if profile_accumulator is not None:
            profile_accumulator.record_accepted(
                image_format=detected_format, mode=mode, width=width, height=height
            )
        findings.extend(
            evaluate_image_policy(
                relative_path=candidate.relative_path,
                image_format=detected_format,
                mode=mode,
                width=width,
                height=height,
                has_exif=has_exif,
                has_gps=has_gps,
                policy=policy,
            )
        )

    findings.sort(key=finding_sort_key)

    return CandidateInspection(
        candidate.relative_path, True, tuple(findings), (), file_identity
    )


def inspect_candidate(
    candidate: DiscoveredImageCandidate,
    policy: Policy | None = None,
    *,
    profile_accumulator: ProfileAccumulator | None = None,
) -> CandidateInspection:
    """Inspect one discovered candidate without exposing exception or metadata values.

    ``profile_accumulator``, if given, is fed this candidate's format/mode/
    dimensions when (and only when) it is accepted -- see
    ``imageset_guard.profile``. It is never required for a correct
    :class:`CandidateInspection` result.
    """
    active_policy = policy or Policy()
    if candidate.extension not in CANDIDATE_EXTENSIONS:
        raise ValueError("candidate extension is outside the v1 candidate set")
    try:
        with open_regular_file_readonly(candidate.absolute_path) as stream:
            identity = file_identity_from_stream(stream)
            return _inspect_stream(stream, candidate, active_policy, identity, profile_accumulator)
    except CandidateChangedError:
        return _changed_failure(candidate)
    except OSError as exc:
        return _operational_failure(candidate, exc)


def inspect_candidates(
    candidates: Iterable[DiscoveredImageCandidate],
    policy: Policy | None = None,
    *,
    profile_accumulator: ProfileAccumulator | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> InspectionResult:
    """Inspect candidates independently and return one canonical aggregate.

    ``progress_callback``, if given, is called after every candidate with
    ``(done, total)``. It exists only for optional CLI progress reporting;
    it is never required for a correct result, and any exception it raises
    propagates immediately (a broken progress reporter must not silently
    corrupt a scan).
    """
    active_policy = policy or Policy()
    ordered = sorted(candidates, key=lambda item: item.relative_path)
    if len({item.relative_path for item in ordered}) != len(ordered):
        raise ValueError("candidates must not contain duplicate relative paths")
    total = len(ordered)
    inspections_list: list[CandidateInspection] = []
    for done, item in enumerate(ordered, start=1):
        inspections_list.append(
            inspect_candidate(item, active_policy, profile_accumulator=profile_accumulator)
        )
        if progress_callback is not None:
            progress_callback(done, total)
    inspections = tuple(inspections_list)
    findings = tuple(
        sorted(
            (finding for item in inspections for finding in item.findings),
            key=finding_sort_key,
        )
    )
    scan_errors = tuple(
        sorted(
            (error for item in inspections for error in item.scan_errors),
            key=scan_error_sort_key,
        )
    )
    return InspectionResult(
        inspections=inspections,
        findings=findings,
        scan_errors=scan_errors,
        examined_file_count=sum(item.examined for item in inspections),
    )
