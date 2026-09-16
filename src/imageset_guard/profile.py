"""Streaming, bounded-memory accumulation of dataset-profile facts (v0.2).

:class:`ProfileAccumulator` is fed one accepted image's format/mode/
dimensions at a time by ``imageset_guard.inspection`` as it examines each
candidate, in isolation, one file at a time -- it never retains a decoded
image or a per-file record, only running counts and min/max bounds. Its
state is bounded by the number of distinct formats/modes observed (at
most a handful), not by the number of files scanned.

:func:`build_profile` combines that accumulator with discovery's own
per-(split, class) candidate counts (already computed for structural
findings) into one immutable, deterministic :class:`DatasetProfile`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from imageset_guard.discovery_models import DiscoveryResult
from imageset_guard.inspection_models import InspectionResult
from imageset_guard.models import ScanError
from imageset_guard.profile_models import DatasetProfile

_ROUND_DIGITS: Final = 6


class ProfileAccumulator:
    """Mutable, bounded-memory accumulator for accepted-image facts.

    Not part of any public result contract -- an internal helper threaded
    through inspection for the duration of one scan, then discarded once
    :func:`build_profile` has read its final state.
    """

    __slots__ = (
        "_accepted_count",
        "_aspect_max",
        "_aspect_min",
        "_format_counts",
        "_height_max",
        "_height_min",
        "_mode_counts",
        "_width_max",
        "_width_min",
    )

    def __init__(self) -> None:
        self._accepted_count = 0
        self._format_counts: dict[str, int] = {}
        self._mode_counts: dict[str, int] = {}
        self._width_min: int | None = None
        self._width_max: int | None = None
        self._height_min: int | None = None
        self._height_max: int | None = None
        self._aspect_min: float | None = None
        self._aspect_max: float | None = None

    def record_accepted(self, *, image_format: str, mode: str, width: int, height: int) -> None:
        """Fold one accepted image's facts into the running aggregate."""
        self._accepted_count += 1
        self._format_counts[image_format] = self._format_counts.get(image_format, 0) + 1
        self._mode_counts[mode] = self._mode_counts.get(mode, 0) + 1
        self._width_min = width if self._width_min is None else min(self._width_min, width)
        self._width_max = width if self._width_max is None else max(self._width_max, width)
        self._height_min = height if self._height_min is None else min(self._height_min, height)
        self._height_max = height if self._height_max is None else max(self._height_max, height)
        ratio = round(width / height, _ROUND_DIGITS)
        self._aspect_min = ratio if self._aspect_min is None else min(self._aspect_min, ratio)
        self._aspect_max = ratio if self._aspect_max is None else max(self._aspect_max, ratio)

    @property
    def accepted_count(self) -> int:
        return self._accepted_count

    @property
    def format_counts(self) -> dict[str, int]:
        return dict(self._format_counts)

    @property
    def mode_counts(self) -> dict[str, int]:
        return dict(self._mode_counts)

    @property
    def width_bounds(self) -> tuple[int, int] | None:
        if self._width_min is None or self._width_max is None:
            return None
        return self._width_min, self._width_max

    @property
    def height_bounds(self) -> tuple[int, int] | None:
        if self._height_min is None or self._height_max is None:
            return None
        return self._height_min, self._height_max

    @property
    def aspect_ratio_bounds(self) -> tuple[float, float] | None:
        if self._aspect_min is None or self._aspect_max is None:
            return None
        return self._aspect_min, self._aspect_max


def build_profile(
    discovery: DiscoveryResult,
    inspection: InspectionResult,
    accumulator: ProfileAccumulator,
    *,
    scan_errors: Sequence[ScanError],
) -> DatasetProfile:
    """Assemble the final, immutable :class:`DatasetProfile` for one scan.

    ``scan_errors`` must be the *complete* set for the scan (discovery,
    inspection, and hashing combined): a single operational failure
    anywhere makes the profile's aggregate facts potentially incomplete.
    """
    candidate_count = len(discovery.candidates)
    examined_count = inspection.examined_file_count
    accepted_count = accumulator.accepted_count
    rejected_count = examined_count - accepted_count

    file_count_by_split: dict[str, int] = {}
    file_count_by_class: dict[str, int] = {}
    empty_classes: list[str] = []
    all_subtrees_complete = True

    for count in discovery.class_counts:
        file_count_by_split[count.split] = (
            file_count_by_split.get(count.split, 0) + count.candidate_count
        )
        file_count_by_class[count.class_name] = (
            file_count_by_class.get(count.class_name, 0) + count.candidate_count
        )
        if not count.is_complete:
            all_subtrees_complete = False
        elif count.candidate_count == 0:
            empty_classes.append(f"{count.split}/{count.class_name}")

    non_empty_class_counts = [c for c in file_count_by_class.values() if c > 0]
    class_balance_ratio = (
        max(non_empty_class_counts) / min(non_empty_class_counts)
        if len(non_empty_class_counts) >= 2
        else None
    )

    width_bounds = accumulator.width_bounds
    height_bounds = accumulator.height_bounds
    aspect_bounds = accumulator.aspect_ratio_bounds

    complete = all_subtrees_complete and not scan_errors

    return DatasetProfile(
        candidate_count=candidate_count,
        examined_count=examined_count,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        file_count_by_split=file_count_by_split,
        file_count_by_class=file_count_by_class,
        format_counts=accumulator.format_counts,
        mode_counts=accumulator.mode_counts,
        width_min=width_bounds[0] if width_bounds else None,
        width_max=width_bounds[1] if width_bounds else None,
        height_min=height_bounds[0] if height_bounds else None,
        height_max=height_bounds[1] if height_bounds else None,
        aspect_ratio_min=aspect_bounds[0] if aspect_bounds else None,
        aspect_ratio_max=aspect_bounds[1] if aspect_bounds else None,
        empty_classes=tuple(empty_classes),
        class_balance_ratio=class_balance_ratio,
        complete=complete,
    )
