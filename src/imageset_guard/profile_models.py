"""Immutable, deterministic dataset-profile facts (v0.2).

A :class:`DatasetProfile` reports *observed facts* about a dataset's
structure and image content -- counts, boundaries, and ratios -- computed
with bounded, streaming aggregation (no per-image record is retained; only
running counts and min/max bounds are kept while scanning). It never
contains a decoded image, a file path, a digest, or any per-file record.

Facts are deliberately separate from judgment: nothing here decides that a
dataset is "bad". A fact becomes a policy violation only when
``imageset_guard.policy`` evaluates it against a user-configured limit,
producing a :class:`~imageset_guard.models.Finding` with
:class:`~imageset_guard.models.Category.POLICY`. This module has no
opinion about what counts as "too imbalanced" or "too small" -- see
``imageset_guard.policy_eval``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

_VALID_SPLITS: Final[frozenset[str]] = frozenset({"train", "validation", "test"})


def _validate_path_component(value: object, *, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty str, got: {value!r}")
    if "/" in value or "\\" in value:
        raise ValueError(f"{field_name} must not contain a path separator: {value!r}")


def _validate_nonneg_int_mapping(
    mapping: Mapping[str, int], *, field_name: str
) -> Mapping[str, int]:
    for key, value in mapping.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{field_name} keys must be non-empty strings, got: {key!r}")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                f"{field_name}[{key!r}] must be a non-negative int, got: {value!r}"
            )
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    """Deterministic, bounded-memory facts about one scanned dataset.

    ``candidate_count`` is every file discovery considered a candidate by
    extension. ``examined_count`` is how many candidates inspection reached
    a deterministic conclusion about (matches
    :class:`~imageset_guard.inspection_models.InspectionResult`
    .examined_file_count`). ``accepted_count`` is the subset that is safe,
    decodable image content (the same boundary
    :func:`imageset_guard.hashing.is_hash_eligible` uses) -- format/mode/
    dimension facts below are computed only over accepted files, since
    format/dimensions are not reliably known for a file that never decoded.
    ``rejected_count`` is ``examined_count - accepted_count``:
    files inspection reached a conclusion about but which failed integrity
    checks (unidentified, undecodable, oversized, multi-frame, or a
    format/extension mismatch). Files blocked by an operational failure
    are neither examined nor rejected; they appear only as ``ScanError``.
    """

    candidate_count: int
    examined_count: int
    accepted_count: int
    rejected_count: int

    file_count_by_split: Mapping[str, int]
    file_count_by_class: Mapping[str, int]
    format_counts: Mapping[str, int]
    mode_counts: Mapping[str, int]

    width_min: int | None
    width_max: int | None
    height_min: int | None
    height_max: int | None
    aspect_ratio_min: float | None
    aspect_ratio_max: float | None

    empty_classes: tuple[str, ...]
    class_balance_ratio: float | None

    complete: bool

    def __post_init__(self) -> None:
        for name in ("candidate_count", "examined_count", "accepted_count", "rejected_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative int, got: {value!r}")
        if self.examined_count > self.candidate_count:
            raise ValueError("examined_count cannot exceed candidate_count")
        if self.accepted_count + self.rejected_count != self.examined_count:
            raise ValueError("accepted_count + rejected_count must equal examined_count")

        object.__setattr__(
            self,
            "file_count_by_split",
            _validate_nonneg_int_mapping(
                self.file_count_by_split, field_name="file_count_by_split"
            ),
        )
        for split in self.file_count_by_split:
            if split not in _VALID_SPLITS:
                raise ValueError(f"file_count_by_split has an unrecognized split: {split!r}")
        object.__setattr__(
            self,
            "file_count_by_class",
            _validate_nonneg_int_mapping(
                self.file_count_by_class, field_name="file_count_by_class"
            ),
        )
        for class_name in self.file_count_by_class:
            _validate_path_component(class_name, field_name="class name")
        object.__setattr__(
            self,
            "format_counts",
            _validate_nonneg_int_mapping(self.format_counts, field_name="format_counts"),
        )
        object.__setattr__(
            self,
            "mode_counts",
            _validate_nonneg_int_mapping(self.mode_counts, field_name="mode_counts"),
        )

        _require_bounds_consistent(self.width_min, self.width_max, field_name="width")
        _require_bounds_consistent(self.height_min, self.height_max, field_name="height")
        _require_bounds_consistent(
            self.aspect_ratio_min, self.aspect_ratio_max, field_name="aspect_ratio"
        )
        for value in (self.aspect_ratio_min, self.aspect_ratio_max):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"aspect_ratio bound must be a finite positive float: {value!r}")
        has_dimension_facts = self.width_min is not None
        if has_dimension_facts and self.accepted_count == 0:
            raise ValueError("dimension bounds require at least one accepted image")
        if not has_dimension_facts and self.accepted_count > 0:
            raise ValueError("accepted images without any recorded dimension bounds")

        object.__setattr__(
            self,
            "empty_classes",
            tuple(sorted(self.empty_classes)),
        )
        for entry in self.empty_classes:
            if not isinstance(entry, str) or "/" not in entry:
                raise ValueError(
                    f"empty_classes entries must be 'split/class' strings, got: {entry!r}"
                )

        if self.class_balance_ratio is not None and (
            not math.isfinite(self.class_balance_ratio) or self.class_balance_ratio < 1.0
        ):
            raise ValueError(
                f"class_balance_ratio must be a finite float >= 1.0, got: "
                f"{self.class_balance_ratio!r}"
            )

        if not isinstance(self.complete, bool):
            raise ValueError(f"complete must be a bool, got: {type(self.complete).__name__}")


def _require_bounds_consistent(
    lo: int | float | None, hi: int | float | None, *, field_name: str
) -> None:
    if (lo is None) != (hi is None):
        raise ValueError(f"{field_name}_min and {field_name}_max must both be set or both None")
    if lo is not None and hi is not None and lo > hi:
        raise ValueError(f"{field_name}_min ({lo!r}) must not exceed {field_name}_max ({hi!r})")
