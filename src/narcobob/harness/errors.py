"""The one exception type tools raise; the harness turns it into an error envelope."""

from __future__ import annotations

from narcobob.common.schemas import ErrorCode

RETRYABLE: frozenset[str] = frozenset({"TIMEOUT", "INTERNAL"})


class ToolFailure(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE
