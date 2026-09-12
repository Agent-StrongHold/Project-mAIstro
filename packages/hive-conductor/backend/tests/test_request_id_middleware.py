"""Tests for Hive Conductor's request-id correlation middleware (#1063).

Hive had no `RequestIDMiddleware` and no `X-Request-ID` handling at all, so the
user-facing request, the Conductor->maistro-server service hop, and the
resulting canonical Run could not be followed by one correlation identity.
This reuses maistro-core's existing, already-tested `RequestIDMiddleware`
rather than a second implementation (see
`packages/maistro-core/tests/observability/test_middleware.py` for the
contract itself: validation pattern, normalization of invalid/duplicate
values, response echo). These tests hold the Hive-specific half: the
middleware is actually wired into `main:app`'s stack, and wraps enough of it
that an id is available even on an early rejection.

Written from scratch, following this test dir's convention of driving the
real ``main:app`` + middleware stack via TestClient (see
test_security_headers.py).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from main import app


def _client() -> TestClient:
    return TestClient(app)


class TestRequestIDPresence:
    def test_a_fresh_id_is_generated_when_none_is_sent(self) -> None:
        c = _client()
        r = c.get("/health")
        assert r.headers["X-Request-ID"]

    def test_two_requests_get_two_different_generated_ids(self) -> None:
        c = _client()
        first = c.get("/health").headers["X-Request-ID"]
        second = c.get("/health").headers["X-Request-ID"]
        assert first != second

    def test_a_valid_client_supplied_id_is_echoed_back_unchanged(self) -> None:
        c = _client()
        r = c.get("/health", headers={"X-Request-ID": "caller-supplied-123"})
        assert r.headers["X-Request-ID"] == "caller-supplied-123"

    def test_an_invalid_client_supplied_id_is_replaced(self) -> None:
        """Same contract as maistro-server's RequestIDMiddleware: punctuation-only
        values (no letter/digit) are rejected rather than trusted verbatim."""
        c = _client()
        r = c.get("/health", headers={"X-Request-ID": "!!!"})
        assert r.headers["X-Request-ID"] != "!!!"
        assert r.headers["X-Request-ID"]

    def test_the_id_is_present_even_on_an_early_rejection(self) -> None:
        """RequestIDMiddleware must wrap AuthMiddleware, not sit inside it --
        an id is exactly as useful for correlating a 401 as a 200."""
        c = _client()
        r = c.get("/v1/tasks")
        assert r.status_code == 401
        assert r.headers["X-Request-ID"]
