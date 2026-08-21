"""Tests for error classification pipeline."""

from __future__ import annotations

from maistro.resilience.classifier import (
    ErrorCategory,
    _classify_402,
    _extract_retry_after,
    classify_error,
)


class _HttpError(Exception):
    def __init__(self, message: str, status_code: int, headers: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = type("Resp", (), {"status_code": status_code, "headers": headers or {}})


class _Timeout(Exception):
    pass


class _RemoteProtocol(Exception):
    pass


class _JsonDecode(Exception):
    pass


class _GenericWithCause(Exception):
    pass


class TestClassifyByHttpStatus:
    def test_429_rate_limit(self):
        err = _HttpError("Rate limit exceeded", 429)
        r = classify_error(err, provider="openai")
        assert r.category == ErrorCategory.RATE_LIMIT
        assert r.retryable is True
        assert r.should_fallback is True
        assert r.should_rotate_credential is True

    def test_429_with_retry_after_header(self):
        err = _HttpError("Slow down", 429, headers={"retry-after": "30"})
        r = classify_error(err)
        assert r.category == ErrorCategory.RATE_LIMIT
        assert r.retry_after_seconds == 30.0

    def test_402_billing_exhausted(self):
        err = _HttpError("Insufficient credits", 402)
        r = classify_error(err)
        assert r.category == ErrorCategory.BILLING
        assert r.retryable is False

    def test_402_usage_limit_transient(self):
        err = _HttpError("Usage limit, try again in 5 minutes", 402)
        r = classify_error(err)
        assert r.category == ErrorCategory.RATE_LIMIT
        assert r.retryable is True
        assert r.should_rotate_credential is True

    def test_401_auth(self):
        err = _HttpError("Invalid API key", 401)
        r = classify_error(err)
        assert r.category == ErrorCategory.AUTH
        assert r.should_rotate_credential is True
        assert r.retryable is False

    def test_403_auth(self):
        err = _HttpError("Forbidden", 403)
        r = classify_error(err)
        assert r.category == ErrorCategory.AUTH

    def test_404_model_not_found(self):
        err = _HttpError("Model gpt-99 not found", 404)
        r = classify_error(err)
        assert r.category == ErrorCategory.MODEL_NOT_FOUND
        assert r.should_fallback is True

    def test_500_transient(self):
        err = _HttpError("Internal server error", 500)
        r = classify_error(err)
        assert r.category == ErrorCategory.TRANSIENT
        assert r.retryable is True
        assert r.should_fallback is True

    def test_502_transient(self):
        err = _HttpError("Bad gateway", 502)
        r = classify_error(err)
        assert r.category == ErrorCategory.TRANSIENT
        assert r.retryable is True

    def test_503_transient(self):
        err = _HttpError("Service unavailable", 503)
        r = classify_error(err)
        assert r.category == ErrorCategory.TRANSIENT

    def test_400_context_overflow(self):
        err = _HttpError("Request too large: maximum context length exceeded", 400)
        r = classify_error(err, context_usage_pct=0.8)
        assert r.category == ErrorCategory.CONTEXT_OVERFLOW
        assert r.should_compress is True

    def test_400_generic(self):
        err = _HttpError("Bad request: invalid parameter", 400)
        r = classify_error(err)
        assert r.category == ErrorCategory.PROVIDER
        assert r.retryable is False


class TestClassifyByExceptionType:
    def test_connection_error(self):
        err = ConnectionError("Connection reset by peer")
        r = classify_error(err)
        assert r.category == ErrorCategory.NETWORK
        assert r.retryable is True
        assert r.should_fallback is True

    def test_timeout_error(self):
        err = TimeoutError("Read timed out")
        r = classify_error(err)
        assert r.category == ErrorCategory.TIMEOUT
        assert r.retryable is True

    def test_custom_timeout_class(self):
        err = _Timeout("Connection timed out after 30s")
        r = classify_error(err)
        assert r.category == ErrorCategory.TIMEOUT
        assert r.retryable is True

    def test_remote_protocol_high_context(self):
        err = _RemoteProtocol("Server disconnected")
        r = classify_error(err, context_usage_pct=0.8, request_messages=250)
        assert r.category == ErrorCategory.UNKNOWN

    def test_remote_protocol_normal_context(self):
        err = _RemoteProtocol("Server disconnected")
        r = classify_error(err, context_usage_pct=0.3, request_messages=10)
        assert r.category == ErrorCategory.UNKNOWN

    def test_json_decode_error(self):
        err = _JsonDecode("JSON decode error at position 42")
        r = classify_error(err)
        assert r.category == ErrorCategory.SCHEMA
        assert r.retryable is True

    def test_network_error_code_in_message(self):
        err = OSError("Connection error: ECONNRESET")
        r = classify_error(err)
        assert r.category == ErrorCategory.NETWORK
        assert r.retryable is True

    def test_ssl_transient(self):
        err = Exception("SSL: CERTIFICATE_VERIFY_FAILED")
        r = classify_error(err)
        assert r.category == ErrorCategory.NETWORK
        assert r.retryable is True


class TestClassifyByMessagePattern:
    def test_content_filter(self):
        err = Exception("Output blocked by content filter")
        r = classify_error(err)
        assert r.category == ErrorCategory.CONTENT_FILTER
        assert r.retryable is False

    def test_model_not_found_in_message(self):
        err = Exception("Model claude-99 does not exist")
        r = classify_error(err)
        assert r.category == ErrorCategory.MODEL_NOT_FOUND
        assert r.should_fallback is True

    def test_schema_error(self):
        err = Exception("Invalid schema for tool call")
        r = classify_error(err)
        assert r.category == ErrorCategory.SCHEMA


class TestClassifyByContextOverflow:
    def test_context_overflow_pattern_high_usage(self):
        err = Exception("This model's maximum context length is 128000 tokens")
        r = classify_error(err, context_usage_pct=0.85)
        assert r.category == ErrorCategory.CONTEXT_OVERFLOW
        assert r.should_compress is True
        assert r.retryable is True

    def test_context_overflow_low_usage(self):
        err = Exception("token limit exceeded")
        r = classify_error(err, context_usage_pct=0.3)
        assert r.category == ErrorCategory.CONTEXT_OVERFLOW
        assert r.should_compress is True


class TestCauseChainWalking:
    def test_cause_chain_resolution(self):
        inner = _HttpError("Rate limit exceeded", 429)
        outer = _GenericWithCause("Wrapper error")
        outer.__cause__ = inner
        r = classify_error(outer)
        assert r.category == ErrorCategory.RATE_LIMIT

    def test_unknown_cause_chain(self):
        inner = ValueError("Some non-API error")
        outer = _GenericWithCause("Wrapper")
        outer.__cause__ = inner
        r = classify_error(outer)
        assert r.category == ErrorCategory.UNKNOWN


class TestUnknownFallback:
    def test_unknown_error(self):
        err = RuntimeError("Something completely unexpected")
        r = classify_error(err, provider="test", model="m1")
        assert r.category == ErrorCategory.UNKNOWN
        assert r.retryable is False
        assert r.provider == "test"
        assert r.model == "m1"


class TestExtractRetryAfter:
    def test_seconds(self):
        assert _extract_retry_after("try again in 30 seconds") == 30.0

    def test_minutes(self):
        assert _extract_retry_after("try again in 2 min") == 120.0

    def test_hours(self):
        assert _extract_retry_after("try again in 1 hour") == 3600.0

    def test_no_match(self):
        assert _extract_retry_after("generic error") is None

    def test_bare_number_with_retry_keyword(self):
        # "retry after N" is an explicit retry hint, so honour it.
        assert _extract_retry_after("retry after 45") == 45.0

    def test_bare_number_in_prose_ignored(self):
        # A bare number with neither a unit nor a retry keyword must NOT
        # be parsed as a retry-after value. The status code leaking into
        # the error message is the canonical trap.
        assert _extract_retry_after("429 Too Many Requests for model gpt-4") is None

    def test_seconds_short_unit(self):
        assert _extract_retry_after("5s") == 5.0

    def test_milliseconds_unit(self):
        assert _extract_retry_after("retry after 500ms") == 0.5

    def test_status_code_429_prose_stays_retryable(self):
        # End-to-end: a 429 whose body merely repeats the status code must
        # remain retryable. A spurious retry_after=429 would exceed
        # max_delay (60) and make compute_backoff abort the retry.
        err = _HttpError("429 Too Many Requests for model gpt-4", 429)
        r = classify_error(err)
        assert r.category == ErrorCategory.RATE_LIMIT
        assert r.retryable is True
        assert r.retry_after_seconds is None


class TestClassify402:
    def test_billing_credits_exhausted(self):
        assert _classify_402("Credits exhausted") == ErrorCategory.BILLING

    def test_billing_insufficient(self):
        assert _classify_402("Insufficient credits") == ErrorCategory.BILLING

    def test_billing_plan_limit(self):
        assert _classify_402("Plan limit reached") == ErrorCategory.BILLING

    def test_usage_limit_transient(self):
        assert _classify_402("Usage limit exceeded") == ErrorCategory.RATE_LIMIT

    def test_usage_limit_with_retry(self):
        assert _classify_402("Try again in 5 minutes") == ErrorCategory.RATE_LIMIT

    def test_ambiguous_defaults_billing(self):
        assert _classify_402("Payment required") == ErrorCategory.BILLING


class TestProviderMetadata:
    def test_provider_and_model_propagated(self):
        err = _HttpError("Rate limit", 429)
        r = classify_error(err, provider="anthropic", model="claude-3")
        assert r.provider == "anthropic"
        assert r.model == "claude-3"

    def test_context_usage_propagated(self):
        err = _HttpError("Server error", 500)
        r = classify_error(err, context_usage_pct=0.75)
        assert r.context_usage_pct == 0.75
