"""The command-line entry point for complete local dataset scans."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from imageset_guard import __version__
from imageset_guard.exitcodes import (
    EXIT_INCOMPLETE,
    EXIT_INTERNAL_ERROR,
    EXIT_INVALID_USAGE,
    exit_code_for_status,
)
from imageset_guard.paths import PathValidationError, validate_dataset_root, validate_output_path
from imageset_guard.policy import PolicyError, load_policy
from imageset_guard.scanner import scan_dataset
from imageset_guard.serialization import ReportWriteError, write_scan_result
from imageset_guard.terminal import render_terminal

PROG = "imageset-guard"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan an image dataset.")
    scan_parser.add_argument("dataset_root", help="Path to the dataset root directory.")
    scan_parser.add_argument(
        "--config", help="Path to a TOML policy file.", default=None
    )
    scan_parser.add_argument(
        "--output", help="Path to write a JSON report to (must end in .json).", default=None
    )

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

    result = scan_dataset(resolved_root, policy)
    if output_path is not None:
        try:
            write_scan_result(result, output_path)
        except ReportWriteError:
            print(f"{PROG}: report could not be written.", file=sys.stderr)
            return EXIT_INCOMPLETE

    print(render_terminal(result), end="")
    return exit_code_for_status(result.status)


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
        parser.error(f"unknown command: {args.command}")
        return EXIT_INVALID_USAGE  # pragma: no cover - parser.error raises SystemExit
    except Exception:
        print(f"{PROG}: unexpected internal error.", file=sys.stderr)
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
