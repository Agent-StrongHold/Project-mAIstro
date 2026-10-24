"""Safe, bounded failure evidence for durable Graph state and recovery logs."""

from __future__ import annotations

import re

from maistro.security.redact import redact

_SAFE_DETAIL = re.compile(r"(?i)\b(password|token|secret|api[_-]?key)\b\s*[=:]\s*[^\s,;]+")


def sanitize_failure_message(message: object, *, limit: int = 512) -> str:
    """Return one bounded failure line without persisting credential-shaped text."""
    text = str(message) if message else ""
    detail = text.splitlines()[0].strip() if text else ""
    detail = redact(_SAFE_DETAIL.sub(r"\1=<redacted>", detail))
    return detail[:limit] or "unknown failure"


__all__ = ["sanitize_failure_message"]
