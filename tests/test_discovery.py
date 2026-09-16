"""Tests for imageset_guard.discovery: dataset structure discovery (Phase 2).

No image content is opened here -- only file names/extensions and
directory structure. No network, no real datasets: every fixture is built
under tmp_path.
"""

from __future__ import annotations

import os
import subprocess
import unicodedata
from collections.abc import Iterable
from pathlib import Path

import pytest

from imageset_guard import codes, discovery
from imageset_guard.discovery_models import DiscoveryResult
from imageset_guard.models import Severity, build_scan_result
from imageset_guard.serialization import serialize_scan_result
from imageset_guard.terminal import render_terminal


def _make_tree(root: Path, paths: Iterable[str]) -> None:
    """Create empty files at each relative path, creating parent dirs."""
    for rel in paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")


def _codes_of(items: Iterable[object]) -> list[str]:
    return [item.code for item in items]  # type: ignore[attr-defined]


def _try_symlink(link_path: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        os.symlink(target, link_path, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is not permitted in this environment: {exc}")


def _break_scandir_for(
    monkeypatch: pytest.MonkeyPatch, broken_path: Path, exc: OSError
) -> None:
    """Make os.scandir(broken_path) raise ``exc``; every other path is
    handled by the real os.scandir. A precise, real (not weakened)
    simulation of a single directory becoming unlistable mid-scan.

    Patches the ``os`` module's own ``scandir`` (the same singleton object
    ``discovery.py`` calls through its own ``import os``), rather than
    reaching into ``discovery``'s namespace for it.
    """
    real_scandir = os.scandir

    def fake_scandir(path: str | Path) -> os._ScandirIterator[str]:
        if Path(path) == broken_path:
            raise exc
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)


class _FakeUnrepresentableEntry:
    """A minimal stand-in for an os.DirEntry whose name cannot be a
    relative_path. Deliberately defines *only* ``name`` and ``path`` --
    if discovery.py ever called is_symlink()/is_dir()/is_file()/stat() on
    it before recognizing the name is unrepresentable, this raises
    AttributeError and fails the test loudly, proving the filtering really
    does happen first."""

    def __init__(self, name: str, path: str) -> None:
        self.name = name
        self.path = path


class _FakeScandirResult:
    def __init__(self, entries: list[object]) -> None:
        self._entries = entries

    def __enter__(self) -> object:
        return iter(self._entries)

    def __exit__(self, *exc_info: object) -> None:
        return None


def _inject_unrepresentable_entry(
    monkeypatch: pytest.MonkeyPatch,
    target_dir: Path,
    bad_name: str,
) -> None:
    """Make os.scandir(target_dir) return only one fake entry whose name
    is unrepresentable, regardless of what target_dir actually contains
    on disk -- so this works even on a filesystem that would refuse to
    create such a name for real (e.g. Windows)."""
    real_scandir = os.scandir
    fake_entry = _FakeUnrepresentableEntry(
        name=bad_name, path=str(target_dir / "placeholder")
    )

    def fake_scandir(path: str | Path) -> object:
        if Path(path) == target_dir:
            return _FakeScandirResult([fake_entry])
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


def test_valid_train_with_multiple_classes(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        [
            "train/cats/a.jpg",
            "train/cats/b.png",
            "train/dogs/c.webp",
        ],
    )
    result = discovery.discover(tmp_path)
    assert not result.findings
    assert not result.scan_errors
    assert {c.relative_path for c in result.candidates} == {
        "train/cats/a.jpg",
        "train/cats/b.png",
        "train/dogs/c.webp",
    }
    assert all(not c.absolute_path.is_relative_to(Path())  # sanity: is absolute-ish
               or c.absolute_path.is_absolute() for c in result.candidates)
    assert all(c.absolute_path.is_absolute() for c in result.candidates)


def test_validation_and_test_absent_is_not_an_issue(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    result = discovery.discover(tmp_path)
    assert codes.SPLIT_TRAIN_MISSING not in _codes_of(result.findings)
    assert not any(f.relative_path in ("validation", "test") for f in result.findings)


def test_optional_splits_present_and_consistent(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        [
            "train/cats/a.jpg",
            "train/dogs/b.jpg",
            "validation/cats/c.jpg",
            "validation/dogs/d.jpg",
            "test/cats/e.jpg",
            "test/dogs/f.jpg",
        ],
    )
    result = discovery.discover(tmp_path)
    assert result.findings == ()
    assert result.scan_errors == ()
    assert len(result.candidates) == 6


def test_train_missing_is_a_structural_error(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["validation/cats/a.jpg"])
    result = discovery.discover(tmp_path)
    train_missing = [f for f in result.findings if f.code == codes.SPLIT_TRAIN_MISSING]
    assert len(train_missing) == 1
    assert train_missing[0].severity is Severity.ERROR
    assert train_missing[0].relative_path is None


def test_train_as_a_file_instead_of_directory(tmp_path: Path) -> None:
    (tmp_path / "train").write_bytes(b"not a directory")
    result = discovery.discover(tmp_path)
    codes_seen = _codes_of(result.findings)
    assert codes.SPLIT_TRAIN_NOT_A_DIRECTORY in codes_seen
    assert codes.SPLIT_TRAIN_MISSING not in codes_seen
    finding = next(f for f in result.findings if f.code == codes.SPLIT_TRAIN_NOT_A_DIRECTORY)
    assert finding.severity is Severity.ERROR
    assert finding.relative_path == "train"


def test_train_with_no_class_directories(tmp_path: Path) -> None:
    (tmp_path / "train").mkdir()
    (tmp_path / "train" / "stray.jpg").write_bytes(b"")
    result = discovery.discover(tmp_path)
    codes_seen = _codes_of(result.findings)
    assert codes.SPLIT_TRAIN_HAS_NO_CLASSES in codes_seen
    finding = next(f for f in result.findings if f.code == codes.SPLIT_TRAIN_HAS_NO_CLASSES)
    assert finding.severity is Severity.ERROR


def test_empty_class_in_train_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "train" / "cats").mkdir(parents=True)
    (tmp_path / "train" / "dogs").mkdir(parents=True)
    (tmp_path / "train" / "dogs" / "a.jpg").write_bytes(b"")
    result = discovery.discover(tmp_path)
    empty = [f for f in result.findings if f.code == codes.SPLIT_EMPTY_CLASS]
    assert len(empty) == 1
    assert empty[0].severity is Severity.ERROR
    assert empty[0].relative_path == "train/cats"


def test_empty_class_in_optional_split_is_a_warning(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    (tmp_path / "validation" / "cats").mkdir(parents=True)
    result = discovery.discover(tmp_path)
    empty = [f for f in result.findings if f.code == codes.SPLIT_EMPTY_CLASS]
    assert len(empty) == 1
    assert empty[0].severity is Severity.WARNING
    assert empty[0].relative_path == "validation/cats"


def test_class_missing_from_optional_split_is_a_warning(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        ["train/cats/a.jpg", "train/dogs/b.jpg", "validation/cats/c.jpg"],
    )
    result = discovery.discover(tmp_path)
    missing = [
        f for f in result.findings if f.code == codes.SPLIT_CLASS_MISSING_FROM_OPTIONAL_SPLIT
    ]
    assert len(missing) == 1
    assert missing[0].severity is Severity.WARNING
    assert missing[0].relative_path == "validation"
    assert missing[0].evidence.get("class_name") == "dogs"


def test_class_not_in_train_is_an_error(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        ["train/cats/a.jpg", "validation/cats/b.jpg", "validation/rabbits/c.jpg"],
    )
    result = discovery.discover(tmp_path)
    extra = [f for f in result.findings if f.code == codes.SPLIT_CLASS_MISSING_FROM_TRAIN]
    assert len(extra) == 1
    assert extra[0].severity is Severity.ERROR
    assert extra[0].relative_path == "validation/rabbits"


def test_nested_directories_inside_class_stay_attributed_to_that_class(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        ["train/cats/sub1/sub2/a.jpg", "train/cats/b.jpg"],
    )
    result = discovery.discover(tmp_path)
    assert not result.findings
    assert {c.class_name for c in result.candidates} == {"cats"}
    assert {c.relative_path for c in result.candidates} == {
        "train/cats/sub1/sub2/a.jpg",
        "train/cats/b.jpg",
    }


def test_image_file_directly_in_split_is_a_warning(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg", "train/stray.png"])
    result = discovery.discover(tmp_path)
    warnings = [f for f in result.findings if f.code == codes.SPLIT_FILE_DIRECTLY_IN_SPLIT]
    assert len(warnings) == 1
    assert warnings[0].severity is Severity.WARNING
    assert warnings[0].relative_path == "train/stray.png"


def test_image_file_at_dataset_root_is_a_warning(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    (tmp_path / "root_stray.jpg").write_bytes(b"")
    result = discovery.discover(tmp_path)
    warnings = [f for f in result.findings if f.code == codes.SPLIT_IMAGE_FILE_AT_DATASET_ROOT]
    assert len(warnings) == 1
    assert warnings[0].relative_path == "root_stray.jpg"


def test_unrecognized_top_level_directory_is_a_warning(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg", "extra/whatever.txt"])
    result = discovery.discover(tmp_path)
    warnings = [
        f for f in result.findings if f.code == codes.SPLIT_UNRECOGNIZED_TOP_LEVEL_DIRECTORY
    ]
    assert len(warnings) == 1
    assert warnings[0].relative_path == "extra"


@pytest.mark.parametrize("extension", [".JPG", ".Png", ".WEBP", ".jpeg", ".JPEG"])
def test_uppercase_and_mixed_case_extensions_are_candidates(tmp_path: Path, extension: str) -> None:
    (tmp_path / "train" / "cats").mkdir(parents=True)
    (tmp_path / "train" / "cats" / f"a{extension}").write_bytes(b"")
    result = discovery.discover(tmp_path)
    assert not result.findings
    assert len(result.candidates) == 1
    assert result.candidates[0].extension == extension.lower()


def test_unsupported_extension_inside_class_is_an_integrity_warning(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg", "train/cats/notes.txt"])
    result = discovery.discover(tmp_path)
    warnings = [f for f in result.findings if f.code == codes.IMG_UNSUPPORTED_EXTENSION]
    assert len(warnings) == 1
    assert warnings[0].severity is Severity.WARNING
    assert warnings[0].relative_path == "train/cats/notes.txt"
    assert len(result.candidates) == 1


# ---------------------------------------------------------------------------
# Unicode / portability
# ---------------------------------------------------------------------------


def test_arabic_and_unicode_names_are_discovered_normally(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/قطط/صورة١.jpg"])
    result = discovery.discover(tmp_path)
    assert not result.findings
    assert result.candidates[0].relative_path == "train/قطط/صورة١.jpg"
    assert result.candidates[0].class_name == "قطط"


def test_nfc_nfd_collision_is_detected(tmp_path: Path) -> None:
    nfc_name = unicodedata.normalize("NFC", "café")  # café, composed
    nfd_name = unicodedata.normalize("NFD", "café")  # café, decomposed
    assert nfc_name != nfd_name
    (tmp_path / "train").mkdir()
    (tmp_path / "train" / nfc_name).mkdir()
    try:
        (tmp_path / "train" / nfd_name).mkdir()
    except FileExistsError:
        pytest.skip("this filesystem normalizes names, so NFC/NFD cannot coexist here")
    result = discovery.discover(tmp_path)
    collisions = [
        f for f in result.findings if f.code == codes.SPLIT_UNICODE_NORMALIZATION_COLLISION
    ]
    assert len(collisions) == 1
    assert collisions[0].relative_path == "train"


def test_case_fold_collision_is_detected(tmp_path: Path) -> None:
    (tmp_path / "train").mkdir()
    (tmp_path / "train" / "Cats").mkdir()
    try:
        (tmp_path / "train" / "cats").mkdir()
    except FileExistsError:
        pytest.skip("this filesystem is case-insensitive, so both names cannot coexist here")
    result = discovery.discover(tmp_path)
    collisions = [f for f in result.findings if f.code == codes.SPLIT_CASE_FOLD_COLLISION]
    assert len(collisions) == 1
    assert collisions[0].relative_path == "train"


@pytest.mark.parametrize("reserved", ["CON", "con", "NUL", "com1", "LPT9", "PRN.txt"])
def test_windows_reserved_name_is_flagged(tmp_path: Path, reserved: str) -> None:
    (tmp_path / "train" / "cats").mkdir(parents=True)
    target = tmp_path / "train" / "cats" / reserved
    try:
        target.write_bytes(b"")
    except OSError as exc:
        pytest.skip(f"cannot create a file named {reserved!r} on this filesystem: {exc}")
    # On Windows, writing to "CON"/"NUL"/etc. can silently succeed without
    # creating a real, listable directory entry (it opens the device
    # instead). Detect that honestly rather than asserting a false failure.
    if reserved not in {e.name for e in os.scandir(target.parent)}:
        pytest.skip(
            f"{reserved!r} opened a reserved device instead of creating a real "
            "directory entry on this filesystem; the reserved-name check has "
            "nothing to see here"
        )
    result = discovery.discover(tmp_path)
    reserved_findings = [f for f in result.findings if f.code == codes.SPLIT_WINDOWS_RESERVED_NAME]
    assert len(reserved_findings) == 1
    assert reserved_findings[0].relative_path == f"train/cats/{reserved}"


# ---------------------------------------------------------------------------
# Symlinks
# ---------------------------------------------------------------------------


def test_symlink_classification_is_skipped_and_not_descended_into(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This machine cannot create real symlinks without a privilege pytest
    # does not have here (see the _try_symlink-based tests below, which
    # skip honestly for that reason). To still exercise the real skip/warn/
    # do-not-descend handling in discovery.py, this simulates a symlink
    # classification for one specific real directory, without touching the
    # filesystem's actual symlink support at all.
    _make_tree(tmp_path, ["train/cats/a.jpg", "train/dogs/b.jpg"])
    real_classify = discovery._classify

    def fake_classify(entry: os.DirEntry[str]) -> discovery._EntryKind:
        if entry.name == "dogs":
            return "symlink"
        return real_classify(entry)

    monkeypatch.setattr(discovery, "_classify", fake_classify)
    result = discovery.discover(tmp_path)

    symlink_findings = [f for f in result.findings if f.code == codes.SPLIT_LINK_SKIPPED]
    assert len(symlink_findings) == 1
    assert symlink_findings[0].relative_path == "train/dogs"
    assert symlink_findings[0].evidence.get("link_type") == "symlink"
    # "dogs" must never be descended into as a class, despite the real file
    # train/dogs/b.jpg existing on disk underneath it.
    assert all(c.class_name != "dogs" for c in result.candidates)
    assert all(c.relative_path != "train/dogs/b.jpg" for c in result.candidates)


def test_junction_classification_is_skipped_and_not_descended_into(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Same simulation strategy as the symlink test above, but for the
    # separate "junction" classification -- proving discovery.py's walk
    # handles it identically (skip, warn, never descend) without needing a
    # real Windows junction for this specific test.
    _make_tree(tmp_path, ["train/cats/a.jpg", "train/dogs/b.jpg"])
    real_classify = discovery._classify

    def fake_classify(entry: os.DirEntry[str]) -> discovery._EntryKind:
        if entry.name == "dogs":
            return "junction"
        return real_classify(entry)

    monkeypatch.setattr(discovery, "_classify", fake_classify)
    result = discovery.discover(tmp_path)

    link_findings = [f for f in result.findings if f.code == codes.SPLIT_LINK_SKIPPED]
    assert len(link_findings) == 1
    assert link_findings[0].relative_path == "train/dogs"
    assert link_findings[0].evidence.get("link_type") == "junction"
    assert all(c.class_name != "dogs" for c in result.candidates)


def test_internal_symlink_to_directory_is_skipped_not_followed(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    _try_symlink(
        tmp_path / "train" / "dogs", tmp_path / "train" / "cats", target_is_directory=True
    )
    result = discovery.discover(tmp_path)
    symlink_findings = [f for f in result.findings if f.code == codes.SPLIT_LINK_SKIPPED]
    assert len(symlink_findings) == 1
    assert symlink_findings[0].relative_path == "train/dogs"
    assert symlink_findings[0].evidence.get("link_type") == "symlink"
    # The symlinked "dogs" must never be treated as a real class with candidates.
    assert all(c.class_name != "dogs" for c in result.candidates)


def test_external_symlink_is_skipped_not_followed(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"isg-outside-{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.jpg").write_bytes(b"")
    try:
        _make_tree(tmp_path, ["train/cats/a.jpg"])
        _try_symlink(tmp_path / "train" / "escape", outside, target_is_directory=True)
        result = discovery.discover(tmp_path)
        symlink_findings = [f for f in result.findings if f.code == codes.SPLIT_LINK_SKIPPED]
        assert len(symlink_findings) == 1
        assert not any("secret" in c.relative_path for c in result.candidates)
    finally:
        for child in outside.iterdir():
            child.unlink()
        outside.rmdir()


def test_cyclic_symlink_does_not_hang_or_crash(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    _try_symlink(tmp_path / "train" / "cats" / "loop", tmp_path, target_is_directory=True)
    result = discovery.discover(tmp_path)
    symlink_findings = [f for f in result.findings if f.code == codes.SPLIT_LINK_SKIPPED]
    assert len(symlink_findings) == 1
    assert symlink_findings[0].relative_path == "train/cats/loop"


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows-only NTFS feature")
def test_real_windows_junction_is_skipped_not_followed(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    target = tmp_path / "train" / "cats"
    link = tmp_path / "train" / "dogs"
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not link.exists():
        pytest.skip(
            f"could not create a real junction on this system "
            f"(returncode={proc.returncode}): {proc.stderr or proc.stdout}"
        )

    result = discovery.discover(tmp_path)

    link_findings = [f for f in result.findings if f.code == codes.SPLIT_LINK_SKIPPED]
    assert len(link_findings) == 1
    assert link_findings[0].relative_path == "train/dogs"
    assert link_findings[0].evidence.get("link_type") == "junction"
    # The junction must never be descended into as a class.
    assert all(c.class_name != "dogs" for c in result.candidates)


# ---------------------------------------------------------------------------
# Operational errors
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not meaningful on Windows")
def test_permission_denied_directory_becomes_a_scan_error(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg", "train/dogs/b.jpg"])
    locked = tmp_path / "train" / "dogs"
    original_mode = locked.stat().st_mode
    locked.chmod(0o000)
    try:
        result = discovery.discover(tmp_path)
    finally:
        locked.chmod(original_mode)
    assert any(e.code == codes.SYS_PERMISSION_DENIED for e in result.scan_errors)
    assert result.scan_errors[0].relative_path == "train/dogs"
    # Discovery kept going for the sibling class despite the failure.
    assert any(c.class_name == "cats" for c in result.candidates)


def test_file_vanishing_during_scan_becomes_a_scan_error_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This simulates a TOCTOU race precisely and deterministically: a real
    # concurrent deletion is not reliably reproducible in a test, so the
    # classification step discovery.py uses internally is monkeypatched to
    # raise for exactly one target, exercising the same except-branch a
    # genuine race would hit.
    _make_tree(tmp_path, ["train/cats/a.jpg", "train/cats/vanishing.jpg"])
    real_classify = discovery._classify

    def fake_classify(entry: os.DirEntry[str]) -> str:
        if entry.name == "vanishing.jpg":
            raise FileNotFoundError(f"[simulated] {entry.path} vanished")
        return real_classify(entry)

    monkeypatch.setattr(discovery, "_classify", fake_classify)
    result = discovery.discover(tmp_path)

    assert any(e.code == codes.SYS_PATH_VANISHED for e in result.scan_errors)
    assert any(e.relative_path == "train/cats/vanishing.jpg" for e in result.scan_errors)
    assert any(c.relative_path == "train/cats/a.jpg" for c in result.candidates)


# ---------------------------------------------------------------------------
# Determinism / safety
# ---------------------------------------------------------------------------


def test_discovery_is_deterministic_across_repeated_runs(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        [
            "train/zebra/a.jpg",
            "train/apple/b.jpg",
            "validation/zebra/c.jpg",
            "extra_dir/file.txt",
        ],
    )
    first = discovery.discover(tmp_path)
    second = discovery.discover(tmp_path)
    assert [c.relative_path for c in first.candidates] == [
        c.relative_path for c in second.candidates
    ]
    assert [(f.code, f.relative_path) for f in first.findings] == [
        (f.code, f.relative_path) for f in second.findings
    ]


def test_no_absolute_paths_leak_into_findings_or_scan_errors(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg", "train/stray.jpg"])
    result = discovery.discover(tmp_path)
    root_str = str(tmp_path)
    for finding in result.findings:
        assert finding.relative_path is None or root_str not in finding.relative_path
        for value in finding.evidence.values():
            assert not (isinstance(value, str) and root_str in value)
    for error in result.scan_errors:
        assert error.relative_path is None or root_str not in error.relative_path


def test_discovery_never_modifies_the_dataset(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg", "train/dogs/b.png", "train/stray.jpg"])
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    discovery.discover(tmp_path)
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_discovery_result_is_internally_consistent(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        ["train/cats/a.jpg", "train/dogs/b.jpg", "validation/cats/c.jpg"],
    )
    result = discovery.discover(tmp_path)
    # DiscoveryResult's own __post_init__ already enforces sorted/unique
    # invariants; simply constructing it successfully via discover() proves
    # discovery.py produces a canonically ordered result.
    counted = {(c.split, c.class_name) for c in result.class_counts}
    assert ("train", "cats") in counted
    assert ("train", "dogs") in counted
    assert ("validation", "cats") in counted


# ---------------------------------------------------------------------------
# Completeness: an incomplete enumeration must never produce a false
# structural claim (items 1 and 2 of the independent review).
# ---------------------------------------------------------------------------


def test_root_enumeration_failure_produces_no_structural_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_scandir_for(monkeypatch, tmp_path, PermissionError(13, "denied"))
    result = discovery.discover(tmp_path)
    assert result.findings == ()
    assert any(e.code == codes.SYS_PERMISSION_DENIED for e in result.scan_errors)


def test_train_classification_failure_does_not_claim_train_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg", "validation/cats/b.jpg"])
    real_classify = discovery._classify

    def fake_classify(entry: os.DirEntry[str]) -> discovery._EntryKind:
        if entry.name == "train":
            raise PermissionError(13, "denied")
        return real_classify(entry)

    monkeypatch.setattr(discovery, "_classify", fake_classify)
    result = discovery.discover(tmp_path)

    assert codes.SPLIT_TRAIN_MISSING not in _codes_of(result.findings)
    assert any(
        e.code == codes.SYS_PERMISSION_DENIED and e.relative_path == "train"
        for e in result.scan_errors
    )


def test_train_direct_listing_failure_does_not_claim_no_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    train_path = tmp_path / "train"
    _break_scandir_for(monkeypatch, train_path, PermissionError(13, "denied"))

    result = discovery.discover(tmp_path)

    assert codes.SPLIT_TRAIN_HAS_NO_CLASSES not in _codes_of(result.findings)
    assert any(
        e.code == codes.SYS_PERMISSION_DENIED and e.relative_path == "train"
        for e in result.scan_errors
    )


def test_split_entry_classification_failure_blocks_cross_split_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # train has classes cats and dogs; validation has cats plus one entry
    # named "mystery" whose classification fails. validation's known class
    # set is then incomplete, so discovery must not claim "dogs" is missing
    # from validation -- "mystery" could have been anything.
    _make_tree(
        tmp_path,
        ["train/cats/a.jpg", "train/dogs/b.jpg", "validation/cats/c.jpg"],
    )
    (tmp_path / "validation" / "mystery").mkdir()
    real_classify = discovery._classify

    def fake_classify(entry: os.DirEntry[str]) -> discovery._EntryKind:
        if entry.name == "mystery":
            raise PermissionError(13, "denied")
        return real_classify(entry)

    monkeypatch.setattr(discovery, "_classify", fake_classify)
    result = discovery.discover(tmp_path)

    assert codes.SPLIT_CLASS_MISSING_FROM_OPTIONAL_SPLIT not in _codes_of(result.findings)
    assert codes.SPLIT_CLASS_MISSING_FROM_TRAIN not in _codes_of(result.findings)
    assert any(
        e.code == codes.SYS_PERMISSION_DENIED and e.relative_path == "validation/mystery"
        for e in result.scan_errors
    )


def test_class_subtree_failure_prevents_empty_class_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "train" / "cats" / "sub").mkdir(parents=True)
    sub_path = tmp_path / "train" / "cats" / "sub"
    _break_scandir_for(monkeypatch, sub_path, PermissionError(13, "denied"))

    result = discovery.discover(tmp_path)

    assert codes.SPLIT_EMPTY_CLASS not in _codes_of(result.findings)
    assert any(
        e.code == codes.SYS_PERMISSION_DENIED and e.relative_path == "train/cats/sub"
        for e in result.scan_errors
    )


def test_class_subtree_failure_still_registers_class_name_for_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "cats" exists in both train and validation. train's "cats" subtree
    # partially fails, but that must not make discovery think "cats" is
    # missing from train when comparing against validation.
    _make_tree(tmp_path, ["train/cats/a.jpg", "validation/cats/b.jpg"])
    (tmp_path / "train" / "cats" / "sub").mkdir()
    sub_path = tmp_path / "train" / "cats" / "sub"
    _break_scandir_for(monkeypatch, sub_path, PermissionError(13, "denied"))

    result = discovery.discover(tmp_path)

    assert codes.SPLIT_CLASS_MISSING_FROM_TRAIN not in _codes_of(result.findings)
    assert codes.SPLIT_CLASS_MISSING_FROM_OPTIONAL_SPLIT not in _codes_of(result.findings)


def test_class_count_is_marked_incomplete_when_subtree_enumeration_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "train" / "cats" / "sub").mkdir(parents=True)
    (tmp_path / "train" / "dogs").mkdir(parents=True)
    (tmp_path / "train" / "dogs" / "a.jpg").write_bytes(b"")
    sub_path = tmp_path / "train" / "cats" / "sub"
    _break_scandir_for(monkeypatch, sub_path, PermissionError(13, "denied"))

    result = discovery.discover(tmp_path)

    cats_count = next(c for c in result.class_counts if c.class_name == "cats")
    dogs_count = next(c for c in result.class_counts if c.class_name == "dogs")
    assert cats_count.is_complete is False
    assert dogs_count.is_complete is True
    assert dogs_count.candidate_count == 1


# ---------------------------------------------------------------------------
# Optional split present but not a directory (item 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("split_name", ["validation", "test"])
def test_optional_split_as_a_file_is_a_structural_error(
    tmp_path: Path, split_name: str
) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    (tmp_path / split_name).write_bytes(b"not a directory")

    result = discovery.discover(tmp_path)

    findings = [
        f for f in result.findings if f.code == codes.SPLIT_OPTIONAL_SPLIT_NOT_A_DIRECTORY
    ]
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].relative_path == split_name


# ---------------------------------------------------------------------------
# ScanError.message must never leak raw OS exception text (item 4)
# ---------------------------------------------------------------------------


def test_scan_error_never_leaks_absolute_path_or_username_from_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    sensitive = "C:\\Users\\secretusername\\private\\a.jpg"
    real_classify = discovery._classify

    def fake_classify(entry: os.DirEntry[str]) -> discovery._EntryKind:
        if entry.name == "a.jpg":
            raise PermissionError(13, sensitive, sensitive)
        return real_classify(entry)

    monkeypatch.setattr(discovery, "_classify", fake_classify)
    result = discovery.discover(tmp_path)

    assert result.scan_errors
    for error in result.scan_errors:
        assert sensitive not in error.message
        assert "secretusername" not in error.message

    built = build_scan_result(
        findings=result.findings, scan_errors=result.scan_errors, examined_file_count=0
    )
    json_bytes = serialize_scan_result(built)
    assert sensitive.encode() not in json_bytes
    assert b"secretusername" not in json_bytes

    text = render_terminal(built)
    assert sensitive not in text
    assert "secretusername" not in text


# ---------------------------------------------------------------------------
# discover() and relative dataset_root paths (item 6)
# ---------------------------------------------------------------------------


def test_discover_accepts_a_relative_dataset_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    monkeypatch.chdir(tmp_path)

    result = discovery.discover(Path("."))

    assert result.findings == ()
    assert len(result.candidates) == 1
    assert result.candidates[0].absolute_path.is_absolute()
    assert result.candidates[0].relative_path == "train/cats/a.jpg"


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows-only NTFS feature")
def test_dataset_root_itself_may_be_a_junction_to_the_real_dataset(tmp_path: Path) -> None:
    # Policy: the caller's own chosen root is allowed to be a link; only
    # entries found *inside* the root are skipped-not-followed.
    real_dataset = tmp_path / "real_dataset"
    _make_tree(real_dataset, ["train/cats/a.jpg"])
    root_link = tmp_path / "root_link"
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root_link), str(real_dataset)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not root_link.exists():
        pytest.skip(
            f"could not create a real junction on this system "
            f"(returncode={proc.returncode}): {proc.stderr or proc.stdout}"
        )

    result = discovery.discover(root_link)

    assert result.findings == ()
    assert result.scan_errors == ()
    assert {c.relative_path for c in result.candidates} == {"train/cats/a.jpg"}
    assert codes.SPLIT_LINK_SKIPPED not in _codes_of(result.findings)


def test_discover_root_resolve_failure_becomes_scan_error_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "weird_root"
    target.mkdir()
    real_resolve = Path.resolve

    def fake_resolve(self: Path, *args: object, **kwargs: object) -> Path:
        if self == target:
            raise OSError(13, "denied")
        return real_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    result = discovery.discover(target)

    assert result.candidates == ()
    assert result.findings == ()
    assert len(result.scan_errors) == 1
    assert result.scan_errors[0].code == codes.SYS_PERMISSION_DENIED
    assert result.scan_errors[0].relative_path is None


def test_discover_root_resolve_symlink_loop_runtimeerror_becomes_scan_error_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On Python 3.11/3.12, pathlib.Path.resolve() can raise RuntimeError
    # (not OSError) for a symlink loop. discover() must convert this to a
    # ScanError exactly like an OSError, using the fixed registry message
    # -- never the exception's own text, which typically embeds an
    # absolute path.
    target = tmp_path / "looped_root"
    target.mkdir()
    real_resolve = Path.resolve
    sensitive_text = f"Symlink loop from {target / 'a' / 'b' / 'c'}"

    def fake_resolve(self: Path, *args: object, **kwargs: object) -> Path:
        if self == target:
            raise RuntimeError(sensitive_text)
        return real_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    result = discovery.discover(target)

    assert result.candidates == ()
    assert result.findings == ()
    assert len(result.scan_errors) == 1
    error = result.scan_errors[0]
    assert error.code == codes.SYS_STAT_OR_WALK_FAILURE
    assert error.relative_path is None
    assert error.message == codes.DEFAULT_MESSAGES[codes.SYS_STAT_OR_WALK_FAILURE]
    assert sensitive_text not in error.message
    assert str(target) not in error.message

    built = build_scan_result(
        findings=result.findings, scan_errors=result.scan_errors, examined_file_count=0
    )
    json_bytes = serialize_scan_result(built)
    assert sensitive_text.encode() not in json_bytes
    assert str(target).encode() not in json_bytes
    text = render_terminal(built)
    assert sensitive_text not in text
    assert str(target) not in text


# ---------------------------------------------------------------------------
# Non-regular filesystem entries inside a class (item 7)
# ---------------------------------------------------------------------------


def test_non_regular_entry_inside_class_is_flagged_and_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Creating a real socket/FIFO/device file portably and safely inside a
    # test is not practical (FIFOs do not exist on Windows at all). This
    # simulates the classification result a real one would produce.
    _make_tree(tmp_path, ["train/cats/a.jpg", "train/cats/weird_socket"])
    real_classify = discovery._classify

    def fake_classify(entry: os.DirEntry[str]) -> discovery._EntryKind:
        if entry.name == "weird_socket":
            return "other"
        return real_classify(entry)

    monkeypatch.setattr(discovery, "_classify", fake_classify)
    result = discovery.discover(tmp_path)

    findings = [f for f in result.findings if f.code == codes.IMG_NON_REGULAR_ENTRY]
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].relative_path == "train/cats/weird_socket"
    assert all(c.relative_path != "train/cats/weird_socket" for c in result.candidates)


# ---------------------------------------------------------------------------
# Hostile / unrepresentable entry names must never crash discover(), and
# must never appear anywhere in the report (models.py review follow-up).
# ---------------------------------------------------------------------------


def _assert_bad_name_never_leaks(result: DiscoveryResult, bad_name: str) -> None:
    for finding in result.findings:
        assert bad_name not in (finding.message or "")
        assert bad_name not in (finding.relative_path or "")
        assert bad_name not in (finding.remediation or "")
        for value in finding.evidence.values():
            assert not (isinstance(value, str) and bad_name in value)
    for error in result.scan_errors:
        assert bad_name not in error.message
        assert bad_name not in (error.relative_path or "")

    built = build_scan_result(
        findings=result.findings, scan_errors=result.scan_errors, examined_file_count=0
    )
    json_bytes = serialize_scan_result(built)
    assert bad_name.encode() not in json_bytes
    text = render_terminal(built)
    assert bad_name not in text


def test_unrepresentable_entry_at_root_does_not_crash_discover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    bad_name = "bad\nname.jpg"
    _inject_unrepresentable_entry(monkeypatch, tmp_path, bad_name)

    result = discovery.discover(tmp_path)

    assert any(e.code == codes.SYS_UNREPRESENTABLE_NAME for e in result.scan_errors)
    unrepresentable = next(
        e for e in result.scan_errors if e.code == codes.SYS_UNREPRESENTABLE_NAME
    )
    assert unrepresentable.relative_path is None
    assert unrepresentable.operation == "walk"
    _assert_bad_name_never_leaks(result, bad_name)


def test_unrepresentable_entry_inside_class_marks_it_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "train" / "cats").mkdir(parents=True)
    class_path = tmp_path / "train" / "cats"
    bad_name = "bad\tname.png"
    _inject_unrepresentable_entry(monkeypatch, class_path, bad_name)

    result = discovery.discover(tmp_path)

    assert codes.SPLIT_EMPTY_CLASS not in _codes_of(result.findings)
    cats_count = next(c for c in result.class_counts if c.class_name == "cats")
    assert cats_count.is_complete is False
    assert cats_count.candidate_count == 0
    unrepresentable = next(
        e for e in result.scan_errors if e.code == codes.SYS_UNREPRESENTABLE_NAME
    )
    assert unrepresentable.relative_path == "train/cats"
    assert unrepresentable.operation == "walk"
    _assert_bad_name_never_leaks(result, bad_name)


def test_unrepresentable_entry_at_split_level_blocks_cross_split_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_tree(
        tmp_path,
        ["train/cats/a.jpg", "train/dogs/b.jpg", "validation/cats/c.jpg"],
    )
    validation_path = tmp_path / "validation"
    bad_name = "weird\\name"
    _inject_unrepresentable_entry(monkeypatch, validation_path, bad_name)

    result = discovery.discover(tmp_path)

    assert codes.SPLIT_CLASS_MISSING_FROM_OPTIONAL_SPLIT not in _codes_of(result.findings)
    assert codes.SPLIT_CLASS_MISSING_FROM_TRAIN not in _codes_of(result.findings)
    _assert_bad_name_never_leaks(result, bad_name)


def test_unrepresentable_candidate_name_inside_class_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "train" / "cats").mkdir(parents=True)
    (tmp_path / "train" / "cats" / "good.jpg").write_bytes(b"")
    class_path = tmp_path / "train" / "cats"
    bad_name = "bad\nphoto.jpg"
    real_scandir = os.scandir

    def fake_scandir(path: str | Path) -> object:
        if Path(path) == class_path:
            with real_scandir(path) as it:
                real_entries = list(it)
            fake_entry = _FakeUnrepresentableEntry(bad_name, str(class_path / "x"))
            return _FakeScandirResult([*real_entries, fake_entry])
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)

    result = discovery.discover(tmp_path)

    assert {c.relative_path for c in result.candidates} == {"train/cats/good.jpg"}
    cats_count = next(c for c in result.class_counts if c.class_name == "cats")
    assert cats_count.is_complete is False
    assert cats_count.candidate_count == 1
    _assert_bad_name_never_leaks(result, bad_name)


@pytest.mark.skipif(os.name == "nt", reason="these byte sequences are not valid Windows filenames")
def test_real_posix_control_character_filename_does_not_crash_discover(tmp_path: Path) -> None:
    (tmp_path / "train" / "cats").mkdir(parents=True)
    bad_name = "bad\nname.jpg"
    (tmp_path / "train" / "cats" / bad_name).write_bytes(b"")

    result = discovery.discover(tmp_path)

    assert any(e.code == codes.SYS_UNREPRESENTABLE_NAME for e in result.scan_errors)
    cats_count = next(c for c in result.class_counts if c.class_name == "cats")
    assert cats_count.is_complete is False
    _assert_bad_name_never_leaks(result, bad_name)


@pytest.mark.skipif(os.name == "nt", reason="backslash is a path separator on Windows")
def test_real_posix_backslash_filename_does_not_crash_discover(tmp_path: Path) -> None:
    (tmp_path / "train" / "cats").mkdir(parents=True)
    bad_name = "bad\\name.jpg"
    (tmp_path / "train" / "cats" / bad_name).write_bytes(b"")

    result = discovery.discover(tmp_path)

    assert any(e.code == codes.SYS_UNREPRESENTABLE_NAME for e in result.scan_errors)
    _assert_bad_name_never_leaks(result, bad_name)


@pytest.mark.skipif(os.name == "nt", reason="':' is not a valid Windows filename character")
def test_real_posix_drive_lookalike_name_at_root_does_not_crash_discover(tmp_path: Path) -> None:
    _make_tree(tmp_path, ["train/cats/a.jpg"])
    bad_name = "C:photo.jpg"
    (tmp_path / bad_name).write_bytes(b"")

    result = discovery.discover(tmp_path)

    assert any(e.code == codes.SYS_UNREPRESENTABLE_NAME for e in result.scan_errors)
    unrepresentable = next(
        e for e in result.scan_errors if e.code == codes.SYS_UNREPRESENTABLE_NAME
    )
    assert unrepresentable.relative_path is None
    _assert_bad_name_never_leaks(result, bad_name)
