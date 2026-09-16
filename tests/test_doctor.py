"""Tests for imageset_guard.doctor: environment diagnostics only.

These never read or list any user dataset.
"""

from __future__ import annotations

from pathlib import Path

from imageset_guard import __version__
from imageset_guard.doctor import run_doctor_checks


def test_all_checks_pass_in_this_environment() -> None:
    checks = run_doctor_checks()
    assert all(check.ok for check in checks)


def test_reports_the_installed_package_version() -> None:
    checks = run_doctor_checks()
    version_check = next(c for c in checks if c.name == "imageset_guard_version")
    assert version_check.detail == __version__
    assert version_check.ok is True


def test_reports_pillow_version_string() -> None:
    checks = run_doctor_checks()
    pillow_check = next(c for c in checks if c.name == "pillow_importable")
    assert pillow_check.ok is True
    assert pillow_check.detail  # some non-empty version string


def test_temp_dir_writable_check_uses_given_directory(tmp_path: Path) -> None:
    checks = run_doctor_checks(temp_dir=tmp_path)
    temp_check = next(c for c in checks if c.name == "temp_dir_writable")
    assert temp_check.ok is True
    assert str(tmp_path) in temp_check.detail


def test_temp_dir_writable_check_fails_for_nonexistent_directory(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    checks = run_doctor_checks(temp_dir=missing)
    temp_check = next(c for c in checks if c.name == "temp_dir_writable")
    assert temp_check.ok is False


def test_checks_never_touch_any_dataset_directory(tmp_path: Path) -> None:
    # A "dataset" full of files that would be expensive or wrong to read.
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "secret.jpg").write_bytes(b"private content")
    before = (dataset / "secret.jpg").read_bytes()
    run_doctor_checks()
    after = (dataset / "secret.jpg").read_bytes()
    assert before == after
