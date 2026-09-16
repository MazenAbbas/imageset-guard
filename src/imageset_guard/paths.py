"""Path-safety validation for the dataset root and the output report path.

Both checks run before anything is scanned or written. Neither creates
anything on disk -- ``Path.resolve()`` normalizes a path (following
symlinks in its existing components) without requiring the path to exist,
which lets the output path be validated before it is ever created.
"""

from __future__ import annotations

import os
from pathlib import Path


class PathValidationError(Exception):
    """Raised for any invalid dataset-root or output path. Maps to exit code 2."""


def validate_dataset_root(path: Path) -> Path:
    """Validate that ``path`` exists, is a directory, and is readable.

    Returns the resolved (canonical) path.
    """
    try:
        if not path.exists():
            raise PathValidationError(f"dataset root does not exist: {path}")
        if not path.is_dir():
            raise PathValidationError(f"dataset root is not a directory: {path}")
        resolved = path.resolve()
        if not os.access(resolved, os.R_OK):
            raise PathValidationError(f"dataset root is not readable: {path}")
    except (OSError, RuntimeError) as exc:
        raise PathValidationError("dataset root could not be resolved safely") from exc
    return resolved


def validate_output_path(output: Path, resolved_dataset_root: Path) -> Path:
    """Validate the ``--output`` path against an already-resolved dataset root.

    ``output`` must end in ``.json`` and must not equal, or be located
    inside, ``resolved_dataset_root``. The comparison happens on the
    resolved (canonicalized) forms of both paths.
    """
    if output.suffix != ".json":
        raise PathValidationError(
            f"--output must be a path ending in '.json', got: {output}"
        )

    try:
        resolved_output = output.resolve()
    except (OSError, RuntimeError) as exc:
        raise PathValidationError("--output could not be resolved safely") from exc

    if resolved_output == resolved_dataset_root:
        raise PathValidationError(
            f"--output must not equal the dataset root: {output}"
        )
    if resolved_output.is_relative_to(resolved_dataset_root):
        raise PathValidationError(
            f"--output must not be located inside the dataset root: {output}"
        )

    return resolved_output
