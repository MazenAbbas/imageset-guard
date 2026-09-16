"""Environment diagnostics for ``imageset-guard doctor``.

Checks the installation and environment only -- Python version, Pillow
availability, the package's own version, and whether the system temp
directory is writable (the same prerequisite ``--output`` needs). Never
opens, lists, or otherwise reads any user dataset.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from imageset_guard import __version__

_MIN_PYTHON: tuple[int, int] = (3, 11)


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One diagnostic check's outcome."""

    name: str
    ok: bool
    detail: str


def run_doctor_checks(*, temp_dir: Path | None = None) -> list[DoctorCheck]:
    """Run every environment check and return their results, in order."""
    checks = [
        _check_python_version(),
        _check_pillow(),
        DoctorCheck("imageset_guard_version", True, __version__),
        _check_temp_dir_writable(temp_dir),
    ]
    return checks


def _check_python_version() -> DoctorCheck:
    version = sys.version_info
    ok = (version.major, version.minor) >= _MIN_PYTHON
    detail = f"{version.major}.{version.minor}.{version.micro}"
    if not ok:
        detail += f" (requires >= {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]})"
    return DoctorCheck("python_version", ok, detail)


def _check_pillow() -> DoctorCheck:
    try:
        import PIL
    except ImportError:
        return DoctorCheck("pillow_importable", False, "Pillow could not be imported")
    return DoctorCheck("pillow_importable", True, PIL.__version__)


def _check_temp_dir_writable(temp_dir: Path | None) -> DoctorCheck:
    base = temp_dir if temp_dir is not None else Path(tempfile.gettempdir())
    try:
        fd, name = tempfile.mkstemp(dir=base, prefix=".imageset-guard-doctor-")
        os.close(fd)
        with contextlib.suppress(OSError):
            Path(name).unlink()
    except OSError:
        return DoctorCheck("temp_dir_writable", False, f"cannot write to {base}")
    return DoctorCheck("temp_dir_writable", True, str(base))
