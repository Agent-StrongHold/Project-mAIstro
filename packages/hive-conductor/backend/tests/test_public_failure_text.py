"""A failure reaches the browser as a kind, never as its own text.

Exception messages on these paths carry filesystem paths, internal hostnames,
and whole provider replies. Returning `str(exc)` to a client publishes all of
it (CodeQL py/stack-trace-exposure). Each of these paths now answers with the
exception's class name and a fixed sentence, and writes the real detail to the
server log with its traceback.

These tests exist to pin the text that crosses the boundary. A regression here
is silent otherwise: the route still returns 200, the widget still renders an
error, and nobody notices which one it is until the message is in someone's
browser.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

PUBLIC_WIDGET_TEXT = "RuntimeError: request failed; see server logs"


class _Request:
    """The attribute surface these handlers touch, and nothing else."""

    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}


class _StubResolver:
    """Stands in for credential resolution so the test reaches the query arm."""

    def __init__(self, _store: Any) -> None:
        pass

    def first_secret(self, *_args: Any, **_kwargs: Any) -> str:
        return "pat-token"


def _boom(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("connect to db-primary.internal:5432 failed for user svc_jira")


class TestAWidgetFailureNamesItsKindAndNothingElse:
    async def test_the_jira_widget_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from routes import widgets

        monkeypatch.setattr(widgets, "_jira_pat", lambda _request: "pat")
        monkeypatch.setattr(widgets, "shared_client", _boom)

        result = await widgets.widget_jira(_Request(), project="ENG")

        assert result["error"] == PUBLIC_WIDGET_TEXT
        assert result["total"] == 0
        assert "db-primary.internal" not in str(result)

    async def test_the_airtable_widget_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Past the credential guard, which has its own fixed message: this is
        the query arm, where a provider reply used to come back verbatim."""
        import stores
        from routes import widgets
        from services import user_credentials as cred_svc

        monkeypatch.setattr(widgets, "_user_id", lambda _request: "u1")
        monkeypatch.setattr(cred_svc, "get_credential_store", lambda: object())
        monkeypatch.setattr(widgets, "ToolCredentialResolver", _StubResolver)
        monkeypatch.setattr(stores, "user_provider_config", {"u1:airtable": {"base_id": "appX"}})
        monkeypatch.setattr(widgets, "get_airtable_records_json", _boom)

        result = await widgets.widget_airtable(_Request(), table="Tasks")

        assert result["error"] == PUBLIC_WIDGET_TEXT
        assert result["records"] == []
        assert "svc_jira" not in str(result)

    async def test_the_airtable_table_listing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from routes import widgets
        from services import user_credentials as cred_svc

        monkeypatch.setattr(widgets, "_user_id", lambda _request: "u1")
        monkeypatch.setattr(cred_svc, "get_credential_store", _boom)

        result = await widgets.widget_airtable_tables(_Request(), base_id="appX")

        assert result["error"] == PUBLIC_WIDGET_TEXT
        assert result["tables"] == []

    async def test_the_dashboard_screenshot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A stub module keeps this on the non-ImportError arm whether or not
        Playwright is installed on the runner -- the arm that used to leak."""
        from routes import widgets

        stub = types.ModuleType("playwright.async_api")
        stub.async_playwright = _boom  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
        monkeypatch.setitem(sys.modules, "playwright.async_api", stub)

        result = await widgets.capture_screenshot(_Request())

        assert result == {"error": PUBLIC_WIDGET_TEXT}


class TestAFailedRsiRunRecordsAKindNotAMessage:
    async def test_the_stored_last_error_is_the_exception_class(self) -> None:
        """`last_error` is handed to the browser with the run record, so the
        provider reply that caused it must not travel with it."""
        from services import rsi

        service = rsi._RsiService()
        run = rsi.RunState(run_id="r1", mode="greenfield", config={})

        async def _fail(_run: rsi.RunState) -> None:
            raise ValueError("/srv/secrets/openai.key rejected by api.internal")

        service._drive_greenfield = _fail  # type: ignore[method-assign]
        await service._drive(run)

        assert run.status == "errored"
        assert run.last_error == "ValueError: run failed; see server logs"
        assert run.ended_at is not None

    async def test_a_cancelled_run_is_stopped_rather_than_errored(self) -> None:
        """The cancellation arm sits above the one under test; a stop must not
        be recorded as a failure just because both end the run."""
        from services import rsi

        service = rsi._RsiService()
        run = rsi.RunState(run_id="r2", mode="greenfield", config={})

        async def _cancel(_run: rsi.RunState) -> None:
            raise asyncio.CancelledError

        service._drive_greenfield = _cancel  # type: ignore[method-assign]
        with pytest.raises(asyncio.CancelledError):
            await service._drive(run)

        assert run.status == "stopped"
        assert run.last_error is None


class TestAnAirtableTokenFingerprintIsNotAnOfflineOracle:
    """The fingerprint keys a cache entry. A bare digest of the token lets
    anyone holding a candidate token confirm it from a log line, so the
    derivation is salted per process and stretched (CodeQL py/weak-sensitive-data-hashing)."""

    def test_it_is_stable_within_a_process_and_token_specific(self) -> None:
        from services.airtable_cache import _token_fingerprint

        first = _token_fingerprint("pat-abc")

        assert first == _token_fingerprint("pat-abc")
        assert first != _token_fingerprint("pat-abd")
        assert len(first) == 12

    def test_it_does_not_contain_the_token(self) -> None:
        from services.airtable_cache import _token_fingerprint

        assert "pat-abc" not in _token_fingerprint("pat-abc")
