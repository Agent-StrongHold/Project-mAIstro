"""Dashboard KPI envelopes (#380): measured values, or an explicit reason.

The old `/v1/dashboard/metrics` payload was hard-coded zeros (`runs_today: 0`,
`ttft_ms: 0`) plus a literal `9`-agent fallback, and `/v1/quotas/outcomes` was
a zeroed dict regardless of the world's state. These tests pin the contract
that replaced it: every KPI names its authoritative query, scope, window, unit
and freshness; zero / no_data / stale / unavailable / error are distinct
states; queries are scoped to the authenticated principal; and a displayed
number is traceable to the source the envelope names.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from services import chat_completion, dashboard_metrics
from services.dag_run_store import DagRun, DagRunStore

# --------------------------------------------------------------------------- #
# Isolation: the chat ring and agent roster are process-global.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _isolate_chat_metrics():
    saved = chat_completion._chat_metrics[:]
    chat_completion._chat_metrics.clear()
    yield
    chat_completion._chat_metrics[:] = saved


@pytest.fixture
def one_agent():
    import stores
    from models.schemas import Agent

    agent = Agent(
        id="kpi-test-agent",
        name="KPI Fixture",
        description="seeded for dashboard metrics",
        model="test-model",
        status="idle",
        created_at=datetime.now(UTC),
    )
    stores.agents[agent.id] = agent
    yield agent
    stores.agents.pop(agent.id, None)


@pytest.fixture
def fresh_run_store(monkeypatch: pytest.MonkeyPatch) -> DagRunStore:
    """A bounded in-memory run store behind the service's store seam."""
    store = DagRunStore()
    monkeypatch.setattr(dashboard_metrics, "_run_store", lambda: store)
    return store


def _seed_chat_metrics(user: str, *, latency_ms: float = 1500.0, age_s: float = 0.0) -> None:
    chat_completion._record_chat_metric(
        user_id=user, model="test-model", elapsed_ms=latency_ms, tokens_in=1000, tokens_out=500
    )
    if age_s:
        chat_completion._chat_metrics[-1]["ts"] = time.time() - age_s


def _seed_run(store: DagRunStore, user: str, *, started_at: float | None = None) -> DagRun:
    """Register a run the way `start_run` does, without the async lock.

    The store's lock binds to whichever event loop first awaits it, and these
    are sync tests; the ring insertion mirrors `start_run`'s own bookkeeping,
    including evicting the oldest run when the deque is at capacity.
    """
    from uuid import uuid4

    run = DagRun(
        id=f"run-{uuid4().hex[:8]}",
        started_at=started_at if started_at is not None else time.time(),
        user_id=user,
    )
    if store._order.maxlen is not None and len(store._order) >= store._order.maxlen:
        evicted = store._order.popleft()
        store._runs.pop(evicted, None)
    store._runs[run.id] = run
    store._order.append(run.id)
    return run


# --------------------------------------------------------------------------- #
# Envelope schema
# --------------------------------------------------------------------------- #


def test_every_kpi_names_query_scope_window_unit_and_freshness() -> None:
    kpis = dashboard_metrics.build_dashboard_metrics("kpi-prov-user")
    assert set(kpis) == {
        "active_agents",
        "runs_today",
        "avg_latency",
        "total_cost",
        "invocations",
        "ttft",
        "approval_rate",
    }
    for name, env in kpis.items():
        assert env["state"] in dashboard_metrics.STATES, name
        # The provenance fields are the point of #380: each is present and
        # says something.
        assert isinstance(env["query"], str) and env["query"], name
        assert isinstance(env["scope"], str) and env["scope"], name
        assert isinstance(env["window"], str) and env["window"], name
        assert isinstance(env["unit"], str) and env["unit"], name
        assert env["computed_at"], name
        # computed_at parses as ISO-8601 (the SPA renders it as a time).
        datetime.fromisoformat(env["computed_at"])


def test_envelope_builder_rejects_inconsistent_states() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError):
        dashboard_metrics.envelope(
            state="misleading", unit="x", query="q", scope="s", window="w", computed_at=now
        )
    with pytest.raises(ValueError):
        dashboard_metrics.envelope(
            state="ok", value=None, unit="x", query="q", scope="s", window="w", computed_at=now
        )
    with pytest.raises(ValueError):
        dashboard_metrics.envelope(
            state="no_data", value=0, unit="x", query="q", scope="s", window="w", computed_at=now
        )


