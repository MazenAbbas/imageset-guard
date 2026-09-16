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
    config.write_text("max_pixels = 60_000_000\nallowed_formats = [\"GIF\"]\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="allowed_formats"):
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
