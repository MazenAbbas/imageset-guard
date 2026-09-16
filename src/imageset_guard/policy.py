"""Strict TOML policy loading.

v1 policy is deliberately tiny: it is TOML only (no YAML), has exactly one
configurable setting (``max_pixels``), and rejects any unrecognized key or
table outright rather than silently ignoring it -- there is no plugin or
scripting surface to grow into.

Supported image formats and the required/optional split names are fixed
project constants for v1, not configurable.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_MAX_PIXELS: Final = 50_000_000

SUPPORTED_FORMATS: Final[frozenset[str]] = frozenset({"JPEG", "PNG", "WEBP"})
REQUIRED_SPLIT: Final = "train"
OPTIONAL_SPLITS: Final[frozenset[str]] = frozenset({"validation", "test"})

_KNOWN_KEYS: Final[frozenset[str]] = frozenset({"max_pixels"})


class PolicyError(Exception):
    """Raised for any invalid policy configuration. Maps to exit code 2."""


def _validate_max_pixels(value: object) -> int:
    if isinstance(value, bool):
        raise PolicyError(
            f"max_pixels must be a positive integer, not a bool: {value!r}"
        )
    if not isinstance(value, int):
        raise PolicyError(
            f"max_pixels must be a positive integer, got {type(value).__name__}: {value!r}"
        )
    if value <= 0:
        raise PolicyError(f"max_pixels must be a positive integer, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class Policy:
    """The v1 policy: currently just the pixel-count safety limit."""

    max_pixels: int = DEFAULT_MAX_PIXELS

    def __post_init__(self) -> None:
        if isinstance(self.max_pixels, bool):
            raise ValueError(
                f"max_pixels must be a positive int, not a bool: {self.max_pixels!r}"
            )
        if not isinstance(self.max_pixels, int):
            raise ValueError(
                f"max_pixels must be a positive int, got {type(self.max_pixels).__name__}"
            )
        if self.max_pixels <= 0:
            raise ValueError(f"max_pixels must be a positive int, got {self.max_pixels!r}")


def load_policy(path: Path | None) -> Policy:
    """Load :class:`Policy` from ``path``, or return the default if ``None``.

    Raises :class:`PolicyError` for a missing file, malformed TOML, an
    unknown key or table, or an invalid ``max_pixels`` value.
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
            f"Recognized keys in v1: {', '.join(sorted(_KNOWN_KEYS))}."
        )

    max_pixels = _validate_max_pixels(data.get("max_pixels", DEFAULT_MAX_PIXELS))
    return Policy(max_pixels=max_pixels)
