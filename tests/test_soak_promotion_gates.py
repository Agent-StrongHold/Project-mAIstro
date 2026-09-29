"""Regression tests for #860 soak-evidence promotion gates."""

from __future__ import annotations

import importlib.util
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "soak" / "run_soak.py"


@pytest.fixture(scope="module")
def soak() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_soak_promotion_gates", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _passing_evidence() -> dict[str, object]:
    return {
        "thresholds": {
            "checks": {
                "exactly_once_task_admission": True,
                "exactly_once_schedule_occurrence": True,
                "rate_limit_enforced": True,
                "lb_failover_bounded": {"ok": True},
                "replica_2_rejoined": True,
                "nonterminal_runs_after_settle": {"ok": True},
                "task_admission_availability": {"ok": True},
                "sustain_duration": {"ok": True},
                # Synthetic evaluator fixture, not evidence from this driver.
                "exact_rc_artifact": {"ok": True},
                "graceful_drain": {"required": True, "ok": True},
            }
        }
    }


def test_every_recorded_hard_gate_must_pass(soak: ModuleType) -> None:
    evidence = _passing_evidence()
    checks = evidence["thresholds"]["checks"]  # type: ignore[index]
    checks["lb_failover_bounded"] = {"ok": False}  # type: ignore[index]
    checks["nonterminal_runs_after_settle"] = {"ok": False}  # type: ignore[index]
    checks["task_admission_availability"] = {"ok": False}  # type: ignore[index]
    checks["sustain_duration"] = {"ok": False}  # type: ignore[index]
    checks["graceful_drain"] = {"required": True, "ok": False}  # type: ignore[index]

    assert soak.failed_promotion_checks(evidence) == [
        "lb_failover_bounded",
        "nonterminal_runs_after_settle",
        "task_admission_availability",
        "sustain_duration",
        "graceful_drain",
    ]


def test_abrupt_kill_does_not_claim_a_graceful_drain(soak: ModuleType) -> None:
    evidence = _passing_evidence()
    checks = evidence["thresholds"]["checks"]  # type: ignore[index]
    checks["graceful_drain"] = {"required": False, "ok": False}  # type: ignore[index]

    assert soak.failed_promotion_checks(evidence) == []


def test_missing_drain_record_cannot_pass(soak: ModuleType) -> None:
    """An evidence doc with no graceful_drain key at all must fail the gate.

    Round-4 verify finding: the gate used to inspect only dicts carrying a
    truthy `required` flag, so omitting the key entirely bypassed the drain
    check. The driver always writes the key; its absence means pre-probe or
    hand-edited evidence.
    """
    evidence = _passing_evidence()
    checks = evidence["thresholds"]["checks"]  # type: ignore[index]
    del checks["graceful_drain"]

    assert soak.failed_promotion_checks(evidence) == ["graceful_drain"]


def test_null_drain_record_cannot_pass(soak: ModuleType) -> None:
    """A null drain record is as absent as a missing key."""
    evidence = _passing_evidence()
    checks = evidence["thresholds"]["checks"]  # type: ignore[index]
    checks["graceful_drain"] = None  # type: ignore[assignment]

    assert soak.failed_promotion_checks(evidence) == ["graceful_drain"]


@pytest.mark.parametrize("artifact_record", ["missing", "null", "preflight"])
def test_four_hour_preflight_cannot_pass_cli(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, artifact_record: str
) -> None:
    """Even otherwise-passing four-hour evidence must fail without an RC artifact."""
    evidence = _passing_evidence()
    evidence["sustain_seconds"] = soak.PROMOTION_MIN_SUSTAIN_SECONDS
    checks = evidence["thresholds"]["checks"]
    if artifact_record == "missing":
        del checks["exact_rc_artifact"]
    elif artifact_record == "null":
        checks["exact_rc_artifact"] = None
    else:
        checks["exact_rc_artifact"] = soak.preflight_artifact_check()
        assert checks["exact_rc_artifact"]["topology"] == "host-uvicorn-preflight"

    async def completed_run(args: object) -> dict[str, object]:
        return evidence

    monkeypatch.setattr(soak, "main_async", completed_run)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--out-dir", str(tmp_path)])
    assert soak.failed_promotion_checks(evidence) == ["exact_rc_artifact"]
    with pytest.raises(SystemExit) as exc:
        soak.main()
    assert exc.value.code == 1


