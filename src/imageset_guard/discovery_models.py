"""Typed, immutable data produced by the discovery layer.

``DiscoveredImageCandidate.absolute_path`` exists purely so later phases
can open the file; it is never written to any report. Nothing here defines
a ``to_dict``/``as_dict``/``to_json`` convenience precisely so no call site
is tempted to serialize one of these objects wholesale -- code that builds
a public report must explicitly select the safe fields (``relative_path``,
``split``, ``class_name``, ``extension``) itself. ``repr()`` may still show
``absolute_path`` for local debugging (e.g. in a failed assertion); that is
not "the report" and is fine.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeVar

from imageset_guard.models import Finding, ScanError, finding_sort_key, scan_error_sort_key
from imageset_guard.models import validate_relative_path as _validate_relative_path

_T = TypeVar("_T")
_K = TypeVar("_K", bound="str | tuple[str, ...]")

_VALID_SPLITS: Final[frozenset[str]] = frozenset({"train", "validation", "test"})

#: The only extensions discovery ever produces for a candidate, and the
#: only ones DiscoveredImageCandidate.extension accepts -- defined here
#: once so discovery.py (which does the case-insensitive matching that
#: *produces* these values) and this module (which validates them) can
#: never drift apart.
CANDIDATE_EXTENSIONS: Final[frozenset[str]] = frozenset({".jpg", ".jpeg", ".png", ".webp"})


def _validate_split(value: object, *, field_name: str = "split") -> None:
    if not isinstance(value, str) or value not in _VALID_SPLITS:
        raise ValueError(f"{field_name} must be one of {sorted(_VALID_SPLITS)}, got: {value!r}")


def validate_path_component(value: object, *, field_name: str) -> None:
    """Validate that ``value`` is a single, safely representable path
    component: a non-empty ``str``, not ``.``/``..``, no path separator, no
    control character. Shared by ``class_name`` on both
    :class:`DiscoveredImageCandidate` and :class:`ClassImageCount` so the
    rule can't drift between the two.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a str, got {type(value).__name__}: {value!r}")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if value in (".", ".."):
        raise ValueError(f"{field_name} must not be '.' or '..', got: {value!r}")
    if "/" in value or "\\" in value:
        raise ValueError(
            f"{field_name} must be a single path component (no '/' or '\\\\'), got: {value!r}"
        )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError(f"{field_name} must not contain control characters: {value!r}")


@dataclass(frozen=True, slots=True)
class DiscoveredImageCandidate:
    """A single file discovery considers a candidate image (by extension only).

    Nothing about its content has been read yet -- not even whether it
    decodes as an image. That is Phase 3's job.
    """

    absolute_path: Path
    relative_path: str
    split: str
    class_name: str
    extension: str

    def __post_init__(self) -> None:
        if not isinstance(self.absolute_path, Path):
            raise ValueError(
                f"absolute_path must be a Path, got {type(self.absolute_path).__name__}"
            )
        if not self.absolute_path.is_absolute():
            raise ValueError(f"absolute_path must be absolute, got: {self.absolute_path!r}")
        if not isinstance(self.relative_path, str):
            raise ValueError(
                f"relative_path must be a str, got {type(self.relative_path).__name__}"
            )
        _validate_relative_path(self.relative_path)
        _validate_split(self.split)
        validate_path_component(self.class_name, field_name="class_name")
        if not isinstance(self.extension, str) or self.extension not in CANDIDATE_EXTENSIONS:
            raise ValueError(
                f"extension must be one of {sorted(CANDIDATE_EXTENSIONS)} "
                f"(lowercase, as discovery produces), got: {self.extension!r}"
            )


@dataclass(frozen=True, slots=True)
class ClassImageCount:
    """The number of candidate images *discovered* for one (split, class)
    pair -- not necessarily the true total.

    Counting only -- v1 does not judge whether the count is balanced.

    ``is_complete`` records whether every directory in this class's subtree
    was successfully enumerated. When ``False``, ``candidate_count`` is a
    partial, best-effort count (some subdirectory could not be listed, or
    some entry could not be classified) and must not be treated as a
    confirmed total -- in particular, a count of 0 with ``is_complete=False``
    does *not* mean the class is empty, only that discovery could not fully
    examine it. There is no default: every call site must decide.
    """

    split: str
    class_name: str
    candidate_count: int
    is_complete: bool

    def __post_init__(self) -> None:
        _validate_split(self.split)
        validate_path_component(self.class_name, field_name="class_name")
        if isinstance(self.candidate_count, bool) or not isinstance(self.candidate_count, int):
            raise ValueError(
                f"candidate_count must be an int, got {type(self.candidate_count).__name__}"
            )
        if self.candidate_count < 0:
            raise ValueError("candidate_count must be non-negative")
        if not isinstance(self.is_complete, bool):
            raise ValueError(
                f"is_complete must be a bool, got {type(self.is_complete).__name__}"
            )


def _candidate_sort_key(candidate: DiscoveredImageCandidate) -> str:
    return candidate.relative_path


def _class_count_sort_key(count: ClassImageCount) -> tuple[str, str]:
    return (count.split, count.class_name)


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """The complete, canonical outcome of the discovery phase.

    Construction enforces the same discipline as
    :class:`imageset_guard.models.ScanResult`: every sequence must already
    be in its canonical sorted order, and no path or (split, class) pair
    may be duplicated.
    """

    candidates: tuple[DiscoveredImageCandidate, ...]
    findings: tuple[Finding, ...]
    scan_errors: tuple[ScanError, ...]
    class_counts: tuple[ClassImageCount, ...]

    def __post_init__(self) -> None:
        _require_sorted_unique(
            self.candidates,
            key=_candidate_sort_key,
            name="candidates",
            duplicate_of="relative_path",
        )
        _require_sorted_unique(self.findings, key=finding_sort_key, name="findings")
        _require_sorted_unique(
            self.scan_errors, key=scan_error_sort_key, name="scan_errors"
        )
        _require_sorted_unique(
            self.class_counts,
            key=_class_count_sort_key,
            name="class_counts",
            duplicate_of="(split, class_name)",
        )


def _require_sorted_unique(
    items: Sequence[_T],
    *,
    key: Callable[[_T], _K],
    name: str,
    duplicate_of: str | None = None,
) -> None:
    keys = [key(item) for item in items]
    if keys != sorted(keys):
        raise ValueError(f"{name} must already be in their canonical sorted order")
    if duplicate_of is not None and len(keys) != len(set(keys)):
        raise ValueError(f"{name} must not contain a duplicate {duplicate_of}")
