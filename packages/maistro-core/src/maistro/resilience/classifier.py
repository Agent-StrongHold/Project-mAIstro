"""Priority-ordered error classification pipeline.

Produces a ``ClassifiedError`` with actionable flags for retry, fallback,
credential rotation, and compression decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class ErrorCategory(StrEnum):
    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    BILLING = "billing"
    AUTH = "auth"
    CONTEXT_OVERFLOW = "context_overflow"
    MODEL_NOT_FOUND = "model_not_found"
    CONTENT_FILTER = "content_filter"
    NETWORK = "network"
    TIMEOUT = "timeout"
    SCHEMA = "schema"
    PROVIDER = "provider"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassifiedError:
    category: ErrorCategory
    original: Exception
    message: str = ""
    retryable: bool = False
    should_fallback: bool = False
    should_rotate_credential: bool = False
    should_compress: bool = False
    retry_after_seconds: float | None = None
    provider: str = ""
    model: str = ""
    context_usage_pct: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)


_TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}
_PERMANENT_HTTP_CODES = {400, 401, 403, 404, 405, 422}
_AUTH_HTTP_CODES = {401, 403}

_BILLING_PATTERNS = re.compile(
    r"insufficient\s+credits|credits?\s+exhausted|billing\s+limit|"
    r"plan\s+limit|subscription\s+(expired|inactive)",
    re.IGNORECASE,
)

_USAGE_LIMIT_PATTERNS = re.compile(
    r"usage\s*limit|rate\s*limit|too\s*many\s*requests|"
    r"try\s+again\s+in\s+(\d+)\s*(s|sec|second|min|minute|hour)",
    re.IGNORECASE,
)

_RATE_LIMIT_HEADER_PATTERNS = re.compile(
    r"retry.?after|x.?ratelimit.?reset|x.?ratelimit.?remaining",
    re.IGNORECASE,
)

# A bare number in prose (e.g. the status code in "429 Too Many Requests")
# must NOT be read as a retry-after value. We only accept a number when it is
# either (a) followed by an explicit time unit, or (b) preceded by a "retry
# after" / "try again in" style hint. Structured headers are handled separately
# in ``_retry_after_from_headers``.
_RETRY_AFTER_PATTERN = re.compile(
    r"(?:(?:retry|try\s+again)[^\d]{0,12})(\d+(?:\.\d+)?)\s*(ms|s|sec|second|min|minute|h|hour)?"
    r"|(\d+(?:\.\d+)?)\s*(ms|s|sec|seconds?|min|minute|minutes?|h|hour|hours?)\b",
    re.IGNORECASE,
)

_NETWORK_ERROR_NAMES = frozenset(
    {
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "TimeoutError",
        "RemoteProtocolError",
        "LocalProtocolError",
    }
)

_NETWORK_ERROR_CODES = frozenset(
    {
        "econnreset",
        "econnrefused",
        "etimedout",
        "eai_again",
        "epipe",
        "enotfound",
        "ehostunreach",
    }
)

_SSL_PATTERNS = re.compile(
    r"ssl|tls|certificate|handshake|CERTIFICATE_VERIFY_FAILED|"
    r"WRONG_VERSION_NUMBER|DECRYPTION_FAILED|EXCESSIVE_MESSAGE_SIZE",
    re.IGNORECASE,
)

_CONTEXT_OVERFLOW_PATTERNS = re.compile(
    r"context.?length|maximum.?context|token.?limit|too many tokens|"
    r"request too large|input too long|prompt is too long|"
    r"reduce the length|exceeds the maximum",
    re.IGNORECASE,
)

_MODEL_NOT_FOUND_PATTERNS = re.compile(
    r"model.*not\s*(found|available|exist)|does not exist|"
    r"invalid model|model.*deprecated|model.*been removed",
    re.IGNORECASE,
)

_CONTENT_FILTER_PATTERNS = re.compile(
    r"content.?filter|content.?policy|safety.?system|flagged|"
    r"refused|blocked by|output blocked",
    re.IGNORECASE,
)


def _extract_retry_after(message: str) -> float | None:
    m = _RETRY_AFTER_PATTERN.search(message)
    if not m:
        return None
    # Branch 1 (retry/try-again hint): groups 1+2. Branch 2 (unit required): 3+4.
    if m.group(1) is not None:
        value = float(m.group(1))
        raw_unit = m.group(2)
    else:
        value = float(m.group(3))
        raw_unit = m.group(4)
    unit = (raw_unit or "s").lower()
    if unit == "ms":
        return value / 1000.0
    if unit.startswith("min"):
        return value * 60
    if unit.startswith("h"):
        return value * 3600
    return value


def _is_ssl_transient(message: str) -> bool:
    return bool(_SSL_PATTERNS.search(message))


def _classify_402(message: str) -> ErrorCategory:
    if _BILLING_PATTERNS.search(message):
        return ErrorCategory.BILLING
    if _USAGE_LIMIT_PATTERNS.search(message):
        return ErrorCategory.RATE_LIMIT
    return ErrorCategory.BILLING


def _infer_context_overflow(error: Exception, message: str) -> bool:
    if _CONTEXT_OVERFLOW_PATTERNS.search(message):
        return True
    error_name = type(error).__name__
    return error_name == "RemoteProtocolError" and "disconnect" in message.lower()


def _classify_network(
    error: Exception,
    *,
    message: str,
    lower_msg: str,
    error_name: str,
    provider: str,
    model: str,
    context_usage_pct: float,
) -> ClassifiedError | None:
    """Classify connection/network/SSL errors. Returns ``None`` if not a network error."""
    if error_name in _NETWORK_ERROR_NAMES or error_name == "ConnectionError":
        should_compress = (
            "disconnect" in message.lower() or "protocol" in message.lower()
        ) and context_usage_pct > 0.6
        return ClassifiedError(
            category=ErrorCategory.NETWORK,
            original=error,
            message=message,
            retryable=True,
            should_fallback=True,
            should_compress=should_compress,
            provider=provider,
            model=model,
        )

    if any(code in lower_msg for code in _NETWORK_ERROR_CODES):
        return ClassifiedError(
            category=ErrorCategory.NETWORK,
            original=error,
            message=message,
            retryable=True,
            should_fallback=True,
            provider=provider,
            model=model,
        )

    if _SSL_PATTERNS.search(message):
        return ClassifiedError(
            category=ErrorCategory.NETWORK,
            original=error,
            message=message,
            retryable=True,
            provider=provider,
            model=model,
        )

    return None


def _classify_by_message_patterns(
    error: Exception,
    *,
    message: str,
    lower_msg: str,
    error_name: str,
    provider: str,
    model: str,
    context_usage_pct: float,
) -> ClassifiedError | None:
    """Classify a status-less error from its message/type. Returns ``None`` if
    no message-based pattern matched (caller then inspects the cause chain)."""
    if _infer_context_overflow(error, message):
        return ClassifiedError(
            category=ErrorCategory.CONTEXT_OVERFLOW,
            original=error,
            message=message,
            retryable=True,
            should_compress=True,
            provider=provider,
            model=model,
            context_usage_pct=context_usage_pct,
        )

    if _CONTENT_FILTER_PATTERNS.search(message):
        return ClassifiedError(
            category=ErrorCategory.CONTENT_FILTER,
            original=error,
            message=message,
            provider=provider,
            model=model,
        )

    if _MODEL_NOT_FOUND_PATTERNS.search(message):
        return ClassifiedError(
            category=ErrorCategory.MODEL_NOT_FOUND,
            original=error,
            message=message,
            should_fallback=True,
            provider=provider,
            model=model,
        )

    if "timeout" in lower_msg or error_name.endswith("Timeout") or error_name == "TimeoutError":
        return ClassifiedError(
            category=ErrorCategory.TIMEOUT,
            original=error,
            message=message,
            retryable=True,
            should_fallback=True,
            provider=provider,
            model=model,
        )

    network = _classify_network(
        error,
        message=message,
        lower_msg=lower_msg,
        error_name=error_name,
        provider=provider,
        model=model,
        context_usage_pct=context_usage_pct,
    )
    if network is not None:
        return network

    if "timeout" in lower_msg or error_name.endswith("Timeout"):
        return ClassifiedError(
            category=ErrorCategory.TIMEOUT,
            original=error,
            message=message,
            retryable=True,
            should_fallback=True,
            provider=provider,
            model=model,
        )

    if "json" in lower_msg and ("decode" in lower_msg or "parse" in lower_msg):
        return ClassifiedError(
            category=ErrorCategory.SCHEMA,
            original=error,
            message=message,
            retryable=True,
            provider=provider,
            model=model,
        )

    if "schema" in lower_msg or "grammar" in lower_msg:
        return ClassifiedError(
            category=ErrorCategory.SCHEMA,
            original=error,
            message=message,
            provider=provider,
            model=model,
        )

    return None


def classify_error(
    error: Exception,
    *,
    provider: str = "",
    model: str = "",
    context_usage_pct: float = 0.0,
    request_messages: int = 0,
) -> ClassifiedError:
    message = str(error)
    error_name = type(error).__name__
    error_module = type(error).__module__ or ""
    lower_msg = message.lower()

    status_code = _extract_status_code(error)
    headers = _extract_headers(error)

    if status_code is not None:
        return _classify_by_status(
            error,
            status_code,
            message,
            headers,
            provider=provider,
            model=model,
            context_usage_pct=context_usage_pct,
        )

    by_pattern = _classify_by_message_patterns(
        error,
        message=message,
        lower_msg=lower_msg,
        error_name=error_name,
        provider=provider,
        model=model,
        context_usage_pct=context_usage_pct,
    )
    if by_pattern is not None:
        return by_pattern

    cause = error.__cause__ or error.__context__
    if isinstance(cause, Exception) and cause is not error:
        inner = classify_error(
            cause,
            provider=provider,
            model=model,
            context_usage_pct=context_usage_pct,
        )
        if inner.category != ErrorCategory.UNKNOWN:
            return inner

    logger.debug(
        "unclassified_error",
        error_name=error_name,
        error_module=error_module,
        message=message[:200],
    )

    return ClassifiedError(
        category=ErrorCategory.UNKNOWN,
        original=error,
        message=message,
        retryable=False,
        provider=provider,
        model=model,
    )


def _classify_by_status(
    error: Exception,
    status_code: int,
    message: str,
    headers: dict[str, str],
    *,
    provider: str,
    model: str,
    context_usage_pct: float,
) -> ClassifiedError:
    if status_code == 429:
        retry_after = _extract_retry_after(message) or _retry_after_from_headers(headers)
        return ClassifiedError(
            category=ErrorCategory.RATE_LIMIT,
            original=error,
            message=message,
            retryable=True,
            should_fallback=True,
            should_rotate_credential=True,
            retry_after_seconds=retry_after,
            provider=provider,
            model=model,
        )

    if status_code == 402:
        cat = _classify_402(message)
        is_transient = cat == ErrorCategory.RATE_LIMIT
        return ClassifiedError(
            category=cat,
            original=error,
            message=message,
            retryable=is_transient,
            should_fallback=is_transient,
            should_rotate_credential=is_transient,
            provider=provider,
            model=model,
        )

    if status_code in _AUTH_HTTP_CODES:
        if "model" in message.lower() and (
            "not found" in message.lower() or "access" in message.lower()
        ):
            return ClassifiedError(
                category=ErrorCategory.MODEL_NOT_FOUND,
                original=error,
                message=message,
                should_fallback=True,
                provider=provider,
                model=model,
            )
        return ClassifiedError(
            category=ErrorCategory.AUTH,
            original=error,
            message=message,
            should_rotate_credential=True,
            provider=provider,
            model=model,
        )

    if status_code == 404:
        return ClassifiedError(
            category=ErrorCategory.MODEL_NOT_FOUND,
            original=error,
            message=message,
            should_fallback=True,
            provider=provider,
            model=model,
        )

    if status_code in _TRANSIENT_HTTP_CODES:
        should_compress = _infer_context_overflow(error, message) and context_usage_pct > 0.6
        return ClassifiedError(
            category=ErrorCategory.TRANSIENT,
            original=error,
            message=message,
            retryable=True,
            should_fallback=True,
            should_compress=should_compress,
            provider=provider,
            model=model,
            context_usage_pct=context_usage_pct,
        )

    if status_code == 400:
        if _CONTEXT_OVERFLOW_PATTERNS.search(message):
            return ClassifiedError(
                category=ErrorCategory.CONTEXT_OVERFLOW,
                original=error,
                message=message,
                retryable=True,
                should_compress=True,
                provider=provider,
                model=model,
            )
        return ClassifiedError(
            category=ErrorCategory.PROVIDER,
            original=error,
            message=message,
            provider=provider,
            model=model,
        )

    return ClassifiedError(
        category=ErrorCategory.PROVIDER,
        original=error,
        message=message,
        provider=provider,
        model=model,
    )


def _extract_status_code(error: Exception) -> int | None:
    for attr in ("status_code", "statusCode", "code"):
        val = getattr(error, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(error, "response", None)
    if resp is not None:
        code = getattr(resp, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def _extract_headers(error: Exception) -> dict[str, str]:
    resp = getattr(error, "response", None)
    if resp is None:
        return {}
    headers = getattr(resp, "headers", None)
    if headers is None:
        return {}
    return dict(headers)


def _retry_after_from_headers(headers: dict[str, str]) -> float | None:
    for key in ("retry-after", "Retry-After", "x-ratelimit-reset"):
        val = headers.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                return _extract_retry_after(val)
    return None
