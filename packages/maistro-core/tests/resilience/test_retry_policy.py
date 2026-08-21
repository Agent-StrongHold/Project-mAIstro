from __future__ import annotations

import pytest

from maistro.resilience.retry_policy import (
    OperationStage,
    get_delay,
    get_policy,
    should_retry,
)


class _HttpError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = type("Resp", (), {"status_code": status_code, "headers": {}})


class TestStagePolicies:
    @pytest.mark.ac("ADR-066/AC-31")
    def test_read_policy(self):
        p = get_policy(OperationStage.READ)
        assert p.max_attempts == 3
        assert p.base_delay == 0.25
        assert p.max_delay == 2.0
        assert p.retryable is True

    @pytest.mark.ac("ADR-066/AC-32")
    def test_evaluate_policy(self):
        p = get_policy(OperationStage.EVALUATE)
        assert p.max_attempts == 2
        assert p.base_delay == 1.0
        assert p.max_delay == 8.0
        assert p.retryable is True

    @pytest.mark.ac("ADR-066/AC-33")
    def test_write_policy(self):
        p = get_policy(OperationStage.WRITE)
        assert p.max_attempts == 1
        assert p.base_delay == 0.0
        assert p.max_delay == 0.0
        assert p.retryable is False

    def test_policies_are_frozen(self):
        p = get_policy(OperationStage.READ)
        with pytest.raises(AttributeError):
            p.max_attempts = 5


class TestShouldRetry:
    def test_read_transient_retryable(self):
        err = _HttpError("Server error", 500)
        assert should_retry(OperationStage.READ, 0, err) is True

    @pytest.mark.ac("ADR-066/AC-31")
    def test_read_exhausted_attempts(self):
        err = _HttpError("Server error", 500)
        assert should_retry(OperationStage.READ, 0, err) is True
        assert should_retry(OperationStage.READ, 1, err) is True
        assert should_retry(OperationStage.READ, 2, err) is True
        assert should_retry(OperationStage.READ, 3, err) is False

    @pytest.mark.ac("ADR-066/AC-32")
    def test_evaluate_transient_retryable(self):
        err = _HttpError("Server error", 500)
        assert should_retry(OperationStage.EVALUATE, 0, err) is True
        assert should_retry(OperationStage.EVALUATE, 1, err) is True
        assert should_retry(OperationStage.EVALUATE, 2, err) is False

    @pytest.mark.ac("ADR-066/AC-33")
    def test_write_never_retries(self):
        err = _HttpError("Server error", 500)
        assert should_retry(OperationStage.WRITE, 0, err) is False

    @pytest.mark.ac("ADR-066/AC-35")
    def test_non_transient_not_retried(self):
        err = _HttpError("Unauthorized", 401)
        assert should_retry(OperationStage.READ, 0, err) is False

    def test_rate_limit_is_retryable(self):
        err = _HttpError("Rate limited", 429)
        assert should_retry(OperationStage.READ, 0, err) is True

    def test_connection_error_retryable(self):
        err = ConnectionError("Connection reset by peer")
        assert should_retry(OperationStage.READ, 0, err) is True


class TestGetDelay:
    @pytest.mark.ac("ADR-066/AC-31")
    def test_read_fixed_delay(self):
        assert get_delay(OperationStage.READ, 0) == 0.25
        assert get_delay(OperationStage.READ, 1) == 0.25
        assert get_delay(OperationStage.READ, 2) == 0.25

    @pytest.mark.ac("ADR-066/AC-32")
    def test_evaluate_exponential_delay(self):
        assert get_delay(OperationStage.EVALUATE, 0) == 1.0
        assert get_delay(OperationStage.EVALUATE, 1) == 2.0
        assert get_delay(OperationStage.EVALUATE, 2) == 4.0
        assert get_delay(OperationStage.EVALUATE, 3) == 8.0

    def test_evaluate_capped_at_max(self):
        assert get_delay(OperationStage.EVALUATE, 4) == 8.0

    @pytest.mark.ac("ADR-066/AC-33")
    def test_write_zero_delay(self):
        assert get_delay(OperationStage.WRITE, 0) == 0.0
        assert get_delay(OperationStage.WRITE, 1) == 0.0
