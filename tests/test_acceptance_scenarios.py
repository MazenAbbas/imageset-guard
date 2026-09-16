"""Locally reproducible acceptance scenarios for the five workflows in
docs/guides.md: student, data scientist, ML engineer, data engineer/CI,
instructor. Each drives the real CLI (imageset_guard.cli.main) exactly as
a user would, and verifies command, exit code, expected finding codes,
human-readable guidance, JSON validity, and that no source file changed.

These are executable stand-ins for real user workflows, not a substitute
for external user testing -- see docs/user-testing-protocol.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from imageset_guard import codes
from imageset_guard.cli import main
from imageset_guard.exitcodes import EXIT_INVALID_USAGE, EXIT_OK, EXIT_POLICY_VIOLATION


def _save(path: Path, color: str = "red", *, size: tuple[int, int] = (32, 32)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG")


def _manifest(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_scenario_student_scans_a_simple_class_based_dataset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "assignment"
    _save(dataset / "cats" / "a.jpg")
    _save(dataset / "dogs" / "b.jpg", "blue")
    before = _manifest(dataset)

    code = main(["scan", str(dataset), "--layout", "class-only"])
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert "Result: PASS" in out
    assert "Profile:" in out
    assert _manifest(dataset) == before


def test_scenario_data_scientist_gets_a_profile_and_sees_imbalance(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "data"
    _save(dataset / "train" / "cats" / "a.jpg")
    for i in range(5):
        # Distinct sizes so the five images are not byte-identical --
        # this scenario is about class-count imbalance, not duplicates.
        _save(dataset / "train" / "dogs" / f"{i}.jpg", "blue", size=(32 + i, 32))
    output = tmp_path / "report.json"

    code = main(["scan", str(dataset), "--output", str(output), "--quiet"])
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert code == EXIT_OK  # no policy configured: imbalance is a fact, not a violation
    assert payload["profile"]["file_count_by_class"] == {"cats": 1, "dogs": 5}
    assert payload["profile"]["class_balance_ratio"] == 5.0
    assert payload["findings"] == []


def test_scenario_ml_engineer_detects_train_test_leakage(tmp_path: Path) -> None:
    dataset = tmp_path / "data"
    train_image = dataset / "train" / "cats" / "a.jpg"
    _save(train_image)
    test_image = dataset / "test" / "cats" / "a_copy.jpg"
    test_image.parent.mkdir(parents=True)
    test_image.write_bytes(train_image.read_bytes())
    output = tmp_path / "report.json"

    code = main(["scan", str(dataset), "--output", str(output), "--quiet"])
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert code == EXIT_POLICY_VIOLATION
    assert [f["code"] for f in payload["findings"]] == [codes.DUP_ACROSS_SPLITS]
    finding = payload["findings"][0]
    leaked_pair = {finding["relative_path"], finding["evidence"]["matches"]}
    assert leaked_pair == {"train/cats/a.jpg", "test/cats/a_copy.jpg"}
    digest = hashlib.sha256(train_image.read_bytes()).hexdigest()
    assert digest not in json.dumps(payload)
    assert str(dataset) not in json.dumps(payload)


def test_scenario_data_engineer_enforces_a_toml_policy_in_ci(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "data"
    _save(dataset / "train" / "cats" / "a.jpg")
    policy_file = tmp_path / "policy.toml"
    policy_file.write_text("min_images_per_class = 5\n", encoding="utf-8")

    check_code = main(["policy-check", str(policy_file)])
    assert check_code == EXIT_OK
    capsys.readouterr()  # discard policy-check's own stdout before the scan below

    output = tmp_path / "report.json"
    scan_code = main(
        ["scan", str(dataset), "--config", str(policy_file), "--output", str(output), "--quiet"]
    )
    captured = capsys.readouterr()
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert scan_code == EXIT_POLICY_VIOLATION
    assert captured.out == ""  # --quiet: CI logs stay short
    assert [f["code"] for f in payload["findings"]] == [codes.POLICY_CLASS_TOO_SMALL]


def test_scenario_instructor_applies_one_policy_to_multiple_submissions(
    tmp_path: Path,
) -> None:
    policy_file = tmp_path / "policy.toml"
    policy_file.write_text("min_images_per_class = 2\n", encoding="utf-8")
    assert main(["policy-check", str(policy_file)]) == EXIT_OK

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    results: dict[str, int] = {}
    for name, count in (("alice", 1), ("bob", 3)):
        submission = tmp_path / "submissions" / name
        for i in range(count):
            _save(submission / "train" / "cats" / f"{i}.jpg")
        output = reports_dir / f"{name}.json"
        results[name] = main(
            ["scan", str(submission), "--config", str(policy_file), "--output", str(output)]
        )
        json.loads(output.read_text(encoding="utf-8"))  # must always be valid JSON

    assert results["alice"] == EXIT_POLICY_VIOLATION  # 1 < min_images_per_class=2
    assert results["bob"] == EXIT_OK  # 3 >= 2


def test_invalid_policy_fails_before_any_scan_ever_touches_the_dataset(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "data"
    _save(dataset / "train" / "cats" / "a.jpg")
    before = _manifest(dataset)
    policy_file = tmp_path / "policy.toml"
    policy_file.write_text("min_images_per_class = -1\n", encoding="utf-8")

    code = main(["scan", str(dataset), "--config", str(policy_file)])

    assert code == EXIT_INVALID_USAGE
    assert _manifest(dataset) == before
