"""Operator-correctable CLI failures. Anything raising UsageError is a usage
problem with a hint, not a bug; cli.main() renders it as {error, hint} and
exits nonzero. InternalError is an engine invariant that failed (a bug, not a
usage problem): rendered the same way with kind "internal" and exit code 4.
Other unexpected exceptions keep their traceback."""

from __future__ import annotations


class UsageError(Exception):
    def __init__(
        self,
        message: str,
        hint: str | None = None,
        exit_code: int = 2,
        kind: str | None = None,
        details: object = None,
    ) -> None:
        super().__init__(message)
        self.hint = hint
        self.exit_code = exit_code
        self.kind = kind  # machine-readable failure class, e.g. "live_running"
        self.details = details


_REPORT_HINT = ("this is an engine bug; nothing was written. "
                "Please report it with the command you ran")


class InternalError(UsageError, ValueError):
    """An engine invariant failed (e.g. overlapping edits, an id collision).
    Still a ValueError for library callers."""

    def __init__(self, message: str, details: object = None) -> None:
        super().__init__(message, hint=_REPORT_HINT, exit_code=4, kind="internal",
                         details=details)
