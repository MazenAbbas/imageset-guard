"""End-to-end tests for the public command-line interface."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from imageset_guard import __version__, cli
from imageset_guard.cli import main
from imageset_guard.exitcodes import (
    EXIT_INCOMPLETE,
    EXIT_INTERNAL_ERROR,
    EXIT_INVALID_USAGE,
    EXIT_OK,
    EXIT_POLICY_VIOLATION,
)
from imageset_guard.models import ScanError, build_scan_result


def _valid_dataset(root: Path) -> Path:
    image = root / "train" / "cats" / "a.jpg"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (5, 5), "red").save(image)
    return image


def test_version_flag_prints_version_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--version"])
    assert code == 0
    assert __version__ in capsys.readouterr().out


def test_help_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--help"])
    assert code == 0
    assert "scan" in capsys.readouterr().out


def test_no_arguments_is_invalid_usage(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])
    assert code == EXIT_INVALID_USAGE


def test_scan_rejects_missing_dataset_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["scan", str(tmp_path / "missing")])
    assert code == EXIT_INVALID_USAGE
    assert "does not exist" in capsys.readouterr().err


def test_scan_passes_valid_dataset_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _valid_dataset(tmp_path)
    code = main(["scan", str(tmp_path)])
    assert code == EXIT_OK
    assert "Result: PASS" in capsys.readouterr().out


def test_scan_rejects_output_with_wrong_suffix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    code = main(["scan", str(dataset_root), "--output", str(tmp_path / "report.txt")])
    assert code == EXIT_INVALID_USAGE
    assert ".json" in capsys.readouterr().err


def test_scan_rejects_output_inside_dataset_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    code = main(
        ["scan", str(dataset_root), "--output", str(dataset_root / "report.json")]
    )
    assert code == EXIT_INVALID_USAGE
    assert "inside" in capsys.readouterr().err


def test_scan_with_valid_output_writes_canonical_report(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "dataset"
    _valid_dataset(dataset_root)
    output = tmp_path / "report.json"
    code = main(["scan", str(dataset_root), "--output", str(output)])
    assert code == EXIT_OK
    assert '"status": "pass"' in output.read_text(encoding="utf-8")


def test_scan_rejects_invalid_policy_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    config = tmp_path / "policy.toml"
    config.write_text("max_pixels = -1\n", encoding="utf-8")
    code = main(["scan", str(dataset_root), "--config", str(config)])
    assert code == EXIT_INVALID_USAGE
    assert "max_pixels" in capsys.readouterr().err


def test_scan_with_valid_policy_config_runs_engine(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    _valid_dataset(dataset_root)
    config = tmp_path / "policy.toml"
    config.write_text("max_pixels = 60_000_000\n", encoding="utf-8")
    code = main(["scan", str(dataset_root), "--config", str(config)])
    assert code == EXIT_OK


def test_scan_never_modifies_dataset_root(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    _valid_dataset(dataset_root)
    before = {p: p.read_bytes() for p in dataset_root.rglob("*") if p.is_file()}

    main(["scan", str(dataset_root)])

    after = {p: p.read_bytes() for p in dataset_root.rglob("*") if p.is_file()}
    assert before == after


def test_scan_returns_policy_violation_for_bad_image(tmp_path: Path) -> None:
    image = tmp_path / "train" / "cats" / "bad.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"not an image")
    assert main(["scan", str(tmp_path)]) == EXIT_POLICY_VIOLATION


def test_warning_result_returns_zero(tmp_path: Path) -> None:
    image = tmp_path / "train" / "cats" / "a.jpg"
    image.parent.mkdir(parents=True)
    exif = Image.Exif()
    exif[305] = "camera software"
    Image.new("RGB", (5, 5)).save(image, exif=exif)
    assert main(["scan", str(tmp_path)]) == EXIT_OK


def test_incomplete_result_returns_three(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _valid_dataset(tmp_path)
    incomplete = build_scan_result(
        findings=(),
        scan_errors=(
            ScanError(
                code="SYS001",
                message="Permission denied while accessing this path.",
                operation="open",
                relative_path="train/cats/a.jpg",
            ),
        ),
        examined_file_count=0,
    )
    monkeypatch.setattr(cli, "scan_dataset", lambda _root, _policy: incomplete)
    assert main(["scan", str(tmp_path)]) == EXIT_INCOMPLETE
    assert "Result: INCOMPLETE" in capsys.readouterr().out


def test_failed_scan_still_writes_report(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    image = dataset / "train" / "cats" / "bad.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"not an image")
    output = tmp_path / "report.json"
    code = main(["scan", str(dataset), "--output", str(output)])
    assert code == EXIT_POLICY_VIOLATION
    assert '"status": "fail"' in output.read_text(encoding="utf-8")


def test_report_write_failure_is_sanitized(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _valid_dataset(tmp_path)
    output = tmp_path.parent / "missing-parent" / "report.json"
    code = main(["scan", str(tmp_path), "--output", str(output)])
    captured = capsys.readouterr()
    assert code == EXIT_INCOMPLETE
    assert "report could not be written" in captured.err
    assert str(output) not in captured.err


def test_unexpected_internal_error_is_sanitized(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _valid_dataset(tmp_path)
    secret = "C:/Users/private-person/secret.jpg"

    def fail(_root: Path, _policy: object) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "scan_dataset", fail)
    code = main(["scan", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == EXIT_INTERNAL_ERROR
    assert "unexpected internal error" in captured.err
    assert secret not in captured.err
