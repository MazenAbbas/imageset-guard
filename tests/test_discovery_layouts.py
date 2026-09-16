"""Tests for imageset_guard.discovery's explicit ``layout`` parameter.

Per the v0.2 design: ``layout="class-only"`` treats the dataset root as
one implicit ``train`` split, reusing the exact same per-class-subtree
walk, portability checks, and candidate classification as split-class --
only the root-level dispatch differs. There is no automatic detection:
the caller always chooses explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from imageset_guard import codes, discovery


def _touch_image(path: Path) -> None:
    # Not a real decodable image; discovery only classifies by extension.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff\xdb" + b"0" * 16)


def test_class_only_layout_treats_root_classes_as_train(tmp_path: Path) -> None:
    _touch_image(tmp_path / "cats" / "a.jpg")
    _touch_image(tmp_path / "dogs" / "b.jpg")

    result = discovery.discover(tmp_path, layout="class-only")

    assert result.scan_errors == ()
    relative_paths = {c.relative_path for c in result.candidates}
    assert relative_paths == {"train/cats/a.jpg", "train/dogs/b.jpg"}
    assert all(c.split == "train" for c in result.candidates)
    class_names = {(c.split, c.class_name) for c in result.class_counts}
    assert class_names == {("train", "cats"), ("train", "dogs")}


def test_class_only_layout_reports_empty_class_dir(tmp_path: Path) -> None:
    (tmp_path / "empty_class").mkdir()
    _touch_image(tmp_path / "cats" / "a.jpg")

    result = discovery.discover(tmp_path, layout="class-only")

    assert any(f.code == codes.SPLIT_EMPTY_CLASS for f in result.findings)
    empty_finding = next(f for f in result.findings if f.code == codes.SPLIT_EMPTY_CLASS)
    assert empty_finding.relative_path == "train/empty_class"
    assert empty_finding.severity.value == "error"  # class-only's implicit split is "train"


def test_class_only_layout_with_no_classes_at_all_is_an_error(tmp_path: Path) -> None:
    result = discovery.discover(tmp_path, layout="class-only")
    assert [f.code for f in result.findings] == [codes.SPLIT_TRAIN_HAS_NO_CLASSES]


def test_class_only_layout_flags_stray_file_directly_at_root(tmp_path: Path) -> None:
    _touch_image(tmp_path / "cats" / "a.jpg")
    _touch_image(tmp_path / "stray.jpg")

    result = discovery.discover(tmp_path, layout="class-only")

    stray = next(f for f in result.findings if f.relative_path == "train/stray.jpg")
    assert stray.code == codes.SPLIT_FILE_DIRECTLY_IN_SPLIT


def test_class_only_layout_never_emits_cross_split_findings(tmp_path: Path) -> None:
    _touch_image(tmp_path / "cats" / "a.jpg")
    result = discovery.discover(tmp_path, layout="class-only")
    cross_split_codes = (
        codes.SPLIT_CLASS_MISSING_FROM_TRAIN,
        codes.SPLIT_CLASS_MISSING_FROM_OPTIONAL_SPLIT,
    )
    assert all(f.code not in cross_split_codes for f in result.findings)


def test_class_only_layout_still_protects_against_incomplete_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    _touch_image(tmp_path / "cats" / "a.jpg")
    unreadable = tmp_path / "dogs"
    unreadable.mkdir()
    _touch_image(unreadable / "b.jpg")

    real_scandir = os.scandir

    def failing_scandir(path: str | Path) -> os._ScandirIterator[str]:
        if Path(path) == unreadable:
            raise PermissionError(13, "denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", failing_scandir)
    result = discovery.discover(tmp_path, layout="class-only")

    assert any(e.code == codes.SYS_PERMISSION_DENIED for e in result.scan_errors)
    dogs_count = next(c for c in result.class_counts if c.class_name == "dogs")
    assert dogs_count.is_complete is False


def test_default_layout_is_still_split_class(tmp_path: Path) -> None:
    _touch_image(tmp_path / "train" / "cats" / "a.jpg")
    result_default = discovery.discover(tmp_path)
    result_explicit = discovery.discover(tmp_path, layout="split-class")
    assert result_default.candidates == result_explicit.candidates


def test_split_class_layout_rejects_class_only_style_dataset(tmp_path: Path) -> None:
    # A class-only dataset scanned with the default split-class layout must
    # never silently reinterpret it -- it should report the missing 'train'
    # split explicitly rather than guessing.
    _touch_image(tmp_path / "cats" / "a.jpg")
    result = discovery.discover(tmp_path, layout="split-class")
    assert codes.SPLIT_TRAIN_MISSING in {f.code for f in result.findings}
    assert result.candidates == ()
