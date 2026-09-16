"""Pure, filesystem-independent tests for discovery.py's classification
predicates.

These prove the underlying logic directly with plain strings/ints/fake
objects, so it is proven correct even on a machine where the real
filesystem cannot create a Windows-reserved name, a colliding pair of
names, or a real symlink/junction (this machine, notably: see
test_discovery.py's honest skips for exactly those limits).
"""

from __future__ import annotations

import stat as stat_module
from types import SimpleNamespace
from typing import Any

import pytest

from imageset_guard import discovery

# ---------------------------------------------------------------------------
# Representable relative paths -- pure, no filesystem needed. Proves the
# safety check discovery.py runs on every entry name before it can ever
# reach a Finding/ScanError/DiscoveredImageCandidate constructor.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        "train/cats/a.jpg",
        "train/قطط/a.jpg",  # Arabic class name
        "train/cats/photo:v2.jpg",  # colon not in drive position: fine
    ],
)
def test_representable_paths_pass(candidate: str) -> None:
    assert discovery.is_representable_relative_path(candidate) is True


@pytest.mark.parametrize(
    "candidate",
    [
        "train/cats/bad\nname.jpg",
        "train/cats/bad\tname.png",
        "train/cats\\nested/a.jpg",
        "C:photo.jpg",
        "train/\x01weird/a.jpg",
    ],
)
def test_unrepresentable_paths_are_rejected(candidate: str) -> None:
    assert discovery.is_representable_relative_path(candidate) is False

# ---------------------------------------------------------------------------
# Windows reserved names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "CON",
        "con",
        "Con",
        "NUL",
        "nul",
        "PRN",
        "AUX",
        "COM1",
        "com9",
        "LPT1",
        "lpt9",
        "CON.txt",
        "con.tar.gz",
        "PRN.TXT",
        "CON.",  # trailing dot stripped by Windows before comparison
        "CON ",  # trailing space stripped by Windows before comparison
        "CON. . ",  # multiple trailing dots/spaces
        "NUL.",
    ],
)
def test_reserved_names_are_detected(name: str) -> None:
    assert discovery.is_windows_reserved_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "cats",
        "MYCON",
        "CONSOLE",
        "COM10",  # only COM1-9 are reserved, not COM10
        "LPT10",
        "COM0",  # only COM1-9, not COM0
        "photo.jpg",
        "",
        "   ",  # strips to empty, not reserved
        "....",  # strips to empty, not reserved
    ],
)
def test_non_reserved_names_pass(name: str) -> None:
    assert discovery.is_windows_reserved_name(name) is False


# ---------------------------------------------------------------------------
# Case-fold collisions
# ---------------------------------------------------------------------------


def test_case_fold_collision_pure() -> None:
    collisions = discovery.find_case_fold_collisions(["cats", "Cats", "dogs"])
    assert collisions == [("Cats", "cats")]


def test_case_fold_no_collision_pure() -> None:
    assert discovery.find_case_fold_collisions(["cats", "dogs", "birds"]) == []


def test_case_fold_collision_among_three_names_pure() -> None:
    collisions = discovery.find_case_fold_collisions(["Foo", "foo", "FOO"])
    # First-seen ("Foo") is compared against each later colliding name.
    assert collisions == [("Foo", "foo"), ("FOO", "Foo")]


def test_case_fold_collision_is_empty_for_empty_input() -> None:
    assert discovery.find_case_fold_collisions([]) == []


# ---------------------------------------------------------------------------
# NFC/NFD collisions
# ---------------------------------------------------------------------------


def test_nfc_collision_pure() -> None:
    nfc = "café"  # é, composed
    nfd = "café"  # é, decomposed
    assert nfc != nfd
    collisions = discovery.find_nfc_collisions([nfc, nfd])
    assert collisions == [tuple(sorted((nfc, nfd)))]


def test_nfc_no_collision_for_unrelated_unicode_names() -> None:
    assert discovery.find_nfc_collisions(["قطط", "dogs"]) == []


