"""End-to-end tests for the public command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from imageset_guard import __version__, cli
from imageset_guard.cli import main
from imageset_guard.exitcodes import (
    EXIT_INCOMPLETE,
    EXIT_INTERNAL_ERROR,
    EXIT_INTERRUPTED,
    EXIT_INVALID_USAGE,
    EXIT_OK,
    EXIT_POLICY_VIOLATION,
)
from imageset_guard.models import ScanError, build_scan_result
from imageset_guard.profile_models import DatasetProfile


def _empty_profile() -> DatasetProfile:
    return DatasetProfile(
        candidate_count=0,
        examined_count=0,
        accepted_count=0,
        rejected_count=0,
        file_count_by_split={},
        file_count_by_class={},
        format_counts={},
        mode_counts={},
        width_min=None,
        width_max=None,
        height_min=None,
        height_max=None,
        aspect_ratio_min=None,
        aspect_ratio_max=None,
        empty_classes=(),
        class_balance_ratio=None,
        complete=True,
    )


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
    monkeypatch.setattr(
        cli, "scan_dataset", lambda _root, _policy, **_kw: (incomplete, _empty_profile())
    )
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

    def fail(_root: Path, _policy: object, **_kw: object) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "scan_dataset", fail)
    code = main(["scan", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == EXIT_INTERNAL_ERROR
    assert "unexpected internal error" in captured.err
    assert secret not in captured.err


# ---------------------------------------------------------------------------
# v0.2: --quiet, --layout, profile in output
# ---------------------------------------------------------------------------


def test_quiet_suppresses_terminal_summary_but_keeps_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _valid_dataset(tmp_path)
    code = main(["scan", str(tmp_path), "--quiet"])
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert captured.out == ""


def test_quiet_never_hides_a_fatal_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["scan", str(tmp_path / "missing"), "--quiet"])
    captured = capsys.readouterr()
    assert code == EXIT_INVALID_USAGE
    assert "does not exist" in captured.err


def test_scan_output_includes_profile_section_in_terminal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _valid_dataset(tmp_path)
    main(["scan", str(tmp_path)])
    out = capsys.readouterr().out
    assert "Profile:" in out
    assert "Classes: 1" in out


def test_scan_json_report_includes_schema_version_and_profile(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    _valid_dataset(dataset_root)
    output = tmp_path / "report.json"
    main(["scan", str(dataset_root), "--output", str(output)])
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report_schema_version"] == 1
    assert payload["profile"]["accepted_count"] == 1


def test_layout_class_only_scans_a_dataset_with_no_split_directories(tmp_path: Path) -> None:
    image = tmp_path / "cats" / "a.jpg"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (5, 5), "red").save(image)
    code = main(["scan", str(tmp_path), "--layout", "class-only"])
    assert code == EXIT_OK


def test_default_layout_rejects_class_only_dataset_explicitly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image = tmp_path / "cats" / "a.jpg"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (5, 5), "red").save(image)
    code = main(["scan", str(tmp_path)])
    assert code == EXIT_POLICY_VIOLATION
    assert "'train' split is missing" in capsys.readouterr().out


def test_invalid_layout_value_is_rejected_by_argparse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["scan", str(tmp_path), "--layout", "bogus"])
    assert code == EXIT_INVALID_USAGE


# ---------------------------------------------------------------------------
# v0.2: policy fields flowing through the CLI end-to-end
# ---------------------------------------------------------------------------


def test_min_images_per_class_policy_flags_small_class_via_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image = tmp_path / "train" / "cats" / "a.jpg"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (5, 5), "red").save(image)
    config = tmp_path.parent / "policy.toml"
    config.write_text("min_images_per_class = 5\n", encoding="utf-8")
    code = main(["scan", str(tmp_path), "--config", str(config)])
    assert code == EXIT_POLICY_VIOLATION
    assert "POLICY003" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# v0.2: doctor, example, policy-check commands
# ---------------------------------------------------------------------------


def test_doctor_command_reports_ok_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["doctor"])
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "environment is OK" in captured.out


def test_doctor_quiet_suppresses_per_check_lines(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["doctor", "--quiet"])
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "[OK]" not in captured.out
    assert "environment is OK" in captured.out


def test_example_command_generates_a_scannable_dataset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "example"
    code = main(["example", str(target)])
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "wrote" in captured.out
    assert main(["scan", str(target), "--quiet"]) == EXIT_OK


def test_example_command_refuses_to_overwrite_existing_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "example"
    target.mkdir()
    code = main(["example", str(target)])
    assert code == EXIT_INVALID_USAGE
    assert "already exists" in capsys.readouterr().err


def test_policy_check_accepts_a_valid_policy_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("max_pixels = 1000\n", encoding="utf-8")
    code = main(["policy-check", str(config)])
    assert code == EXIT_OK
    assert "valid" in capsys.readouterr().out


def test_policy_check_rejects_an_invalid_policy_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "policy.toml"
    config.write_text("max_pixels = -1\n", encoding="utf-8")
    code = main(["policy-check", str(config)])
    assert code == EXIT_INVALID_USAGE
    assert "max_pixels" in capsys.readouterr().err


def test_policy_check_command_has_no_dataset_root_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No dataset_root argument exists at all for this command: calling it
    # with none (just the missing policy_file) is a plain usage error,
    # exactly like any other missing-required-argument case -- main()
    # never lets argparse's SystemExit escape (see its docstring).
    code = main(["policy-check"])
    assert code == EXIT_INVALID_USAGE
    assert "policy_file" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# v0.2: Ctrl+C handling
# ---------------------------------------------------------------------------


def test_keyboard_interrupt_returns_documented_code_and_sanitized_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _valid_dataset(tmp_path)

    def interrupted(_root: Path, _policy: object, **_kw: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "scan_dataset", interrupted)
    code = main(["scan", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == EXIT_INTERRUPTED
    assert "interrupted" in captured.err


def test_keyboard_interrupt_during_write_leaves_no_partial_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_root = tmp_path / "dataset"
    _valid_dataset(dataset_root)
    output = tmp_path / "report.json"

    def interrupted(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "write_report", interrupted)
    code = main(["scan", str(dataset_root), "--output", str(output)])
    assert code == EXIT_INTERRUPTED
    assert not output.exists()


# ---------------------------------------------------------------------------
# v0.2: --progress writes to stderr only, never contaminating stdout/JSON
# ---------------------------------------------------------------------------


def test_progress_writes_only_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset_root = tmp_path / "dataset"
    _valid_dataset(dataset_root)
    output = tmp_path / "report.json"
    code = main(["scan", str(dataset_root), "--output", str(output), "--progress"])
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "inspected" in captured.err
    # stdout is the human-readable terminal summary; the JSON report is a
    # separate file. Neither may contain a progress line.
    assert "inspected" not in captured.out
    report_text = output.read_text(encoding="utf-8")
    assert "inspected" not in report_text
    json.loads(report_text)  # still valid JSON
