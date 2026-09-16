"""Strict TOML policy loading.

Policy is TOML only (no YAML), rejects any unrecognized key or table
outright rather than silently ignoring it, and never coerces an invalid
type -- there is no plugin or scripting surface to grow into.

``POLICY_SCHEMA_VERSION`` is the only schema version v0.2 understands. An
explicit ``schema_version`` key mismatching it fails clearly (exit code 2)
rather than silently reinterpreting an unknown future format. Every field
beyond ``max_pixels`` is new in v0.2 and optional: a policy file with only
``max_pixels`` (or no file at all) behaves exactly as it did in v0.1 --
none of these new checks run unless the user explicitly configures them.

Supported image formats and the required/optional split names are fixed
project constants, not configurable.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

DEFAULT_MAX_PIXELS: Final = 50_000_000

SUPPORTED_FORMATS: Final[frozenset[str]] = frozenset({"JPEG", "PNG", "WEBP"})
REQUIRED_SPLIT: Final = "train"
OPTIONAL_SPLITS: Final[frozenset[str]] = frozenset({"validation", "test"})

POLICY_SCHEMA_VERSION: Final = 1

_METADATA_POLICY_VALUES: Final[frozenset[str]] = frozenset({"allow", "forbid"})

_KNOWN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "max_pixels",
        "min_images_per_class",
        "max_class_imbalance_ratio",
        "allowed_formats",
        "allowed_modes",
        "min_width",
        "max_width",
        "min_height",
        "max_height",
        "min_aspect_ratio",
        "max_aspect_ratio",
        "exif_policy",
        "gps_policy",
    }
)


class PolicyError(Exception):
    """Raised for any invalid policy configuration. Maps to exit code 2."""


def _require_positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyError(
            f"{field_name} must be a positive integer, got {type(value).__name__}: {value!r}"
        )
    if value <= 0:
        raise PolicyError(f"{field_name} must be a positive integer, got {value!r}")
    return value


def _require_positive_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PolicyError(
            f"{field_name} must be a positive number, got {type(value).__name__}: {value!r}"
        )
    result = float(value)
    if result <= 0:
        raise PolicyError(f"{field_name} must be a positive number, got {value!r}")
    return result


def _require_string_set(value: object, *, field_name: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise PolicyError(
            f"{field_name} must be a non-empty array of strings, got: {value!r}"
        )
    for item in value:
        if not isinstance(item, str) or not item:
            raise PolicyError(f"{field_name} entries must be non-empty strings, got: {item!r}")
    return frozenset(value)


def _require_metadata_policy(value: object, *, field_name: str) -> Literal["allow", "forbid"]:
    if not isinstance(value, str) or value not in _METADATA_POLICY_VALUES:
        raise PolicyError(
            f"{field_name} must be one of {sorted(_METADATA_POLICY_VALUES)}, got: {value!r}"
        )
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Policy:
    """The complete v0.2 policy.

    Every field beyond ``max_pixels`` defaults to "no additional
    constraint": absent from the TOML file, it behaves exactly as v0.1
    did. Each new check is opt-in and produces a distinct
    ``Category.POLICY`` finding code -- it never changes the meaning or
    severity of an existing SPLIT/IMG/PRIV/DUP finding.
    """

    max_pixels: int = DEFAULT_MAX_PIXELS
    min_images_per_class: int | None = None
    max_class_imbalance_ratio: float | None = None
    allowed_formats: frozenset[str] | None = None
    allowed_modes: frozenset[str] | None = None
    min_width: int | None = None
    max_width: int | None = None
    min_height: int | None = None
    max_height: int | None = None
    min_aspect_ratio: float | None = None
    max_aspect_ratio: float | None = None
    exif_policy: Literal["allow", "forbid"] = "allow"
    gps_policy: Literal["allow", "forbid"] = "allow"

    def __post_init__(self) -> None:
        if isinstance(self.max_pixels, bool) or not isinstance(self.max_pixels, int):
            raise ValueError(
                f"max_pixels must be a positive int, got {type(self.max_pixels).__name__}"
            )
        if self.max_pixels <= 0:
            raise ValueError(f"max_pixels must be a positive int, got {self.max_pixels!r}")

        _check_optional_positive(self.min_images_per_class, field_name="min_images_per_class")
        _check_optional_positive(
            self.max_class_imbalance_ratio, field_name="max_class_imbalance_ratio"
        )
        _check_optional_positive(self.min_width, field_name="min_width")
        _check_optional_positive(self.max_width, field_name="max_width")
        _check_optional_positive(self.min_height, field_name="min_height")
        _check_optional_positive(self.max_height, field_name="max_height")
        _check_optional_positive(self.min_aspect_ratio, field_name="min_aspect_ratio")
        _check_optional_positive(self.max_aspect_ratio, field_name="max_aspect_ratio")
        _check_bounds_pair(self.min_width, self.max_width, field_name="width")
        _check_bounds_pair(self.min_height, self.max_height, field_name="height")
        _check_bounds_pair(self.min_aspect_ratio, self.max_aspect_ratio, field_name="aspect_ratio")

        if self.allowed_formats is not None and not self.allowed_formats:
            raise ValueError("allowed_formats must not be an empty set")
        if self.allowed_modes is not None and not self.allowed_modes:
            raise ValueError("allowed_modes must not be an empty set")
        if self.exif_policy not in _METADATA_POLICY_VALUES:
            raise ValueError(f"exif_policy must be one of {sorted(_METADATA_POLICY_VALUES)}")
        if self.gps_policy not in _METADATA_POLICY_VALUES:
            raise ValueError(f"gps_policy must be one of {sorted(_METADATA_POLICY_VALUES)}")


def _check_optional_positive(value: int | float | None, *, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a positive number, got {value!r}")
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive number, got {value!r}")


def _check_bounds_pair(
    lo: int | float | None, hi: int | float | None, *, field_name: str
) -> None:
    if lo is not None and hi is not None and lo > hi:
        raise ValueError(
            f"min_{field_name} ({lo!r}) must not exceed max_{field_name} ({hi!r})"
        )


def load_policy(path: Path | None) -> Policy:
    """Load :class:`Policy` from ``path``, or return the default if ``None``.

    Raises :class:`PolicyError` for a missing file, malformed TOML, an
    unknown key or table, an unsupported ``schema_version``, or any
    invalid field value. All validation happens before a dataset is ever
    scanned.
    """
    if path is None:
        return Policy()

    if not path.is_file():
        raise PolicyError(f"policy file not found: {path}")

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise PolicyError(f"policy file is not valid TOML: {exc}") from exc
    except OSError as exc:
        raise PolicyError(f"policy file could not be read: {exc}") from exc

    unknown_keys = set(data) - _KNOWN_KEYS
    if unknown_keys:
        raise PolicyError(
            f"unknown policy key(s): {', '.join(sorted(unknown_keys))}. "
            f"Recognized keys: {', '.join(sorted(_KNOWN_KEYS))}."
        )

    schema_version = data.get("schema_version", POLICY_SCHEMA_VERSION)
    if schema_version != POLICY_SCHEMA_VERSION:
        raise PolicyError(
            f"unsupported policy schema_version {schema_version!r}; "
            f"this build only understands schema_version {POLICY_SCHEMA_VERSION}"
        )

    max_pixels = _require_positive_int(
        data.get("max_pixels", DEFAULT_MAX_PIXELS), field_name="max_pixels"
    )

    min_images_per_class = (
        _require_positive_int(data["min_images_per_class"], field_name="min_images_per_class")
        if "min_images_per_class" in data
        else None
    )
    max_class_imbalance_ratio = (
        _require_positive_float(
            data["max_class_imbalance_ratio"], field_name="max_class_imbalance_ratio"
        )
        if "max_class_imbalance_ratio" in data
        else None
    )
    allowed_formats = (
        _require_string_set(data["allowed_formats"], field_name="allowed_formats")
        if "allowed_formats" in data
        else None
    )
    if allowed_formats is not None and not allowed_formats <= SUPPORTED_FORMATS:
        raise PolicyError(
            f"allowed_formats may only name supported formats {sorted(SUPPORTED_FORMATS)}, "
            f"got: {sorted(allowed_formats)}"
        )
    allowed_modes = (
        _require_string_set(data["allowed_modes"], field_name="allowed_modes")
        if "allowed_modes" in data
        else None
    )

    min_width = (
        _require_positive_int(data["min_width"], field_name="min_width")
        if "min_width" in data
        else None
    )
    max_width = (
        _require_positive_int(data["max_width"], field_name="max_width")
        if "max_width" in data
        else None
    )
    min_height = (
        _require_positive_int(data["min_height"], field_name="min_height")
        if "min_height" in data
        else None
    )
    max_height = (
        _require_positive_int(data["max_height"], field_name="max_height")
        if "max_height" in data
        else None
    )
    min_aspect_ratio = (
        _require_positive_float(data["min_aspect_ratio"], field_name="min_aspect_ratio")
        if "min_aspect_ratio" in data
        else None
    )
    max_aspect_ratio = (
        _require_positive_float(data["max_aspect_ratio"], field_name="max_aspect_ratio")
        if "max_aspect_ratio" in data
        else None
    )
    exif_policy = (
        _require_metadata_policy(data["exif_policy"], field_name="exif_policy")
        if "exif_policy" in data
        else "allow"
    )
    gps_policy = (
        _require_metadata_policy(data["gps_policy"], field_name="gps_policy")
        if "gps_policy" in data
        else "allow"
    )

    try:
        return Policy(
            max_pixels=max_pixels,
            min_images_per_class=min_images_per_class,
            max_class_imbalance_ratio=max_class_imbalance_ratio,
            allowed_formats=allowed_formats,
            allowed_modes=allowed_modes,
            min_width=min_width,
            max_width=max_width,
            min_height=min_height,
            max_height=max_height,
            min_aspect_ratio=min_aspect_ratio,
            max_aspect_ratio=max_aspect_ratio,
            exif_policy=exif_policy,
            gps_policy=gps_policy,
        )
    except ValueError as exc:
        raise PolicyError(str(exc)) from exc
