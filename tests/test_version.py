"""Guards against the package version and pyproject.toml version drifting apart."""

from __future__ import annotations

import tomllib
from pathlib import Path

from imageset_guard import __version__


def test_package_version_matches_pyproject() -> None:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    assert __version__ == data["project"]["version"]
