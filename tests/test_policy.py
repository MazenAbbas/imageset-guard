"""Tests for the strict TOML policy loader in imageset_guard.policy.

Per the approved specification: no YAML, no plugins/scripting, a single
configurable setting (``max_pixels``, default 50_000_000) that must be a
positive integer and can never be null/zero/negative/disabled, and fixed
(non-configurable) v1 constants for supported formats and required splits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from imageset_guard.policy import (
    DEFAULT_MAX_PIXELS,
    OPTIONAL_SPLITS,
    REQUIRED_SPLIT,
    SUPPORTED_FORMATS,
    Policy,
    PolicyError,
    load_policy,
)


def test_default_policy_has_project_default_max_pixels() -> None:
    assert load_policy(None).max_pixels == DEFAULT_MAX_PIXELS == 50_000_000


def test_fixed_v1_constants_are_not_configurable() -> None:
    assert frozenset({"JPEG", "PNG", "WEBP"}) == SUPPORTED_FORMATS
    assert REQUIRED_SPLIT == "train"
    assert frozenset({"validation", "test"}) == OPTIONAL_SPLITS


def test_loads_valid_max_pixels_from_toml(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("max_pixels = 80_000_000\n", encoding="utf-8")
    policy = load_policy(config)
    assert policy.max_pixels == 80_000_000


def test_missing_config_file_is_a_policy_error(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="not found"):
        load_policy(tmp_path / "does-not-exist.toml")


def test_malformed_toml_is_a_policy_error(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("max_pixels = [unterminated\n", encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(config)


@pytest.mark.parametrize(
    "raw",
    [
        "max_pixels = 0\n",
        "max_pixels = -1\n",
        "max_pixels = true\n",
        "max_pixels = false\n",
        'max_pixels = "50000000"\n',
        "max_pixels = 50.0\n",
    ],
)
def test_rejects_invalid_max_pixels_values(tmp_path: Path, raw: str) -> None:
    config = tmp_path / "policy.toml"
    config.write_text(raw, encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(config)


def test_max_pixels_cannot_be_set_to_toml_null_like_syntax(tmp_path: Path) -> None:
    # TOML has no null literal at all; a bare unquoted value is a parse error,
    # which load_policy must surface as a PolicyError, not a crash.
    config = tmp_path / "policy.toml"
    config.write_text("max_pixels = null\n", encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(config)


def test_rejects_unknown_key(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("max_pixels = 60_000_000\ntotally_unknown_key = 1\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="totally_unknown_key"):
        load_policy(config)


def test_rejects_unknown_table(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("[plugins]\nrun = \"anything\"\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="plugins"):
        load_policy(config)


def test_policy_is_frozen() -> None:
    policy = Policy()
    with pytest.raises(AttributeError):
        policy.max_pixels = 1  # type: ignore[misc]


def test_policy_direct_construction_validates_too() -> None:
    with pytest.raises(ValueError, match="positive"):
        Policy(max_pixels=0)
    with pytest.raises(ValueError, match="bool"):
        Policy(max_pixels=True)


# ---------------------------------------------------------------------------
# v0.2: schema_version and backward compatibility
# ---------------------------------------------------------------------------


def test_absent_schema_version_defaults_to_current() -> None:
    policy = load_policy(None)
    assert policy.max_pixels == DEFAULT_MAX_PIXELS
    # None of the new v0.2 fields constrain anything unless configured:
    assert policy.min_images_per_class is None
    assert policy.max_class_imbalance_ratio is None
    assert policy.allowed_formats is None
    assert policy.allowed_modes is None
    assert policy.min_width is None
    assert policy.exif_policy == "allow"
    assert policy.gps_policy == "allow"


def test_explicit_matching_schema_version_is_accepted(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("schema_version = 1\nmax_pixels = 1_000_000\n", encoding="utf-8")
    assert load_policy(config).max_pixels == 1_000_000


@pytest.mark.parametrize("bad_version", [0, 2, 99, "1"])
def test_unsupported_schema_version_fails_clearly(tmp_path: Path, bad_version: object) -> None:
    config = tmp_path / "policy.toml"
    config.write_text(f"schema_version = {bad_version!r}\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="schema_version"):
        load_policy(config)


def test_v1_only_policy_file_still_loads_with_v02_binary(tmp_path: Path) -> None:
    # A policy file written for v0.1 (just max_pixels, no schema_version at
    # all) must still load correctly and produce v0.1-identical behavior.
    config = tmp_path / "policy.toml"
    config.write_text("max_pixels = 42_000_000\n", encoding="utf-8")
    policy = load_policy(config)
    assert policy == Policy(max_pixels=42_000_000)


# ---------------------------------------------------------------------------
# v0.2: new optional fields
# ---------------------------------------------------------------------------


def test_loads_all_new_fields_from_toml(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text(
        """
        min_images_per_class = 10
        max_class_imbalance_ratio = 3.5
        allowed_formats = ["JPEG", "PNG"]
        allowed_modes = ["RGB", "L"]
        min_width = 32
        max_width = 4096
        min_height = 32
        max_height = 4096
        min_aspect_ratio = 0.5
        max_aspect_ratio = 2.0
        exif_policy = "forbid"
        gps_policy = "forbid"
        """,
        encoding="utf-8",
    )
    policy = load_policy(config)
    assert policy.min_images_per_class == 10
    assert policy.max_class_imbalance_ratio == 3.5
    assert policy.allowed_formats == frozenset({"JPEG", "PNG"})
    assert policy.allowed_modes == frozenset({"RGB", "L"})
    assert policy.min_width == 32
    assert policy.max_width == 4096
    assert policy.min_height == 32
    assert policy.max_height == 4096
    assert policy.min_aspect_ratio == 0.5
    assert policy.max_aspect_ratio == 2.0
    assert policy.exif_policy == "forbid"
    assert policy.gps_policy == "forbid"


@pytest.mark.parametrize(
    "raw",
    [
        "min_images_per_class = 0\n",
        "min_images_per_class = -1\n",
        "min_images_per_class = true\n",
        'min_images_per_class = "5"\n',
        "min_images_per_class = 1.5\n",
    ],
)
def test_rejects_invalid_min_images_per_class(tmp_path: Path, raw: str) -> None:
    config = tmp_path / "policy.toml"
    config.write_text(raw, encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(config)


def test_allowed_formats_must_be_non_empty_array(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("allowed_formats = []\n", encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(config)


def test_allowed_formats_rejects_unsupported_format_name(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text('allowed_formats = ["GIF"]\n', encoding="utf-8")
    with pytest.raises(PolicyError, match="supported"):
        load_policy(config)


def test_allowed_formats_rejects_non_string_entries(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("allowed_formats = [1, 2]\n", encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(config)


def test_min_width_exceeding_max_width_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("min_width = 100\nmax_width = 50\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="min_width"):
        load_policy(config)


def test_min_aspect_ratio_exceeding_max_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("min_aspect_ratio = 2.0\nmax_aspect_ratio = 1.0\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="aspect_ratio"):
        load_policy(config)


@pytest.mark.parametrize("field_name", ["exif_policy", "gps_policy"])
def test_metadata_policy_rejects_invalid_value(tmp_path: Path, field_name: str) -> None:
    config = tmp_path / "policy.toml"
    config.write_text(f'{field_name} = "sometimes"\n', encoding="utf-8")
    with pytest.raises(PolicyError, match=field_name):
        load_policy(config)


def test_direct_policy_construction_validates_new_fields_too() -> None:
    with pytest.raises(ValueError, match="min_images_per_class"):
        Policy(min_images_per_class=0)
    with pytest.raises(ValueError, match="width"):
        Policy(min_width=100, max_width=50)
    with pytest.raises(ValueError, match="empty"):
        Policy(allowed_formats=frozenset())
    with pytest.raises(ValueError, match="exif_policy"):
        Policy(exif_policy="sometimes")  # type: ignore[arg-type]
