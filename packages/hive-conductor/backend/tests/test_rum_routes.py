"""The RUM collector contract (#1420).

The SPA reporter (`frontend/src/lib/rum.ts`) batches perceived-load events
to `POST /v1/rum/events`; this suite pins the receiving side's behavior:

- fail-closed ingest: with `RUM_INGEST_ENABLED` unset (the default) a valid
  batch is acknowledged and DISCARDED — an enabled client cannot switch
  collection on, and nothing it sends is ever stored;
- the `hive.rum.v1` schema is enforced server-side as defense in depth:
  oversized batches, unknown schema versions, route templates carrying a
  query string, and request ids outside the `X-Request-ID` charset are all
  refused before the store sees them;
- an accepted event is projected onto the approved fields only — extra
  properties a (broken or hostile) client attached are not stored, so a
  secret-looking payload cannot ride into the operator's read-back;
- retention is bounded: the ring evicts oldest beyond `RUM_MAX_EVENTS` and
  the settings value is clamped, so the sink cannot be configured (or
  flooded) into unbounded memory;
- transport-failure outcomes (`status_class=0`, outcome `timeout` /
  `network_error`) store `request_id=None` — no server id is fabricated for
  a request that never got a response — while a response-carried
  `X-Request-ID` is stored verbatim, matching what `RequestIDMiddleware`
  stamps on responses and log lines (asserted here against a live response
  through the app, the same correlation the browser reporter relies on).
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

RUM_URL = "/v1/rum/events"


def _envelope(events: list[dict[str, Any]], *, build_id: str = "build-test-1") -> dict[str, Any]:
    return {
        "schema": "hive.rum.v1",
        "build_id": build_id,
        "session_id": "sess01aaaaaa",
        "events": events,
    }


def _web_vital(**overrides: Any) -> dict[str, Any]:
    event = {
        "type": "web_vital",
        "name": "LCP",
        "value_ms": 412.5,
        "route": "/dashboard",
        "ts": 1_700_000_000_000,
    }
    event.update(overrides)
    return event


def _api_event(**overrides: Any) -> dict[str, Any]:
    event = {
        "type": "api_request",
        "method": "GET",
        "route": "/v1/agents/*",
        "status_class": 2,
        "outcome": "ok",
        "duration_ms": 33.25,
        "request_id": "abc123def456",
        "ts": 1_700_000_000_500,
    }
    event.update(overrides)
    return event


@pytest.fixture()
def rum_store():
    """A clean process store per test; restored afterwards so other suites
    sharing this interpreter never see RUM rows (#414's lesson)."""
    from services.rum_store import get_store

    store = get_store()
    store.clear()
    yield store
    store.clear()


@pytest.fixture()
def ingest_enabled(monkeypatch: pytest.MonkeyPatch):
    """Flip the operator switch on for one test (the route reads it live)."""
    import routes.rum as rum_routes

    monkeypatch.setattr(rum_routes, "rum_ingest_enabled", lambda: True)


# --- the disabled default ---------------------------------------------------


def test_disabled_collector_discards_a_valid_batch(authed_client: Any, rum_store: Any) -> None:
    r = authed_client.post(RUM_URL, json=_envelope([_web_vital(), _api_event()]))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body == {"accepted": 0, "enabled": False}
    # Nothing reachable afterwards: the read-back and the summary are empty.
    listing = authed_client.get(RUM_URL).json()
    assert listing == {"events": [], "total": 0, "truncated": False}
    assert authed_client.get(f"{RUM_URL}/summary").json()["groups"] == []


def test_disabled_collector_still_refuses_a_malformed_envelope(
    authed_client: Any, rum_store: Any
) -> None:
    """Fail-closed means no path stores anything — including a payload that
    only fails validation while disabled. 422 is the honest answer."""
    r = authed_client.post(RUM_URL, json=_envelope([_web_vital(name="CLP")]))
    assert r.status_code == 422
    assert rum_store.list_events()["total"] == 0


# --- enabled ingest, read-back and grouping ---------------------------------


def test_enabled_collector_stores_and_serves_observations(
    authed_client: Any, rum_store: Any, ingest_enabled: None
) -> None:
    r = authed_client.post(RUM_URL, json=_envelope([_web_vital(), _api_event()]))
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 2, "enabled": True}

    listing = authed_client.get(RUM_URL).json()
    assert listing["truncated"] is False
    assert listing["total"] == 2
    by_type = {event["type"]: event for event in listing["events"]}
    vital = by_type["web_vital"]
    assert vital["name"] == "LCP"
    assert vital["value_ms"] == 412.5
    assert vital["route"] == "/dashboard"
    api = by_type["api_request"]
    assert api["outcome"] == "ok"
    assert api["status_class"] == 2
    assert api["duration_ms"] == 33.25
    assert api["request_id"] == "abc123def456"
    # The stored field set is exactly the approved one — no extra key a
    # client may have attached survived into the operator's read-back.
    assert set(vital) == {"type", "name", "value_ms", "route", "ts", "received_at"}
    assert set(api) == {
        "type",
        "method",
        "route",
        "status_class",
        "outcome",
        "duration_ms",
        "request_id",
        "ts",
        "received_at",
    }


