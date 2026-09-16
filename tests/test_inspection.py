"""Phase 3 image-integrity and privacy inspection tests.

Every image fixture is generated locally by Pillow.  The test suite never
downloads or stores third-party images.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

import pytest
from PIL import Image, ImageFile, features

from imageset_guard import codes, file_access, inspection
from imageset_guard.discovery_models import DiscoveredImageCandidate
from imageset_guard.inspection import inspect_candidate, inspect_candidates
from imageset_guard.inspection_models import CandidateInspection, InspectionResult
from imageset_guard.policy import Policy


def _save_image(
    path: Path, *, image_format: str | None = None, exif: Image.Exif | None = None
) -> None:
    kwargs: dict[str, object] = {}
    if exif is not None:
        kwargs["exif"] = exif
    Image.new("RGB", (8, 6), (20, 40, 60)).save(path, format=image_format, **kwargs)


def _candidate(path: Path, relative: str | None = None) -> DiscoveredImageCandidate:
    suffix = path.suffix.lower()
    return DiscoveredImageCandidate(
        absolute_path=path.absolute(),
        relative_path=relative or f"train/cats/{path.name}",
        split="train",
        class_name="cats",
        extension=suffix,
    )


def _codes(result: CandidateInspection | InspectionResult) -> set[str]:
    return {item.code for item in result.findings}


@pytest.mark.parametrize(
    ("suffix", "image_format"),
    [(".jpg", "JPEG"), (".jpeg", "JPEG"), (".png", "PNG")],
)
def test_clean_static_supported_image_passes(
    tmp_path: Path, suffix: str, image_format: str
) -> None:
    path = tmp_path / f"clean{suffix}"
    _save_image(path, image_format=image_format)
    result = inspect_candidate(_candidate(path))
    assert result.examined is True
    assert result.findings == ()
    assert result.scan_errors == ()


def test_successful_inspection_does_not_modify_file_bytes(tmp_path: Path) -> None:
    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")
    before = hashlib.sha256(path.read_bytes()).digest()
    inspect_candidate(_candidate(path))
    after = hashlib.sha256(path.read_bytes()).digest()
    assert after == before


@pytest.mark.skipif(not features.check("webp"), reason="Pillow build has no WebP support")
def test_clean_static_webp_passes(tmp_path: Path) -> None:
    path = tmp_path / "clean.webp"
    _save_image(path, image_format="WEBP")
    assert inspect_candidate(_candidate(path)).findings == ()


def test_non_image_bytes_are_an_integrity_finding_not_scan_error(tmp_path: Path) -> None:
    path = tmp_path / "fake.jpg"
    path.write_bytes(b"not an image")
    result = inspect_candidate(_candidate(path))
    assert result.examined is True
    assert _codes(result) == {codes.IMG_UNIDENTIFIED_IMAGE}
    assert result.scan_errors == ()


def test_truncated_image_is_rejected_by_verify_or_full_decode(tmp_path: Path) -> None:
    path = tmp_path / "truncated.jpg"
    _save_image(path, image_format="JPEG")
    payload = path.read_bytes()
    path.write_bytes(payload[: max(20, len(payload) // 2)])
    result = inspect_candidate(_candidate(path))
    assert result.examined is True
    assert _codes(result) <= {codes.IMG_UNIDENTIFIED_IMAGE, codes.IMG_DECODE_FAILED}
    assert _codes(result)


def test_extension_format_mismatch_is_reported_after_successful_decode(tmp_path: Path) -> None:
    path = tmp_path / "actually_png.jpg"
    _save_image(path, image_format="PNG")
    result = inspect_candidate(_candidate(path))
    assert _codes(result) == {codes.IMG_EXTENSION_FORMAT_MISMATCH}
    finding = result.findings[0]
    assert finding.evidence == {"expected_format": "JPEG", "detected_format": "PNG"}


def test_unsupported_content_behind_supported_extension_is_not_decoded(tmp_path: Path) -> None:
    path = tmp_path / "actually_gif.jpg"
    _save_image(path, image_format="GIF")
    result = inspect_candidate(_candidate(path))
    assert _codes(result) == {codes.IMG_EXTENSION_FORMAT_MISMATCH}
    assert result.findings[0].evidence["detected_format"] == "OTHER"


def test_configured_pixel_limit_is_enforced_before_pixel_decode(tmp_path: Path) -> None:
    path = tmp_path / "large.png"
    _save_image(path, image_format="PNG")
    result = inspect_candidate(_candidate(path), Policy(max_pixels=10))
    assert _codes(result) == {codes.IMG_PIXEL_LIMIT_EXCEEDED}


@pytest.mark.parametrize("size", [(15, 10), (20, 20)])
def test_pillow_decompression_bomb_warning_and_error_are_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, size: tuple[int, int]
) -> None:
    path = tmp_path / "bomb.png"
    Image.new("RGB", size).save(path)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    result = inspect_candidate(_candidate(path), Policy(max_pixels=10_000))
    assert _codes(result) == {codes.IMG_PIXEL_LIMIT_EXCEEDED}


def test_inspection_never_changes_pillow_global_pixel_limit(tmp_path: Path) -> None:
    path = tmp_path / "clean.png"
    _save_image(path, image_format="PNG")
    before = Image.MAX_IMAGE_PIXELS
    inspect_candidate(_candidate(path), Policy(max_pixels=1_000))
    assert before == Image.MAX_IMAGE_PIXELS


@pytest.mark.skipif(not features.check("webp"), reason="Pillow build has no WebP support")
def test_animated_webp_is_rejected_without_first_frame_semantics(tmp_path: Path) -> None:
    path = tmp_path / "animated.webp"
    frames = [Image.new("RGB", (4, 4), color) for color in ("red", "blue")]
    try:
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=10, loop=0)
    finally:
        for frame in frames:
            frame.close()
    result = inspect_candidate(_candidate(path))
    assert _codes(result) == {codes.IMG_MULTIFRAME_UNSUPPORTED}
    assert result.findings[0].evidence["frame_count"] == 2


def test_exif_presence_is_reported_without_values(tmp_path: Path) -> None:
    secret = "PRIVATE-CAMERA-SERIAL-123"
    exif = Image.Exif()
    exif[271] = secret
    path = tmp_path / "exif.jpg"
    _save_image(path, image_format="JPEG", exif=exif)
    result = inspect_candidate(_candidate(path))
    assert _codes(result) == {codes.PRIV_EXIF_PRESENT}
    assert result.findings[0].evidence == {"exif_present": True}
    assert secret not in repr(result)


def test_gps_tag_presence_is_reported_without_opening_gps_ifd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "PRIVATE-GPS-VALUE"
    exif = Image.Exif()
    exif[34853] = {1: secret}
    path = tmp_path / "gps.jpg"
    _save_image(path, image_format="JPEG", exif=exif)

    def forbidden_get_ifd(self: Image.Exif, tag: int) -> object:
        raise AssertionError(f"GPS IFD values must never be opened: {tag}")

    monkeypatch.setattr(Image.Exif, "get_ifd", forbidden_get_ifd)
    result = inspect_candidate(_candidate(path))
    assert _codes(result) == {codes.PRIV_EXIF_PRESENT, codes.PRIV_GPS_PRESENT}
    assert secret not in repr(result)
    assert all(set(item.evidence.values()) <= {True} for item in result.findings)


def test_exif_parser_failure_is_sanitized_as_decode_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")
    secret = "PRIVATE EXIF VALUE FROM C:/Users/private-person"

    def broken_exif(self: Image.Image) -> Image.Exif:
        raise ValueError(secret)

    monkeypatch.setattr(Image.Image, "getexif", broken_exif)
    result = inspect_candidate(_candidate(path))
    assert _codes(result) == {codes.IMG_DECODE_FAILED}
    assert secret not in repr(result)


def test_missing_file_is_unexamined_and_exception_text_does_not_leak(tmp_path: Path) -> None:
    path = tmp_path / "secret-user-path.jpg"
    candidate = _candidate(path)
    result = inspect_candidate(candidate)
    assert result.examined is False
    assert result.findings == ()
    assert result.scan_errors[0].code == codes.SYS_PATH_VANISHED
    assert str(tmp_path) not in repr(result)


def test_directory_replacing_candidate_is_not_opened(tmp_path: Path) -> None:
    path = tmp_path / "changed.jpg"
    path.mkdir()
    result = inspect_candidate(_candidate(path))
    assert result.examined is False
    assert result.scan_errors[0].code == codes.SYS_CANDIDATE_CHANGED


def test_descriptor_identity_change_is_treated_as_operational_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "changed.jpg"
    _save_image(path, image_format="JPEG")
    monkeypatch.setattr(file_access, "same_file_identity", lambda before, after: False)
    result = inspect_candidate(_candidate(path))
    assert result.examined is False
    assert result.scan_errors[0].code == codes.SYS_CANDIDATE_CHANGED


def test_file_descriptor_is_closed_after_inspection(tmp_path: Path) -> None:
    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")
    inspect_candidate(_candidate(path))
    renamed = tmp_path / "renamed.jpg"
    path.rename(renamed)
    assert renamed.is_file()


def test_unexpected_internal_exception_is_not_mislabeled_as_bad_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")

    def defect(*args: object, **kwargs: object) -> object:
        raise RuntimeError("internal defect")

    monkeypatch.setattr(inspection, "_inspect_stream", defect)
    with pytest.raises(RuntimeError, match="internal defect"):
        inspect_candidate(_candidate(path))


def test_process_wide_truncated_image_opt_in_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with pytest.raises(RuntimeError, match="strict decoding"):
        inspect_candidate(_candidate(path))


def test_decoder_warning_is_sanitized_and_does_not_reach_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")
    real_open = Image.open
    secret = "C:/Users/private-person/source.jpg"

    def warning_open(*args: object, **kwargs: object) -> Image.Image:
        import warnings

        warnings.warn(secret, UserWarning, stacklevel=1)
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Image, "open", warning_open)
    result = inspect_candidate(_candidate(path))
    captured = capsys.readouterr()
    assert codes.IMG_DECODER_WARNING in _codes(result)
    assert secret not in repr(result)
    assert secret not in captured.err


def test_batch_continues_after_bad_image_and_is_canonical(tmp_path: Path) -> None:
    good = tmp_path / "b.jpg"
    bad = tmp_path / "a.jpg"
    _save_image(good, image_format="JPEG")
    bad.write_bytes(b"bad")
    result = inspect_candidates(
        [_candidate(good, "train/cats/b.jpg"), _candidate(bad, "train/cats/a.jpg")]
    )
    assert [item.relative_path for item in result.inspections] == [
        "train/cats/a.jpg",
        "train/cats/b.jpg",
    ]
    assert result.examined_file_count == 2
    assert _codes(result) == {codes.IMG_UNIDENTIFIED_IMAGE}


def test_operational_error_message_never_uses_raw_os_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "image.jpg"
    _save_image(path, image_format="JPEG")
    secret = "C:/Users/private-person/secret.jpg"

    @contextlib.contextmanager
    def denied(candidate: DiscoveredImageCandidate) -> Iterator[BinaryIO]:
        raise PermissionError(13, secret)
        yield  # pragma: no cover

    monkeypatch.setattr(inspection, "open_regular_file_readonly", denied)
    result = inspect_candidate(_candidate(path))
    assert result.scan_errors[0].code == codes.SYS_PERMISSION_DENIED
    assert secret not in repr(result)


def test_inspection_opens_candidate_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")
    real_open = os.open
    seen_flags: list[int] = []

    def recording_open(target: Path, flags: int) -> int:
        seen_flags.append(flags)
        return real_open(target, flags)

    monkeypatch.setattr(os, "open", recording_open)
    inspect_candidate(_candidate(path))
    assert seen_flags
    assert all(flags & os.O_WRONLY == 0 and flags & os.O_RDWR == 0 for flags in seen_flags)


def test_results_are_json_serializable_without_absolute_path(tmp_path: Path) -> None:
    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")
    result = inspect_candidate(_candidate(path))
    public = {
        "relative_path": result.relative_path,
        "examined": result.examined,
        "findings": [dict(item.evidence) for item in result.findings],
        "scan_errors": [item.message for item in result.scan_errors],
    }
    payload = json.dumps(public)
    assert str(tmp_path) not in payload


# ---------------------------------------------------------------------------
# v0.2: per-image policy findings and profile accumulation, through the
# real Pillow decode path (not synthetic values) -- proves the wiring in
# _inspect_stream, not just the pure policy_eval functions in isolation.
# ---------------------------------------------------------------------------


def test_policy_min_width_violation_fires_through_real_decode(tmp_path: Path) -> None:
    path = tmp_path / "small.jpg"
    _save_image(path, image_format="JPEG")  # 8x6
    policy = Policy(min_width=100)
    result = inspect_candidate(_candidate(path), policy)
    assert codes.POLICY_WIDTH_OUT_OF_BOUNDS in _codes(result)
    finding = next(f for f in result.findings if f.code == codes.POLICY_WIDTH_OUT_OF_BOUNDS)
    assert finding.category.value == "policy"
    assert finding.evidence == {"width": 8, "min_width": 100}


def test_policy_exif_forbidden_fires_alongside_priv001(tmp_path: Path) -> None:
    path = tmp_path / "with_exif.jpg"
    exif = Image.Exif()
    exif[305] = "camera-software"
    _save_image(path, image_format="JPEG", exif=exif)
    policy = Policy(exif_policy="forbid")
    result = inspect_candidate(_candidate(path), policy)
    codes_seen = _codes(result)
    # Both fire -- the unconditional PRIV001 keeps its original meaning,
    # and the new POLICY001 is additive, never a replacement for it.
    assert codes.PRIV_EXIF_PRESENT in codes_seen
    assert codes.POLICY_EXIF_FORBIDDEN in codes_seen


def test_policy_allowed_formats_violation_still_hash_eligible(tmp_path: Path) -> None:
    # A policy-format violation is a POLICY finding, not an INTEGRITY
    # error -- it must never block hashing/duplicate detection.
    from imageset_guard.hashing import is_hash_eligible

    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")
    policy = Policy(allowed_formats=frozenset({"PNG"}))
    result = inspect_candidate(_candidate(path), policy)
    assert codes.POLICY_FORMAT_NOT_ALLOWED in _codes(result)
    assert is_hash_eligible(result) is True


def test_no_policy_configured_produces_no_policy_category_findings(tmp_path: Path) -> None:
    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")
    result = inspect_candidate(_candidate(path))  # default Policy()
    assert all(f.category.value != "policy" for f in result.findings)


def test_profile_accumulator_is_fed_only_for_accepted_candidates(tmp_path: Path) -> None:
    from imageset_guard.profile import ProfileAccumulator

    accepted_path = tmp_path / "clean.jpg"
    _save_image(accepted_path, image_format="JPEG")
    corrupt_path = tmp_path / "bad.jpg"
    corrupt_path.write_bytes(b"not an image")

    accumulator = ProfileAccumulator()
    inspect_candidates(
        [
            _candidate(accepted_path, "train/cats/clean.jpg"),
            _candidate(corrupt_path, "train/cats/bad.jpg"),
        ],
        profile_accumulator=accumulator,
    )
    assert accumulator.accepted_count == 1
    assert accumulator.format_counts == {"JPEG": 1}
    assert accumulator.width_bounds == (8, 8)


def test_progress_callback_is_called_once_per_candidate_in_order(tmp_path: Path) -> None:
    paths = [tmp_path / f"{i}.jpg" for i in range(3)]
    for path in paths:
        _save_image(path, image_format="JPEG")
    candidates = [_candidate(p, f"train/cats/{p.name}") for p in paths]

    calls: list[tuple[int, int]] = []

    def record(done: int, total: int) -> None:
        calls.append((done, total))

    inspect_candidates(candidates, progress_callback=record)
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_progress_callback_exception_propagates_and_does_not_corrupt_scan(tmp_path: Path) -> None:
    path = tmp_path / "clean.jpg"
    _save_image(path, image_format="JPEG")

    def broken_callback(done: int, total: int) -> None:
        raise RuntimeError("progress reporter is broken")

    with pytest.raises(RuntimeError, match="progress reporter is broken"):
        inspect_candidates([_candidate(path)], progress_callback=broken_callback)
