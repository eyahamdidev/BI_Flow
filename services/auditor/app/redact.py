"""Strip provider secrets before anything is written to a warning or a log."""

from __future__ import annotations

import re

_SECRET = re.compile(r"gsk_[A-Za-z0-9]+|sk-[A-Za-z0-9_\-]+|Bearer\s+\S+", re.I)


def redact(text: str | None) -> str:
    return _SECRET.sub("[redacted]", text or "")
