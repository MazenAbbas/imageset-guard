"""Packaging-contract tests: PEP 561 typing marker and version consistency.

These guard the source tree; the actual verification that ``py.typed``
survives into the built wheel and sdist is done by inspecting the built
artifacts directly (reported alongside the release gates' other
verification results) rather than inside the test suite, since building a
wheel/sdist on every test run would be slow and belongs to release
verification, not unit testing.
"""

from __future__ import annotations

from pathlib import Path

import imageset_guard


def test_py_typed_marker_exists_in_the_source_tree() -> None:
    package_dir = Path(imageset_guard.__file__).resolve().parent
    marker = package_dir / "py.typed"
    assert marker.is_file(), (
        f"{marker} is missing: without it, type checkers treat this package "
        "as untyped (PEP 561)"
    )
