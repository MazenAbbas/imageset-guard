"""The process exit-code contract.

These five values (0-4) are the complete v1 contract.
"""

from __future__ import annotations

from typing import Final

from imageset_guard.models import ResultStatus

EXIT_OK: Final = 0
EXIT_POLICY_VIOLATION: Final = 1
EXIT_INVALID_USAGE: Final = 2
EXIT_INCOMPLETE: Final = 3
EXIT_INTERNAL_ERROR: Final = 4

_EXIT_CODE_BY_STATUS: Final[dict[ResultStatus, int]] = {
    ResultStatus.PASS: EXIT_OK,
    ResultStatus.WARN: EXIT_OK,
    ResultStatus.FAIL: EXIT_POLICY_VIOLATION,
    ResultStatus.INCOMPLETE: EXIT_INCOMPLETE,
    ResultStatus.ERROR: EXIT_INTERNAL_ERROR,
}


def exit_code_for_status(status: ResultStatus) -> int:
    """Map a completed :class:`ResultStatus` to its process exit code."""
    return _EXIT_CODE_BY_STATUS[status]
