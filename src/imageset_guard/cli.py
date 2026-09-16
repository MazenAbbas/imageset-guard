"""The command-line entry point for complete local dataset scans."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from imageset_guard import __version__
from imageset_guard.doctor import run_doctor_checks
from imageset_guard.example_dataset import generate_example_dataset
from imageset_guard.exitcodes import (
    EXIT_INCOMPLETE,
    EXIT_INTERNAL_ERROR,
    EXIT_INTERRUPTED,
    EXIT_INVALID_USAGE,
    EXIT_OK,
    exit_code_for_status,
)
from imageset_guard.paths import PathValidationError, validate_dataset_root, validate_output_path
from imageset_guard.policy import PolicyError, load_policy
from imageset_guard.scanner import scan_dataset
from imageset_guard.serialization import ReportWriteError, write_report
from imageset_guard.terminal import render_terminal

PROG = "imageset-guard"

_PROGRESS_INTERVAL = 500


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan an image dataset.",
        description=(
            "Scan a local image-classification dataset and report structure, "
            "integrity, privacy, and duplicate-leakage findings."
        ),
        epilog=(
            f"Examples:\n"
            f"  {PROG} scan ./data\n"
            f"  {PROG} scan ./data --config policy.toml --output report.json\n"
            f"  {PROG} scan ./data --layout class-only --quiet\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scan_parser.add_argument("dataset_root", help="Path to the dataset root directory.")
    scan_parser.add_argument(
        "--config", help="Path to a TOML policy file.", default=None
    )
    scan_parser.add_argument(
        "--output", help="Path to write a JSON report to (must end in .json).", default=None
    )
    scan_parser.add_argument(
        "--layout",
        choices=("split-class", "class-only"),
        default="split-class",
        help=(
            "Dataset layout: 'split-class' expects train/validation/test "
            "directories (the default); 'class-only' expects class "
            "directories directly under the dataset root, with no split "
            "concept, reported as a single implicit 'train' split."
        ),
    )
    scan_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable terminal summary. Never hides a fatal error.",
    )
    scan_parser.add_argument(
        "--progress",
        action="store_true",
        help=(
            "Write periodic progress lines to stderr while inspecting files. "
            "Never mixed into stdout or the JSON report."
        ),
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check the installation and environment (never reads a dataset).",
    )
    doctor_parser.add_argument(
        "--quiet", action="store_true", help="Suppress per-check detail; print only the verdict."
    )

    example_parser = subparsers.add_parser(
        "example",
        help="Generate a tiny local example dataset to try the tool on.",
        description=(
            "Write a small, deterministic, locally-generated example dataset "
            "(no downloaded or copyrighted images) so you can try 'scan' immediately."
        ),
    )
    example_parser.add_argument("output_dir", help="Directory to create (must not already exist).")
    example_parser.add_argument(
        "--seed", type=int, default=0, help="Deterministic seed for the generated images."
    )

    policy_check_parser = subparsers.add_parser(
        "policy-check", help="Validate a TOML policy file without scanning any dataset."
    )
    policy_check_parser.add_argument("policy_file", help="Path to the TOML policy file.")

    return parser


def _run_scan(args: argparse.Namespace) -> int:
    try:
        resolved_root = validate_dataset_root(Path(args.dataset_root))
    except PathValidationError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return EXIT_INVALID_USAGE

    config_path = Path(args.config) if args.config is not None else None
    try:
        policy = load_policy(config_path)
    except PolicyError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return EXIT_INVALID_USAGE

    output_path: Path | None = None
    if args.output is not None:
        try:
            output_path = validate_output_path(Path(args.output), resolved_root)
        except PathValidationError as exc:
            print(f"{PROG}: {exc}", file=sys.stderr)
            return EXIT_INVALID_USAGE

    progress_callback = _make_progress_reporter() if args.progress else None

    result, profile = scan_dataset(
        resolved_root, policy, layout=args.layout, progress_callback=progress_callback
    )

    if output_path is not None:
        try:
            write_report(result, profile, output_path)
        except ReportWriteError:
            print(f"{PROG}: report could not be written.", file=sys.stderr)
            return EXIT_INCOMPLETE

    if not args.quiet:
        print(render_terminal(result, profile), end="")
    return exit_code_for_status(result.status)


def _make_progress_reporter() -> Callable[[int, int], None]:
    last_reported = 0

    def report(done: int, total: int) -> None:
        nonlocal last_reported
        if done == total or done - last_reported >= _PROGRESS_INTERVAL:
            print(f"{PROG}: inspected {done}/{total} files", file=sys.stderr, flush=True)
            last_reported = done

    return report


def _run_doctor(args: argparse.Namespace) -> int:
    checks = run_doctor_checks()
    all_ok = all(check.ok for check in checks)
    if not args.quiet:
        for check in checks:
            status = "OK" if check.ok else "FAIL"
            print(f"[{status}] {check.name}: {check.detail}")
    print(f"{PROG}: environment is {'OK' if all_ok else 'NOT OK'}.")
    return EXIT_OK if all_ok else EXIT_INCOMPLETE


def _run_example(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    try:
        count = generate_example_dataset(output_dir, seed=args.seed)
    except FileExistsError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return EXIT_INVALID_USAGE
    print(f"{PROG}: wrote {count} example images to {output_dir}")
    print(f"Try: {PROG} scan {output_dir}")
    return EXIT_OK


def _run_policy_check(args: argparse.Namespace) -> int:
    try:
        load_policy(Path(args.policy_file))
    except PolicyError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return EXIT_INVALID_USAGE
    print(f"{PROG}: policy file is valid.")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its exit code. Never raises ``SystemExit``."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return EXIT_INVALID_USAGE

    try:
        if args.command == "scan":
            return _run_scan(args)
        if args.command == "doctor":
            return _run_doctor(args)
        if args.command == "example":
            return _run_example(args)
        if args.command == "policy-check":
            return _run_policy_check(args)
        parser.error(f"unknown command: {args.command}")
        return EXIT_INVALID_USAGE  # pragma: no cover - parser.error raises SystemExit
    except KeyboardInterrupt:
        print(f"\n{PROG}: interrupted; no report was published as complete.", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception:
        print(f"{PROG}: unexpected internal error.", file=sys.stderr)
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
