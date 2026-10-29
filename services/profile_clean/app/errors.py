"""Domain errors mapped to contract error codes."""
from __future__ import annotations


class ProfileCleanError(Exception):
    code: str = "INTERNAL"
    http_status: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadInputError(ProfileCleanError):
    code = "BAD_INPUT"
    http_status = 400


class SchemaMismatchError(ProfileCleanError):
    code = "SCHEMA_MISMATCH"
    http_status = 400


class TimeoutError(ProfileCleanError):  # noqa: A001
    code = "TIMEOUT"
    http_status = 504


class ReconciliationError(ProfileCleanError):
    code = "INTERNAL"
    http_status = 500
