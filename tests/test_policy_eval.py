"""Tests for imageset_guard.policy_eval: pure policy-to-Finding logic.

Every existing SPLIT/IMG/PRIV/DUP finding code is untouched by policy --
these tests only exercise the new POLICYxxx codes.
"""

from __future__ import annotations

from imageset_guard import codes
from imageset_guard.models import Category, Finding, Severity
from imageset_guard.policy import Policy
from imageset_guard.policy_eval import evaluate_image_policy, evaluate_profile_policy
from imageset_guard.profile_models import DatasetProfile

_PATH = "train/cats/a.jpg"


def _image_policy_findings(policy: Policy, **overrides: object) -> list[Finding]:
    kwargs: dict[str, object] = {
        "relative_path": _PATH,
        "image_format": "JPEG",
        "mode": "RGB",
        "width": 100,
        "height": 100,
        "has_exif": False,
        "has_gps": False,
        "policy": policy,
    }
    kwargs.update(overrides)
    return evaluate_image_policy(**kwargs)  # type: ignore[arg-type]


def _profile(**overrides: object) -> DatasetProfile:
    defaults: dict[str, object] = {
        "candidate_count": 0,
        "examined_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "file_count_by_split": {},
        "file_count_by_class": {},
        "format_counts": {},
        "mode_counts": {},
        "width_min": None,
        "width_max": None,
        "height_min": None,
        "height_max": None,
        "aspect_ratio_min": None,
        "aspect_ratio_max": None,
        "empty_classes": (),
        "class_balance_ratio": None,
        "complete": True,
    }
    defaults.update(overrides)
    return DatasetProfile(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Per-image checks
# ---------------------------------------------------------------------------


def test_no_policy_configured_produces_no_findings() -> None:
    assert _image_policy_findings(Policy()) == []


def test_exif_forbidden_fires_only_when_present_and_forbidden() -> None:
    policy = Policy(exif_policy="forbid")
    assert _image_policy_findings(policy, has_exif=False) == []
    findings = _image_policy_findings(policy, has_exif=True)
    assert [f.code for f in findings] == [codes.POLICY_EXIF_FORBIDDEN]
    assert findings[0].category is Category.POLICY
    assert findings[0].severity is Severity.ERROR
    assert findings[0].evidence == {"exif_present": True}


def test_exif_present_with_allow_policy_produces_no_policy_finding() -> None:
    assert _image_policy_findings(Policy(exif_policy="allow"), has_exif=True) == []


def test_gps_forbidden_fires_only_when_present_and_forbidden() -> None:
    policy = Policy(gps_policy="forbid")
    findings = _image_policy_findings(policy, has_gps=True)
    assert [f.code for f in findings] == [codes.POLICY_GPS_FORBIDDEN]
    assert findings[0].evidence == {"gps_present": True}


def test_allowed_formats_flags_disallowed_format() -> None:
    policy = Policy(allowed_formats=frozenset({"PNG"}))
    findings = _image_policy_findings(policy, image_format="JPEG")
    assert [f.code for f in findings] == [codes.POLICY_FORMAT_NOT_ALLOWED]
    assert findings[0].evidence == {"format": "JPEG"}


def test_allowed_formats_accepts_listed_format() -> None:
    policy = Policy(allowed_formats=frozenset({"JPEG", "PNG"}))
    assert _image_policy_findings(policy, image_format="JPEG") == []


def test_allowed_modes_flags_disallowed_mode() -> None:
    policy = Policy(allowed_modes=frozenset({"RGB"}))
    findings = _image_policy_findings(policy, mode="L")
    assert [f.code for f in findings] == [codes.POLICY_MODE_NOT_ALLOWED]


def test_min_width_violation() -> None:
    policy = Policy(min_width=200)
    findings = _image_policy_findings(policy, width=100)
    assert [f.code for f in findings] == [codes.POLICY_WIDTH_OUT_OF_BOUNDS]
    assert findings[0].evidence == {"width": 100, "min_width": 200}


def test_max_width_violation() -> None:
    policy = Policy(max_width=50)
    findings = _image_policy_findings(policy, width=100)
    assert [f.code for f in findings] == [codes.POLICY_WIDTH_OUT_OF_BOUNDS]
    assert findings[0].evidence == {"width": 100, "max_width": 50}


def test_width_within_bounds_produces_no_finding() -> None:
    policy = Policy(min_width=50, max_width=200)
    assert _image_policy_findings(policy, width=100) == []


def test_width_exactly_at_min_or_max_boundary_is_not_a_violation() -> None:
    # Inclusive bounds: width == min_width or width == max_width must pass.
    assert _image_policy_findings(Policy(min_width=100), width=100) == []
    assert _image_policy_findings(Policy(max_width=100), width=100) == []


def test_width_one_below_min_or_one_above_max_is_a_violation() -> None:
    assert len(_image_policy_findings(Policy(min_width=100), width=99)) == 1
    assert len(_image_policy_findings(Policy(max_width=100), width=101)) == 1


def test_height_exactly_at_min_or_max_boundary_is_not_a_violation() -> None:
    assert _image_policy_findings(Policy(min_height=100), height=100) == []
    assert _image_policy_findings(Policy(max_height=100), height=100) == []


def test_min_and_max_height_violations() -> None:
    below = _image_policy_findings(Policy(min_height=200), height=100)
    above = _image_policy_findings(Policy(max_height=50), height=100)
    assert [f.code for f in below] == [codes.POLICY_HEIGHT_OUT_OF_BOUNDS]
    assert [f.code for f in above] == [codes.POLICY_HEIGHT_OUT_OF_BOUNDS]


def test_aspect_ratio_bounds_violations() -> None:
    # width=200, height=100 -> aspect_ratio = 2.0
    below = _image_policy_findings(
        Policy(min_aspect_ratio=3.0), width=200, height=100
    )
    above = _image_policy_findings(
        Policy(max_aspect_ratio=1.0), width=200, height=100
    )
    assert [f.code for f in below] == [codes.POLICY_ASPECT_RATIO_OUT_OF_BOUNDS]
    assert below[0].evidence["aspect_ratio"] == 2.0
    assert [f.code for f in above] == [codes.POLICY_ASPECT_RATIO_OUT_OF_BOUNDS]


def test_aspect_ratio_within_bounds_produces_no_finding() -> None:
    policy = Policy(min_aspect_ratio=0.5, max_aspect_ratio=2.0)
    assert _image_policy_findings(policy, width=200, height=100) == []


def test_aspect_ratio_exactly_at_boundary_is_not_a_violation() -> None:
    # width=200, height=100 -> aspect_ratio == 2.0 exactly.
    assert _image_policy_findings(Policy(min_aspect_ratio=2.0), width=200, height=100) == []
    assert _image_policy_findings(Policy(max_aspect_ratio=2.0), width=200, height=100) == []


def test_multiple_violations_all_reported_together() -> None:
    policy = Policy(min_width=500, allowed_formats=frozenset({"PNG"}), exif_policy="forbid")
    findings = _image_policy_findings(
        policy, width=10, image_format="JPEG", has_exif=True
    )
    codes_seen = {f.code for f in findings}
    assert codes_seen == {
        codes.POLICY_WIDTH_OUT_OF_BOUNDS,
        codes.POLICY_FORMAT_NOT_ALLOWED,
        codes.POLICY_EXIF_FORBIDDEN,
    }
    assert all(f.relative_path == _PATH for f in findings)


# ---------------------------------------------------------------------------
# Dataset-wide checks
# ---------------------------------------------------------------------------


def test_no_dataset_policy_configured_produces_no_findings() -> None:
    profile = _profile(file_count_by_class={"cats": 1, "dogs": 10}, class_balance_ratio=10.0)
    assert evaluate_profile_policy(profile, Policy()) == ()


def test_min_images_per_class_flags_each_small_class() -> None:
    profile = _profile(file_count_by_class={"cats": 2, "dogs": 10, "birds": 1})
    findings = evaluate_profile_policy(profile, Policy(min_images_per_class=5))
    assert [f.code for f in findings] == [
        codes.POLICY_CLASS_TOO_SMALL,
        codes.POLICY_CLASS_TOO_SMALL,
    ]
    class_names = {f.evidence["class_name"] for f in findings}
    assert class_names == {"cats", "birds"}


def test_min_images_per_class_does_not_flag_classes_meeting_minimum() -> None:
    profile = _profile(file_count_by_class={"cats": 5, "dogs": 10})
    assert evaluate_profile_policy(profile, Policy(min_images_per_class=5)) == ()


def test_min_images_per_class_flags_exactly_one_below_minimum() -> None:
    profile = _profile(file_count_by_class={"cats": 4})
    findings = evaluate_profile_policy(profile, Policy(min_images_per_class=5))
    assert [f.code for f in findings] == [codes.POLICY_CLASS_TOO_SMALL]


def test_max_class_imbalance_ratio_violation() -> None:
    profile = _profile(
        file_count_by_class={"cats": 1, "dogs": 10}, class_balance_ratio=10.0
    )
    findings = evaluate_profile_policy(profile, Policy(max_class_imbalance_ratio=5.0))
    assert [f.code for f in findings] == [codes.POLICY_CLASS_IMBALANCE]
    assert findings[0].evidence == {"ratio": 10.0, "maximum": 5.0}


def test_max_class_imbalance_ratio_not_violated_stays_silent() -> None:
    profile = _profile(
        file_count_by_class={"cats": 8, "dogs": 10}, class_balance_ratio=1.25
    )
    assert evaluate_profile_policy(profile, Policy(max_class_imbalance_ratio=5.0)) == ()


def test_max_class_imbalance_ratio_exactly_at_boundary_is_not_a_violation() -> None:
    profile = _profile(file_count_by_class={"cats": 1, "dogs": 5}, class_balance_ratio=5.0)
    assert evaluate_profile_policy(profile, Policy(max_class_imbalance_ratio=5.0)) == ()


def test_max_class_imbalance_ratio_with_no_balance_ratio_available_is_silent() -> None:
    profile = _profile(file_count_by_class={"cats": 5}, class_balance_ratio=None)
    assert evaluate_profile_policy(profile, Policy(max_class_imbalance_ratio=1.0)) == ()


def test_profile_findings_are_canonically_sorted() -> None:
    profile = _profile(file_count_by_class={"zebra": 1, "apple": 1})
    findings = evaluate_profile_policy(profile, Policy(min_images_per_class=5))
    assert [f.evidence["class_name"] for f in findings] == ["apple", "zebra"]