# --------------------------------------------------------------------------- #
# Scoping and cardinality bounds
# --------------------------------------------------------------------------- #


def test_chat_kpis_are_scoped_to_the_requesting_principal() -> None:
    _seed_chat_metrics("user-a", latency_ms=2000.0)
    _seed_chat_metrics("user-b", latency_ms=8000.0, age_s=0)
    kpis = dashboard_metrics.build_dashboard_metrics("user-a")
    assert kpis["avg_latency"]["state"] == "ok"
    assert kpis["avg_latency"]["value"] == 2000.0
    assert kpis["avg_latency"]["scope"] == "user:user-a"
    assert kpis["invocations"]["value"] == 1
    assert kpis["total_cost"]["state"] == "ok"
    # No other account's spend leaks into this envelope.
    assert kpis["total_cost"]["value"] == round(500 * 0.000003 + 1000 * 0.000001, 4)


def test_runs_today_counts_only_this_principal(fresh_run_store: DagRunStore) -> None:
    _seed_run(fresh_run_store, "user-a")
    _seed_run(fresh_run_store, "user-b")
    kpis = dashboard_metrics.build_dashboard_metrics("user-a")
    assert kpis["runs_today"]["value"] == 1
    assert kpis["runs_today"]["scope"] == "user:user-a"
    assert kpis["runs_today"]["last_update"] is not None


def test_count_since_is_bounded_by_the_working_set() -> None:
    store = DagRunStore(max_runs=2)
    _seed_run(store, "u", started_at=time.time() - 10_000)
    _seed_run(store, "u", started_at=time.time() - 100)
    _seed_run(store, "u", started_at=time.time())
    stats = store.count_since(user_id="u", started_after=0.0)
    # The ring evicted the oldest; the count says what it is a count of.
    assert stats["count"] == 2
    assert stats["bound"] == 2
    assert stats["is_durable"] is False
    assert stats["last_started_at"] == pytest.approx(time.time(), abs=5)


def test_count_since_filters_user_and_cutoff() -> None:
    store = DagRunStore()
    _seed_run(store, "u", started_at=1_000.0)
    _seed_run(store, "u", started_at=time.time())
    _seed_run(store, "other", started_at=time.time())
    assert store.count_since(user_id="u", started_after=time.time() - 60)["count"] == 1
    assert store.count_since(user_id="u", started_after=0.0)["count"] == 2


# --------------------------------------------------------------------------- #
# zero vs no_data vs stale
# --------------------------------------------------------------------------- #


def test_roster_count_is_measured_with_last_update(one_agent) -> None:
    kpis = dashboard_metrics.build_dashboard_metrics("anyone")
    env = kpis["active_agents"]
    assert env["state"] == "ok"
    assert env["value"] >= 1
    assert env["last_update"] is not None


def test_chat_kpis_with_no_observations_are_no_data_not_zero() -> None:
    kpis = dashboard_metrics.build_dashboard_metrics("never-invoked")
    for name in ("avg_latency", "total_cost", "invocations"):
        assert kpis[name]["state"] == "no_data", name
        assert kpis[name]["value"] is None, name
        assert kpis[name]["reason"], name