LB = "http://127.0.0.1:18080"
REPLICAS = ("http://127.0.0.1:18201", "http://127.0.0.1:18202")
PROBE_PATHS = [(origin, auth) for origin in (LB, *REPLICAS) for auth in (False, True)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("broken_path", "failure"),
    [(None, None)]
    + [(path, failure) for path in PROBE_PATHS for failure in ("disabled", "no-header", "offline")],
)
async def test_rate_probe_requires_every_replica_and_identity_class(
    soak: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    broken_path: tuple[str, bool] | None,
    failure: str | None,
) -> None:
    """A healthy LB/peer must not hide a failed direct probe (or vice versa)."""
    import httpx

    observed: dict[tuple[str, bool], int] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        path = (str(request.url).removesuffix("/tasks"), "authorization" in request.headers)
        assert request.method == "GET" and request.url.path == "/tasks"
        observed[path] = observed.get(path, 0) + 1
        if path == broken_path:
            if failure == "disabled":
                return httpx.Response(200)
            if failure == "offline":
                raise httpx.ConnectError("replica unavailable", request=request)
            return httpx.Response(429)  # rejection without the required Retry-After
        return httpx.Response(429, headers={"Retry-After": "60"})

    @asynccontextmanager
    async def client_for_probe(**kwargs: object):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            yield client

    monkeypatch.setattr(soak, "shared_client", client_for_probe)
    assert soak.REPLICA_ORIGINS == REPLICAS
    result = await soak.phase_rate_limit(
        LB, soak.REPLICA_ORIGINS, {"Authorization": "Bearer fixture"}, 17, 2
    )

    # 17 is intentionally not divisible by the driver's 16 concurrent lanes.
    assert observed == dict.fromkeys(PROBE_PATHS, 17)
    assert result["enforced_everywhere"] is (broken_path is None)
    assert set(result["direct_replicas"]) == set(REPLICAS)
    for origin, pair in result["direct_replicas"].items():
        for identity, probe in pair.items():
            assert probe["target"] == origin
            assert probe["authenticated"] is (identity == "authenticated")
            assert probe["requests"] == sum(probe["status_counts"].values()) == 17

    evidence = _passing_evidence()
    evidence["thresholds"]["checks"]["rate_limit_enforced"] = result["enforced_everywhere"]
    assert soak.failed_promotion_checks(evidence) == (
        [] if broken_path is None else ["rate_limit_enforced"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origins", [(), REPLICAS[:1], (REPLICAS[0], REPLICAS[0]), (LB, REPLICAS[0])]
)
async def test_rate_probe_rejects_incomplete_replica_topology(
    soak: ModuleType, origins: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError, match="two distinct direct replica origins"):
        await soak.phase_rate_limit(LB, origins, {}, 17, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("second_replica_limited", [True, False])
async def test_rate_probe_with_production_middleware(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, second_replica_limited: bool
) -> None:
    """Exercise real limiter instances; ASGI routing is not a production soak."""
    import httpx
    from fastapi import FastAPI

    from maistro.config.settings import get_settings
    from maistro_server.api.rate_limit import RateLimitMiddleware

    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_BURST", "0")
    monkeypatch.setenv("API_KEYS", '["soak:probe-secret"]')
    get_settings.cache_clear()

    def app(limited: bool) -> FastAPI:
        instance = FastAPI()

        @instance.get("/tasks")
        async def tasks() -> dict[str, str]:
            return {"status": "ok"}

        if limited:
            instance.add_middleware(RateLimitMiddleware)
        return instance

    transports = [
        httpx.ASGITransport(app=app(True)),
        httpx.ASGITransport(app=app(second_replica_limited)),
    ]
    lb_requests = 0

    async def route(request: httpx.Request) -> httpx.Response:
        nonlocal lb_requests
        if request.url.port == 18080:
            index = lb_requests % 2
            lb_requests += 1
        else:
            index = REPLICAS.index(str(request.url).removesuffix("/tasks"))
        return await transports[index].handle_async_request(request)

    @asynccontextmanager
    async def client_for_probe(**kwargs: object):
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            yield client

    monkeypatch.setattr(soak, "shared_client", client_for_probe)
    try:
        result = await soak.phase_rate_limit(
            LB, REPLICAS, {"Authorization": "Bearer probe-secret"}, 17, 2
        )
        # LB sees 429 even with replica 2 disabled: only the direct probes
        # distinguish that broken deployment from two healthy limiters.
        assert result["through_lb_authenticated"]["status_counts"]["429"] > 0
        assert result["through_lb_unauthenticated"]["status_counts"]["429"] > 0
        assert result["enforced_everywhere"] is second_replica_limited
        first = result["direct_replicas"][REPLICAS[0]]
        second = result["direct_replicas"][REPLICAS[1]]
        for identity in ("authenticated", "unauthenticated"):
            assert first[identity]["status_counts"] == {"429": 17}
            assert first[identity]["retry_after"] is not None
            expected_status = "429" if second_replica_limited else "200"
            assert second[identity]["status_counts"] == {expected_status: 17}
            assert (second[identity]["retry_after"] is not None) is second_replica_limited
    finally:
        get_settings.cache_clear()
        for transport in transports:
            await transport.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("authenticated", [False, True])
async def test_replica_selection_has_an_independent_production_allowance(
    monkeypatch: pytest.MonkeyPatch, authenticated: bool
) -> None:
    """H3 is local enforcement, not proof of a cluster-wide principal budget."""
    import httpx
    from fastapi import FastAPI

    from maistro.config.settings import get_settings
    from maistro_server.api.rate_limit import RateLimitMiddleware

    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_BURST", "0")
    monkeypatch.setenv("API_KEYS", '["soak:probe-secret"]')
    get_settings.cache_clear()

    def replica() -> FastAPI:
        app = FastAPI()

        @app.get("/tasks")
        async def tasks() -> dict[str, str]:
            return {"status": "ok"}

        app.add_middleware(RateLimitMiddleware)
        return app

    # Same connecting IP and same credential on both instances. Only the
    # middleware instance changes; no identity rotation or forged proxy header.
    headers = {"Authorization": "Bearer probe-secret"} if authenticated else {}
    try:
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=replica()), base_url=REPLICAS[0]
            ) as first,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=replica()), base_url=REPLICAS[1]
            ) as second,
        ):

            async def statuses(client: httpx.AsyncClient) -> list[int]:
                responses = [await client.get("/tasks", headers=headers) for _ in range(3)]
                assert responses[-1].headers.get("Retry-After") is not None
                return [response.status_code for response in responses]

            assert await statuses(first) == [200, 200, 429]
            # Replica 1 exhausted the identity's local allowance. Replica 2
            # still accepts two requests, falsifying the old shared-store claim.
            assert await statuses(second) == [200, 200, 429]
            assert (await first.get("/tasks", headers=headers)).status_code == 429
    finally:
        get_settings.cache_clear()
