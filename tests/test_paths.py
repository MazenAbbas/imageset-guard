"""Tests for imageset_guard.paths: dataset-root and output-path validation.

Per the approved specification:
- dataset root must exist, be a directory, and be readable.
- output, if given, must end in ``.json``.
- output must not equal the dataset root, nor be located inside it, compared
  after a safe ``resolve()``.
- validation must never create the output path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from imageset_guard.paths import (
    PathValidationError,
    validate_dataset_root,
    validate_output_path,
)


def test_dataset_root_resolve_failure_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "C:/Users/private-person/dataset"
    real_resolve = Path.resolve

    def fail_for_root(path: Path, *args: object, **kwargs: object) -> Path:
        if path == tmp_path:
            raise RuntimeError(secret)
        return real_resolve(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", fail_for_root)
    with pytest.raises(PathValidationError) as captured:
        validate_dataset_root(tmp_path)
    assert secret not in str(captured.value)


def test_output_resolve_failure_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path.parent / "report.json"
    secret = "C:/Users/private-person/report.json"
    real_resolve = Path.resolve

    def fail_for_output(path: Path, *args: object, **kwargs: object) -> Path:
        if path == output:
            raise OSError(secret)
        return real_resolve(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", fail_for_output)
    with pytest.raises(PathValidationError) as captured:
        validate_output_path(output, tmp_path.resolve())
    assert secret not in str(captured.value)


def test_validate_dataset_root_accepts_existing_directory(tmp_path: Path) -> None:
    result = validate_dataset_root(tmp_path)
    assert result == tmp_path.resolve()


def test_validate_dataset_root_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(PathValidationError, match="does not exist"):
        validate_dataset_root(tmp_path / "missing")


def test_validate_dataset_root_rejects_file(tmp_path: Path) -> None:
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(PathValidationError, match="not a directory"):
        validate_dataset_root(file_path)


def test_validate_output_path_accepts_json_sibling(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    output = tmp_path / "report.json"
    result = validate_output_path(output, dataset_root.resolve())
    assert result == output.resolve()
    assert not output.exists()  # validation must not create it


def test_validate_output_path_rejects_non_json_suffix(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    with pytest.raises(PathValidationError, match=r"\.json"):
        validate_output_path(tmp_path / "report.txt", dataset_root.resolve())


def test_validate_output_path_rejects_uppercase_suffix(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    with pytest.raises(PathValidationError, match=r"\.json"):
        validate_output_path(tmp_path / "report.JSON", dataset_root.resolve())


def test_validate_output_path_rejects_equal_to_dataset_root(tmp_path: Path) -> None:
    # Give the root itself a .json-suffixed name so the equality branch is
    # reached rather than being short-circuited by the suffix check.
    dataset_root = tmp_path / "dataset.json"
    dataset_root.mkdir()
    with pytest.raises(PathValidationError, match="equal"):
        validate_output_path(dataset_root, dataset_root.resolve())


def test_validate_output_path_rejects_path_inside_dataset_root(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    output = dataset_root / "report.json"
    with pytest.raises(PathValidationError, match="inside"):
        validate_output_path(output, dataset_root.resolve())


def test_validate_output_path_rejects_nested_path_inside_dataset_root(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "dataset"
    (dataset_root / "sub" / "dir").mkdir(parents=True)
    output = dataset_root / "sub" / "dir" / "report.json"
    with pytest.raises(PathValidationError, match="inside"):
        validate_output_path(output, dataset_root.resolve())


def test_validate_output_path_allows_sibling_directory(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    output = reports_dir / "report.json"
    result = validate_output_path(output, dataset_root.resolve())
    assert result == output.resolve()
