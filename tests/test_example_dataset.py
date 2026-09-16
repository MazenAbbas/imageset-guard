"""Tests for imageset_guard.example_dataset: the local synthetic example."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from imageset_guard.example_dataset import generate_example_dataset
from imageset_guard.scanner import scan_dataset


def test_generates_a_split_class_layout_that_passes_a_scan(tmp_path: Path) -> None:
    target = tmp_path / "example"
    count = generate_example_dataset(target)
    assert count > 0

    result, profile = scan_dataset(target)
    assert result.status.value == "pass"
    assert profile.accepted_count == count


def test_refuses_to_overwrite_an_existing_directory(tmp_path: Path) -> None:
    target = tmp_path / "example"
    target.mkdir()
    (target / "keep.txt").write_text("do not delete me", encoding="utf-8")
    with pytest.raises(FileExistsError):
        generate_example_dataset(target)
    assert (target / "keep.txt").read_text(encoding="utf-8") == "do not delete me"


def test_is_deterministic_for_a_given_seed(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_example_dataset(first, seed=42)
    generate_example_dataset(second, seed=42)

    first_files = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    second_files = sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file())
    assert first_files == second_files
    for rel in first_files:
        first_bytes = (first / rel).read_bytes()
        second_bytes = (second / rel).read_bytes()
        assert first_bytes == second_bytes


def test_different_seeds_produce_different_pixel_content(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    generate_example_dataset(a, seed=1)
    generate_example_dataset(b, seed=2)
    file_a = next(p for p in a.rglob("*.png"))
    file_b = next(p for p in b.rglob("*.png"))
    digest_a = hashlib.sha256(file_a.read_bytes()).digest()
    digest_b = hashlib.sha256(file_b.read_bytes()).digest()
    assert digest_a != digest_b