def test_summary_groups_by_metric_route_and_outcome(
    authed_client: Any, rum_store: Any, ingest_enabled: None
) -> None:
    authed_client.post(
        RUM_URL,
        json=_envelope(
            [
                _web_vital(value_ms=100.0, route="/dashboard"),
                _web_vital(value_ms=300.0, route="/dashboard"),
                _api_event(outcome="http_error", status_class=5, duration_ms=900.0),
                _api_event(duration_ms=50.0),
            ]
        ),
    )
    summary = authed_client.get(f"{RUM_URL}/summary").json()
    assert summary["window_events"] == 4
    groups = {
        (g["type"], g["metric"], g["route"], g["outcome"] or "", g["status_class"]): g
        for g in summary["groups"]
    }
    vital = groups[("web_vital", "LCP", "/dashboard", "", 0)]
    assert vital["count"] == 2
    assert vital["min_ms"] == 100.0
    assert vital["p50_ms"] == 300.0
    assert vital["max_ms"] == 300.0
    errors = groups[("api_request", "GET", "/v1/agents/*", "http_error", 5)]
    assert errors["count"] == 1
    assert errors["p95_ms"] == 900.0
    ok = groups[("api_request", "GET", "/v1/agents/*", "ok", 2)]
    assert ok["count"] == 1 and ok["p50_ms"] == 50.0


# --- schema enforcement (server-side redaction, defense in depth) ------------


def test_oversized_batch_is_refused_before_the_store(
    authed_client: Any, rum_store: Any, ingest_enabled: None
) -> None:
    from routes.rum import MAX_BATCH_EVENTS

    flood = [_web_vital(ts=float(i)) for i in range(MAX_BATCH_EVENTS + 1)]
    r = authed_client.post(RUM_URL, json=_envelope(flood))
    assert r.status_code == 422
    assert rum_store.list_events()["total"] == 0


def test_route_template_carrying_a_query_string_is_refused(
    authed_client: Any, rum_store: Any, ingest_enabled: None
) -> None:
    r = authed_client.post(
        RUM_URL,
        json=_envelope([_web_vital(route="/dashboard?redirect=https://evil.example")]),
    )
    assert r.status_code == 422
    assert rum_store.list_events()["total"] == 0


def test_unknown_schema_version_is_refused(
    authed_client: Any, rum_store: Any, ingest_enabled: None
) -> None:
    batch = _envelope([_web_vital()])
    batch["schema"] = "hive.rum.v2"
    r = authed_client.post(RUM_URL, json=batch)
    assert r.status_code == 422
    assert rum_store.list_events()["total"] == 0


def test_extra_fields_are_not_stored_and_secrets_do_not_leak(
    authed_client: Any, rum_store: Any, ingest_enabled: None
) -> None:
    """A client that ignored the frontend redaction rules — attaching the raw
    URL (with a token in its query string), a response body and a credential —
    gets those fields silently dropped: only approved fields are ever read."""
    sneaky = {
        **_api_event(),
        "url": "/v1/agents/agent-77?api_token=supersecret-token",
        "response_body": {"detail": "boom", "stack": "secret-ish"},
        "password": "hunter2",
        "prompt": "the user's entire chat history",
    }
    r = authed_client.post(RUM_URL, json=_envelope([sneaky]))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1
    import json as jsonlib

    dump = jsonlib.dumps(authed_client.get(RUM_URL).json())
    for secret in ("supersecret-token", "hunter2", "the user's entire chat history", "agent-77"):
        assert secret not in dump
    assert "url" not in dump and "password" not in dump and "prompt" not in dump


