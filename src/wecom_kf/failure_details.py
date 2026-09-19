"""Safe, operator-facing failure descriptions.

Provider exceptions are useful for diagnosing a job, but their text can also
contain passwords, cookies, tokens, or an entire response body.  This module
keeps a bounded, redacted description suitable for the durable job result and
the administrator console.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(password|passwd|token|secret|cookie|authorization|api[_ -]?key)"
    r"\s*[:=]\s*(?:Bearer\s+)?([^,;\s}]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def safe_error_text(value: Any, *, secrets: Iterable[Any] = (), limit: int = 512) -> str:
    """Return bounded diagnostic text with credentials removed.

    An empty provider message is represented by its exception/type name by the
    caller; this function itself never invents a placeholder reason.
    """

    text = " ".join(str(value or "").split())
    for secret in secrets:
        if isinstance(secret, str) and secret:
            text = text.replace(secret, "[已脱敏]")
    text = _SENSITIVE_ASSIGNMENT.sub(lambda m: f"{m.group(1)}=[已脱敏]", text)
    text = _BEARER.sub("Bearer [已脱敏]", text)
    text = _CONTROL.sub("", text).strip()
    return text[:limit]


def exception_detail(exc: BaseException, *, secrets: Iterable[Any] = ()) -> str:
    """Format an exception as a useful, redacted operator diagnostic."""

    message = safe_error_text(exc, secrets=secrets)
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def add_failure(result: dict[str, Any], detail: str) -> None:
    """Append one bounded failure detail without creating empty entries."""

    detail = safe_error_text(detail)
    if not detail:
        return
    failures = result.setdefault("failures", [])
    if isinstance(failures, list) and detail not in failures and len(failures) < 50:
        failures.append(detail)