def test_nfc_collision_is_empty_for_empty_input() -> None:
    assert discovery.find_nfc_collisions([]) == []


# ---------------------------------------------------------------------------
# Junction / reparse-point classification
#
# os.DirEntry cannot be constructed directly from Python, so these use
# minimal duck-typed fakes to exercise both code paths (Python 3.12+'s
# native is_junction(), and the manual reparse-tag fallback used on 3.11)
# without needing a real Windows junction.
# ---------------------------------------------------------------------------


class _FakeEntryWithIsJunction:
    """Simulates Python 3.12+, where DirEntry.is_junction() exists."""

    def __init__(self, value: bool) -> None:
        self._value = value

    def is_junction(self) -> bool:
        return self._value

    def stat(self, *, follow_symlinks: bool) -> Any:
        raise AssertionError("is_junction() present; stat() fallback must not be used")


class _FakeEntryWithoutIsJunction:
    """Simulates Python 3.11, where DirEntry has no is_junction() at all."""

    def __init__(self, reparse_tag: int) -> None:
        self._reparse_tag = reparse_tag

    def stat(self, *, follow_symlinks: bool) -> Any:
        assert follow_symlinks is False
        return SimpleNamespace(st_reparse_tag=self._reparse_tag)


def test_is_junction_uses_native_method_when_available_true() -> None:
    entry = _FakeEntryWithIsJunction(True)
    assert discovery._is_junction(entry) is True  # type: ignore[arg-type]


def test_is_junction_uses_native_method_when_available_false() -> None:
    entry = _FakeEntryWithIsJunction(False)
    assert discovery._is_junction(entry) is False  # type: ignore[arg-type]


def test_is_junction_falls_back_to_reparse_tag_when_method_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the Windows-only constant to exist with a known value regardless
    # of the platform actually running this test -- on real Windows it
    # already exists (and happens to equal this value), but on Linux/macOS
    # it is absent, and discovery._is_mount_point_reparse_tag() correctly
    # treats "absent" as "never a mount point" (see its docstring). Without
    # this patch, this "pure" test silently depended on running on Windows.
    mount_point_tag = 0xA0000003
    monkeypatch.setattr(
        stat_module, "IO_REPARSE_TAG_MOUNT_POINT", mount_point_tag, raising=False
    )
    entry = _FakeEntryWithoutIsJunction(reparse_tag=mount_point_tag)
    assert discovery._is_junction(entry) is True  # type: ignore[arg-type]


def test_is_junction_fallback_rejects_non_mount_point_reparse_tags() -> None:
    symlink_tag = 0xA000000C  # IO_REPARSE_TAG_SYMLINK, a different reparse type
    entry = _FakeEntryWithoutIsJunction(reparse_tag=symlink_tag)
    assert discovery._is_junction(entry) is False  # type: ignore[arg-type]


def test_is_junction_fallback_rejects_zero_reparse_tag() -> None:
    entry = _FakeEntryWithoutIsJunction(reparse_tag=0)
    assert discovery._is_junction(entry) is False  # type: ignore[arg-type]


def test_is_mount_point_reparse_tag_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same reasoning as test_is_junction_falls_back_to_reparse_tag_when_method_absent:
    # force the constant to exist so this test does not silently depend on
    # running on real Windows.
    mount_point_tag = 0xA0000003
    monkeypatch.setattr(
        stat_module, "IO_REPARSE_TAG_MOUNT_POINT", mount_point_tag, raising=False
    )
    assert discovery._is_mount_point_reparse_tag(mount_point_tag) is True
    assert discovery._is_mount_point_reparse_tag(0) is False
    assert discovery._is_mount_point_reparse_tag(0xA000000C) is False


def test_candidate_extensions_defined_in_exactly_one_place() -> None:
    from imageset_guard.discovery_models import CANDIDATE_EXTENSIONS

    assert discovery.CANDIDATE_EXTENSIONS is CANDIDATE_EXTENSIONS
    assert frozenset({".jpg", ".jpeg", ".png", ".webp"}) == discovery.CANDIDATE_EXTENSIONS
