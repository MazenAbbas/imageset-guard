"""Tests for imageset_guard.profile_models.DatasetProfile invariants."""

from __future__ import annotations

import pytest

from imageset_guard.profile_models import DatasetProfile


def _profile(**overrides: object) -> DatasetProfile:
    defaults: dict[str, object] = {
        "candidate_count": 2,
        "examined_count": 2,
        "accepted_count": 2,
        "rejected_count": 0,
        "file_count_by_split": {"train": 2},
        "file_count_by_class": {"cats": 2},
        "format_counts": {"JPEG": 2},
        "mode_counts": {"RGB": 2},
        "width_min": 10,
        "width_max": 20,
        "height_min": 10,
        "height_max": 20,
        "aspect_ratio_min": 1.0,
        "aspect_ratio_max": 1.0,
        "empty_classes": (),
        "class_balance_ratio": None,
        "complete": True,
    }
    defaults.update(overrides)
    return DatasetProfile(**defaults)  # type: ignore[arg-type]


def test_accepts_valid_profile() -> None:
    profile = _profile()
    assert profile.accepted_count == 2
    assert profile.complete is True


def test_accepted_plus_rejected_must_equal_examined() -> None:
    with pytest.raises(ValueError, match="accepted_count"):
        _profile(examined_count=2, accepted_count=2, rejected_count=1)


def test_examined_cannot_exceed_candidate_count() -> None:
    with pytest.raises(ValueError, match="examined_count"):
        _profile(candidate_count=1, examined_count=2, accepted_count=2, rejected_count=0)


@pytest.mark.parametrize(
    "field_name", ["candidate_count", "examined_count", "accepted_count", "rejected_count"]
)
def test_negative_counts_are_rejected(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        _profile(**{field_name: -1})


def test_zero_accepted_requires_no_dimension_bounds() -> None:
    with pytest.raises(ValueError, match="dimension bounds"):
        _profile(
            examined_count=0,
            accepted_count=0,
            rejected_count=0,
            width_min=10,
            width_max=20,
            height_min=10,
            height_max=20,
            aspect_ratio_min=1.0,
            aspect_ratio_max=1.0,
        )


def test_positive_accepted_requires_dimension_bounds() -> None:
    with pytest.raises(ValueError, match="without any recorded"):
        _profile(width_min=None, width_max=None, height_min=None, height_max=None)


def test_zero_accepted_with_no_bounds_is_valid() -> None:
    profile = _profile(
        candidate_count=0,
        examined_count=0,
        accepted_count=0,
        rejected_count=0,
        file_count_by_split={},
        file_count_by_class={},
        format_counts={},
        mode_counts={},
        width_min=None,
        width_max=None,
        height_min=None,
        height_max=None,
        aspect_ratio_min=None,
        aspect_ratio_max=None,
    )
    assert profile.accepted_count == 0


@pytest.mark.parametrize(
    ("lo", "hi"), [(20, 10)]
)
def test_width_min_cannot_exceed_width_max(lo: int, hi: int) -> None:
    with pytest.raises(ValueError, match="width_min"):
        _profile(width_min=lo, width_max=hi)


def test_width_min_equal_to_width_max_is_valid() -> None:
    profile = _profile(width_min=10, width_max=10)
    assert profile.width_min == profile.width_max == 10


def test_width_bounds_must_both_be_set_or_both_none() -> None:
    with pytest.raises(ValueError, match="width_min and width_max"):
        _profile(width_min=10, width_max=None)


def test_file_count_by_split_rejects_unrecognized_split() -> None:
    with pytest.raises(ValueError, match="split"):
        _profile(file_count_by_split={"bogus": 1})


def test_file_count_by_class_rejects_empty_class_name() -> None:
    with pytest.raises(ValueError):
        _profile(file_count_by_class={"": 1})


def test_empty_classes_must_be_split_slash_class_strings() -> None:
    with pytest.raises(ValueError, match="split/class"):
        _profile(empty_classes=("no_slash_here",))


def test_empty_classes_are_sorted_deterministically() -> None:
    profile = _profile(empty_classes=("train/zebra", "train/apple"))
    assert profile.empty_classes == ("train/apple", "train/zebra")


@pytest.mark.parametrize("bad_ratio", [0.0, -1.0, 0.999])
def test_class_balance_ratio_must_be_at_least_one(bad_ratio: float) -> None:
    with pytest.raises(ValueError, match="class_balance_ratio"):
        _profile(class_balance_ratio=bad_ratio)


def test_class_balance_ratio_of_exactly_one_is_valid() -> None:
    assert _profile(class_balance_ratio=1.0).class_balance_ratio == 1.0


def test_complete_must_be_a_bool() -> None:
    with pytest.raises(ValueError, match="complete"):
        _profile(complete=1)


def test_profile_is_frozen() -> None:
    profile = _profile()
    with pytest.raises(AttributeError):
        profile.complete = False  # type: ignore[misc]


def test_nonneg_mapping_rejects_negative_value() -> None:
    with pytest.raises(ValueError, match="format_counts"):
        _profile(format_counts={"JPEG": -1})


@pytest.mark.parametrize("bad_aspect", [0.0, -1.0, float("inf")])
def test_aspect_ratio_bounds_must_be_finite_and_positive(bad_aspect: float) -> None:
    with pytest.raises(ValueError, match="aspect_ratio"):
        _profile(aspect_ratio_min=bad_aspect, aspect_ratio_max=bad_aspect)