def test_request_id_outside_the_server_charset_is_refused(
    authed_client: Any, rum_store: Any, ingest_enabled: None
) -> None:
    for bad in ("spaces are bad", "semi;colon", "", "x" * 129, "no!chars"):
        r = authed_client.post(RUM_URL, json=_envelope([_api_event(request_id=bad)]))
        assert r.status_code == 422, bad
    assert rum_store.list_events()["total"] == 0


# --- correlation with the existing X-Request-ID contract ---------------------


def test_response_request_id_is_storable_and_the_collector_response_carries_one(
    authed_client: Any, rum_store: Any, ingest_enabled: None
) -> None:
    """Round trip: a request through the app gets the middleware's
    X-Request-ID; a rum event carrying that exact id is stored verbatim."""
    probe = authed_client.get("/health")
    server_id = probe.headers.get("X-Request-ID")
    assert server_id, "every response carries the correlation id"
    r = authed_client.post(RUM_URL, json=_envelope([_api_event(request_id=server_id)]))
    assert r.status_code == 200, r.text
    # The collector's own response carries an id too — same middleware, so a
    # client-side event about the ingest itself can be correlated as well.
    assert r.headers.get("X-Request-ID")
    stored = authed_client.get(RUM_URL).json()["events"]
    assert len(stored) == 1
    assert stored[0]["request_id"] == server_id


def test_transport_failure_stores_no_fabricated_request_id(
    authed_client: Any, rum_store: Any, ingest_enabled: None
) -> None:
    r = authed_client.post(
        RUM_URL,
        json=_envelope(
            [
                _api_event(
                    status_class=0,
                    outcome="timeout",
                    request_id=None,
                    duration_ms=30_000.0,
                )
            ]
        ),
    )
    assert r.status_code == 200, r.text
    stored = authed_client.get(RUM_URL).json()["events"]
    assert stored[0]["status_class"] == 0
    assert stored[0]["outcome"] == "timeout"
    assert stored[0]["request_id"] is None


# --- retention bounds ---------------------------------------------------------


def test_ring_evicts_oldest_and_stays_bounded() -> None:
    from services.rum_store import RumStore

    store = RumStore(max_events=50)
    for i in range(60):
        accepted = store.ingest([_web_vital(ts=float(i))])
        assert accepted == 1
    listing = store.list_events(limit=200)
    # limit is clamped to the ring size: nothing is hidden, so not truncated.
    assert listing["truncated"] is False
    stamps = [event["ts"] for event in listing["events"]]
    assert stamps == [float(i) for i in range(10, 60)], "oldest evicted, order kept"
    # An operator asking for fewer than the ring holds sees the flag set.
    clipped = store.list_events(limit=10)
    assert clipped["truncated"] is True
    assert [event["ts"] for event in clipped["events"]] == [float(i) for i in range(50, 60)]


def test_max_events_setting_is_clamped_to_a_bounded_sink() -> None:
    from services.rum_store import MAX_MAX_EVENTS, MIN_MAX_EVENTS, RumStore

    assert RumStore(max_events=1).max_events == MIN_MAX_EVENTS
    assert RumStore(max_events=10**9).max_events == MAX_MAX_EVENTS


def test_batch_size_caps_match_the_frontend_contract() -> None:
    """The server cap and the client's MAX_BATCH_EVENTS are one number; this
    pins the two files together until a shared source exists."""
    import pathlib as pathlib_mod
    import re as re_mod

    backend_dir = pathlib_mod.Path(__file__).resolve().parents[1]
    frontend_dir = backend_dir.parent / "frontend"
    py = (backend_dir / "services" / "rum_store.py").read_text(encoding="utf-8")
    ts = (frontend_dir / "src" / "lib" / "rumSchema.ts").read_text(encoding="utf-8")
    py_cap = re_mod.search(
        r"MAX_BATCH_EVENTS = (\d+)", (backend_dir / "routes" / "rum.py").read_text(encoding="utf-8")
    )
    ts_cap = re_mod.search(r"MAX_BATCH_EVENTS = (\d+)", ts)
    assert py_cap and ts_cap
    assert py_cap.group(1) == ts_cap.group(1)
    # And the client schema version is the one the server accepts.
    ts_schema = re_mod.search(r'RUM_SCHEMA = "([^"]+)"', ts)
    py_schema = re_mod.search(r'RUM_SCHEMA = "([^"]+)"', py)
    assert ts_schema and py_schema
    assert ts_schema.group(1) == py_schema.group(1)
