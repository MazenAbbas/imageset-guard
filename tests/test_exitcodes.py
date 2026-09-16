"""Tests for the complete exit-code contract in imageset_guard.exitcodes.

Pins the exact mapping from the approved specification:

    0 = completed and policy passed (PASS or WARN)
    1 = completed with policy violations (FAIL)
    2 = invalid CLI usage or configuration
    3 = INCOMPLETE, or an operational/filesystem failure (e.g. report write)
    4 = unexpected internal error
"""

from __future__ import annotations

import pytest

from imageset_guard.exitcodes import (
    EXIT_INCOMPLETE,
    EXIT_INTERNAL_ERROR,
    EXIT_INTERRUPTED,
    EXIT_INVALID_USAGE,
    EXIT_OK,
    EXIT_POLICY_VIOLATION,
    exit_code_for_status,
)
from imageset_guard.models import ResultStatus


def test_exit_constants_match_the_approved_contract() -> None:
    assert EXIT_OK == 0
    assert EXIT_POLICY_VIOLATION == 1
    assert EXIT_INVALID_USAGE == 2
    assert EXIT_INCOMPLETE == 3
    assert EXIT_INTERNAL_ERROR == 4


def test_exit_interrupted_is_the_new_v02_additive_code() -> None:
    # 130 = 128 + SIGINT(2), the standard Unix convention. New in v0.2;
    # every code above is unchanged from v0.1.
    assert EXIT_INTERRUPTED == 130


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (ResultStatus.PASS, EXIT_OK),
        (ResultStatus.WARN, EXIT_OK),
        (ResultStatus.FAIL, EXIT_POLICY_VIOLATION),
        (ResultStatus.INCOMPLETE, EXIT_INCOMPLETE),
        (ResultStatus.ERROR, EXIT_INTERNAL_ERROR),
    ],
)
def test_exit_code_for_status(status: ResultStatus, expected_code: int) -> None:
    assert exit_code_for_status(status) == expected_code
