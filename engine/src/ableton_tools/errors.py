"""Operator-correctable CLI failures. Anything raising UsageError is a usage
problem with a hint, not a bug; cli.main() renders it as {error, hint} and
exits nonzero. Genuine bugs keep raising ordinary exceptions and traceback."""

from __future__ import annotations


class UsageError(Exception):
    def __init__(self, message: str, hint: str | None = None, exit_code: int = 2) -> None:
        super().__init__(message)
        self.hint = hint
        self.exit_code = exit_code
