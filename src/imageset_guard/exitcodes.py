"""The process exit-code contract.

Values 0-4 are the complete v1 contract and keep their original meanings
unchanged in v0.2. ``EXIT_INTERRUPTED`` (130) is new in v0.2, additive:
the standard Unix convention (128 + SIGINT's signal number 2) for a
process a user deliberately interrupted with Ctrl+C.
"""

from __future__ import annotations

from typing import Final

from imageset_guard.models import ResultStatus

EXIT_OK: Final = 0
EXIT_POLICY_VIOLATION: Final = 1
EXIT_INVALID_USAGE: Final = 2
EXIT_INCOMPLETE: Final = 3
EXIT_INTERNAL_ERROR: Final = 4
EXIT_INTERRUPTED: Final = 130

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