def test_runs_today_is_a_measured_zero_on_a_full_coverage_store(
    fresh_run_store: DagRunStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Durable store, booted before local midnight: zero runs today is measured.
    monkeypatch.setattr(
        "services.dag_run_store._PROCESS_BOOT_TS",
        time.time() - 3 * 24 * 3600,
    )
    fresh_run_store._records = object()  # durable: history predates the boot
    kpis = dashboard_metrics.build_dashboard_metrics("quiet-user")
    assert kpis["runs_today"]["state"] == "ok"
    assert kpis["runs_today"]["value"] == 0


def test_stale_when_newest_observation_predates_the_window() -> None:
    _seed_chat_metrics("gone-user", latency_ms=1200.0, age_s=2 * 24 * 3600)
    kpis = dashboard_metrics.build_dashboard_metrics("gone-user")
    assert kpis["avg_latency"]["state"] == "stale"
    assert kpis["avg_latency"]["value"] == 1200.0
    assert "old" in kpis["avg_latency"]["reason"]
    assert kpis["avg_latency"]["last_update"] is not None


def test_runs_today_is_stale_after_an_in_memory_restart(
    fresh_run_store: DagRunStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Non-durable history, booted after local midnight: today's count is
    # partial, and the envelope says so instead of looking healthy.
    monkeypatch.setattr("services.dag_run_store._PROCESS_BOOT_TS", time.time())
    kpis = dashboard_metrics.build_dashboard_metrics("quiet-user")
    assert kpis["runs_today"]["state"] == "stale"
    assert kpis["runs_today"]["value"] == 0
    assert "booted" in kpis["runs_today"]["reason"]


def test_runs_today_names_the_floor_when_the_ring_is_full(
    fresh_run_store: DagRunStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("services.dag_run_store._PROCESS_BOOT_TS", time.time() - 3 * 24 * 3600)
    small = DagRunStore(max_runs=2)
    small._records = object()  # durable, post-construction: coverage predates the boot
    monkeypatch.setattr(dashboard_metrics, "_run_store", lambda: small)
    _seed_run(small, "busy-user")
    _seed_run(small, "busy-user")
    stats = small.count_since(user_id="busy-user", started_after=0.0)
    assert stats["count"] == stats["bound"]
    kpis = dashboard_metrics.build_dashboard_metrics("busy-user")
    assert kpis["runs_today"]["state"] == "stale"
    assert "floor" in kpis["runs_today"]["reason"]


# --------------------------------------------------------------------------- #
# unavailable and error say why
# --------------------------------------------------------------------------- #


def test_unsupported_kpis_are_explicitly_unavailable() -> None:
    kpis = dashboard_metrics.build_dashboard_metrics("anyone")
    for name in ("ttft", "approval_rate"):
        env = kpis[name]
        assert env["state"] == "unavailable", name
        assert env["value"] is None, name
        assert env["reason"], name
        assert "none" in env["query"].lower(), name


def test_one_failing_source_is_an_error_envelope_not_a_blank_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(user_id: str | None = None, window_seconds: float | None = None) -> dict:
        raise RuntimeError("ring exploded")

    monkeypatch.setattr(chat_completion, "get_chat_metrics_summary", boom)
    kpis = dashboard_metrics.build_dashboard_metrics("anyone")
    assert kpis["avg_latency"]["state"] == "error"
    assert "ring exploded" in kpis["avg_latency"]["reason"]
    # The blast stops at the broken source.
    assert kpis["active_agents"]["state"] in ("ok", "no_data", "stale")
    assert kpis["ttft"]["state"] == "unavailable"


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #


def test_metrics_route_requires_a_principal() -> None:
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    r = client.get("/v1/dashboard/metrics")
    assert r.status_code == 401


def test_metrics_route_serves_envelopes(admin_client) -> None:
    r = admin_client.get("/v1/dashboard/metrics")
    assert r.status_code == 200
    kpis = r.json()
    assert "active_agents" in kpis
    for env in kpis.values():
        assert env["state"] in dashboard_metrics.STATES
        assert env["query"] and env["scope"] and env["window"] and env["unit"]


def test_widget_metrics_route_happy_path(authed_client) -> None:
    _seed_chat_metrics("user", latency_ms=2500.0)
    r = authed_client.get("/v1/widgets/metrics", params={"metric": "latency"})
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "ok"
    assert data["value"] == 2500.0
    assert data["unit"] == "ms"
    assert data["query"] and data["scope"] == "user:user"
    assert data["computed_at"]


def test_widget_metrics_route_no_data_is_not_zero(authed_client) -> None:
    chat_completion._chat_metrics.clear()
    r = authed_client.get("/v1/widgets/metrics", params={"metric": "latency"})
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "no_data"
    assert data["value"] is None


def test_widget_metrics_route_tokens_aggregates_both_directions(authed_client) -> None:
    _seed_chat_metrics("user")
    r = authed_client.get("/v1/widgets/metrics", params={"metric": "tokens"})
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "ok"
    assert data["value"] == 1500
    assert data["unit"] == "tokens"


def test_widget_metrics_route_has_no_errors_metric(authed_client) -> None:
    """`errors` was a hard-coded 0 keyed off a summary field nobody wrote."""
    r = authed_client.get("/v1/widgets/metrics", params={"metric": "errors"})
    assert r.status_code == 400
    assert "errors" in r.json()["detail"]


def test_widget_metrics_route_rejects_unknown_metrics(authed_client) -> None:
    r = authed_client.get("/v1/widgets/metrics", params={"metric": "vibes"})
    assert r.status_code == 400
