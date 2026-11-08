"""Regression tests for #860 soak-evidence promotion gates."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import select
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

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


@pytest.mark.parametrize(
    ("gate", "record"),
    [
        ("exact_rc_artifact", {"ok": "false"}),
        ("exact_rc_artifact", {"ok": "true"}),
        ("exact_rc_artifact", {"ok": 1}),
        ("exact_rc_artifact", {"ok": [True]}),
        ("graceful_drain", {}),
        ("graceful_drain", {"ok": True}),
        ("graceful_drain", {"required": None, "ok": True}),
        ("graceful_drain", {"required": "false", "ok": True}),
        ("graceful_drain", {"required": 0, "ok": True}),
        ("graceful_drain", {"required": 1, "ok": True}),
        ("graceful_drain", {"required": True, "ok": "false"}),
        ("graceful_drain", {"required": True, "ok": 1}),
    ],
)
def test_malformed_gate_records_cannot_pass_cli(
    soak: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    gate: str,
    record: dict[str, object],
) -> None:
    """JSON truthiness is not an observed pass or an explicit drain exemption."""
    evidence = _passing_evidence()
    evidence["thresholds"]["checks"][gate] = record
    # Exercise the JSON evidence shape, evaluator, and actual CLI exit path.
    evidence = json.loads(json.dumps(evidence))

    async def completed_run(args: object) -> dict[str, object]:
        return evidence

    monkeypatch.setattr(soak, "main_async", completed_run)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--out-dir", str(tmp_path)])
    assert soak.failed_promotion_checks(evidence) == [gate]
    with pytest.raises(SystemExit) as exc:
        soak.main()
    assert exc.value.code == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("receipts", "expected"),
    [
        pytest.param([(409, {})] * 12, False, id="all-conflicts"),
        pytest.param([], False, id="empty-probe"),
        pytest.param([(202, {"run_id": "run-a"})], False, id="not-concurrent"),
        pytest.param([(202, {})] * 2, False, id="missing-identities"),
        pytest.param([(202, {"run_id": None})] * 2, False, id="null-identities"),
        pytest.param([(202, {"run_id": " "})] * 2, False, id="blank-identities"),
        pytest.param([(202, {"run_id": ["run-a"]})] * 2, False, id="invalid-identities"),
        pytest.param([(202, {"run_id": "run-a"}), (202, {})], False, id="one-invalid-receipt"),
        pytest.param(
            [(202, {"run_id": "run-a"}), (200, {"run_id": "run-b"})],
            False,
            id="duplicate-hidden-in-replay",
        ),
        pytest.param([(202, {"run_id": "run-a"})] * 12, True, id="one-admission"),
        pytest.param(
            [(202, {"run_id": "run-a"}), (200, {"run_id": "run-a"}), (409, {})],
            True,
            id="admission-replay-and-conflict",
        ),
        pytest.param([(202, {"run_id": "run-a"}), (503, {})], False, id="partial-delivery"),
    ],
)
async def test_task_admission_probe_requires_observed_canonical_identity(
    soak: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    receipts: list[tuple[int, dict[str, object]]],
    expected: bool,
) -> None:
    """Exercise the HTTP probe, not a hand-authored summary's boolean gate."""
    import httpx

    pending = iter(receipts)
    keys: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/tasks"
        keys.append(request.headers["Idempotency-Key"])
        status, body = next(pending)
        return httpx.Response(status, json=body)

    @asynccontextmanager
    async def client_for_probe(**kwargs: object):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            yield client

    monkeypatch.setattr(soak, "shared_client", client_for_probe)
    result = await soak.phase_exactly_once_tasks(LB, {}, len(receipts))
    assert len(keys) == len(receipts)
    assert len(set(keys)) == (1 if receipts else 0)
    assert result["statuses"] == [status for status, _ in receipts]
    assert result["ok"] is expected
    assert (result["cause"] == "ok") is expected
    if expected:
        assert result["distinct_run_ids"] == ["run-a"]
    evidence = _passing_evidence()
    evidence["thresholds"]["checks"]["exactly_once_task_admission"] = result["ok"]
    assert soak.failed_promotion_checks(evidence) == (
        [] if expected else ["exactly_once_task_admission"]
    )


@pytest.mark.skipif(sys.platform != "linux", reason="soak sampler requires Linux /proc")
@pytest.mark.asyncio
async def test_sampler_observes_uv_child_memory_and_descriptors(soak: ModuleType) -> None:
    """Real uv wrapper: resource growth in its child must reach the metrics row."""
    code = """
import json, os, sys
print(json.dumps({'pid': os.getpid()}), flush=True)
sys.stdin.read(1)
heap = bytearray(32 * 1024 * 1024)
files = [open('/dev/null') for _ in range(16)]
print('grown', flush=True)
sys.stdin.read(1)
"""
    proc = subprocess.Popen(
        ["uv", "run", "--no-sync", "python", "-u", "-c", code],
        cwd=SCRIPT.parents[2],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        assert proc.stdout is not None and proc.stdin is not None
        assert select.select([proc.stdout], [], [], 30)[0], "child startup timed out"
        child_pid = json.loads(proc.stdout.readline())["pid"]
        assert child_pid != proc.pid  # reproduce the actual wrapper topology
        pool = SimpleNamespace(fetchval=AsyncMock(return_value=0))
        before = (await soak.sample_once({"replica_1": proc}, pool))["replica_1"]
        proc.stdin.write("g")
        proc.stdin.flush()
        assert select.select([proc.stdout], [], [], 30)[0], "child allocation timed out"
        assert proc.stdout.readline().strip() == "grown"
        after = (await soak.sample_once({"replica_1": proc}, pool))["replica_1"]
        assert after["rss_kb"] - before["rss_kb"] >= 30 * 1024
        assert after["fds"] - before["fds"] >= 16
        assert after["process_count"] == 2
        assert {p["pid"] for p in after["processes"]} == {proc.pid, child_pid}
        assert after["complete"] is True
    finally:
        try:
            proc.communicate(input="q", timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate(timeout=10)


@pytest.mark.parametrize("failure", [None, "unreadable", "missing-rss", "empty"])
def test_process_group_samples_do_not_hide_missing_measurements(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    monkeypatch.setattr(soak.os, "listdir", lambda path: ["10", "11", "99", "self"])
    monkeypatch.setattr(
        soak.os, "getpgid", lambda pid: 99 if pid == 99 or failure == "empty" else 10
    )

    def stats(pid: int) -> dict[str, object] | None:
        assert pid != 99, "must not sample another replica's group"
        if pid == 11 and failure == "unreadable":
            return None
        return {"pid": pid, "rss_kb": None if failure == "missing-rss" else 100, "fds": 3}

    monkeypatch.setattr(soak, "proc_stats", stats)
    result = soak.process_group_stats(10)
    assert result["pgid"] == 10
    assert result["complete"] is (failure is None)
    if failure is None:
        assert result["process_count"] == 2
        assert result["rss_kb"] == 200
        assert result["fds"] == 6
    else:
        assert result["rss_kb"] is None
        assert result["fds"] is None
    if failure == "empty":
        assert result["process_count"] == 0
    if failure == "unreadable":
        assert result["unmeasured_pids"] == [11]


@pytest.mark.asyncio
async def test_sampler_keeps_observing_group_after_wrapper_exit(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = {"pgid": 10, "process_count": 1, "rss_kb": 100, "fds": 5}

    def group(pgid: int) -> dict[str, object]:
        assert pgid == 10
        return row

    monkeypatch.setattr(soak, "process_group_stats", group)
    proc = SimpleNamespace(pid=10, poll=lambda: 0)
    pool = SimpleNamespace(fetchval=AsyncMock(return_value=0))
    result = await soak.sample_once({"replica_1": proc}, pool)
    assert result["replica_1"]["process_count"] == 1
    assert result["replica_1"]["rss_kb"] == 100
    assert result["replica_1"]["wrapper_alive"] is False


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("responses", "kill_count", "expected"),
    [
        pytest.param([], 0, False, id="no-submissions"),
        pytest.param([(429, "60")] * 2, 0, False, id="all-backpressure"),
        pytest.param([(202, None), (429, None)], 0, False, id="missing-retry-after"),
        pytest.param([(202, None), (429, " ")], 0, False, id="blank-retry-after"),
        pytest.param([(202, None), (429, "60")], 0, True, id="accepted-and-backpressure"),
        pytest.param([(202, None), (500, None)], 0, False, id="server-error"),
        pytest.param([(202, None), (429, "60")], 1, False, id="accepted-only-during-kill"),
        pytest.param(
            [(429, "60"), (202, None), (429, None)],
            1,
            False,
            id="kill-window-header-cannot-cover-outside-rejection",
        ),
        pytest.param(
            [(429, None), (202, None), (429, "60")],
            1,
            True,
            id="kill-window-rejection-excluded",
        ),
    ],
)
async def test_sustained_admission_requires_work_and_retryable_backpressure(
    soak: ModuleType,
    responses: list[tuple[int, str | None]],
    kill_count: int,
    expected: bool,
) -> None:
    """Feed HTTP responses through the real worker/accounting/evaluator path."""
    import httpx

    pending = iter(responses)

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/tasks"
        status, retry_after = next(pending)
        return httpx.Response(
            status,
            headers={} if retry_after is None else {"Retry-After": retry_after},
            json={"run_id": "run-observed"} if status == 202 else {},
        )

    stats = soak.LoadStats()
    before = await stats.snapshot()
    after = before
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        for index in range(len(responses)):
            await soak.one_request_with(client, LB, {}, "task_submit", stats, index)
            if index + 1 == kill_count:
                after = await stats.snapshot()
    kill_record = {
        "window_task_status_counts": soak._counter_delta(
            after["kind_status_codes"].get("task_submit", {}),
            before["kind_status_codes"].get("task_submit", {}),
        ),
        "window_retryable_counts": soak._counter_delta(
            after.get("retryable_counts", {}), before.get("retryable_counts", {})
        ),
    }
    check = soak.task_admission_check(stats, kill_record)
    assert check["submissions_outside_kill_window"] == len(responses) - kill_count
    assert check["ok"] is expected
    evidence = _passing_evidence()
    evidence["thresholds"]["checks"]["task_admission_availability"] = check
    assert soak.failed_promotion_checks(evidence) == (
        [] if expected else ["task_admission_availability"]
    )


@pytest.mark.asyncio
async def test_receipt_load_reads_admitted_tasks_through_production_router(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read an admitted receipt from a peer via the shared durable tier.

    Both queues use one canonical admission spine. This is an ASGI contract
    probe, not a production multi-replica soak or a second execution authority.
    """
    import httpx
    from fastapi import FastAPI

    from maistro.config.settings import Settings, get_settings
    from maistro.runs.wiring import wire_execution_spine
    from maistro.tasks.queue import TaskQueue, get_task_queue
    from maistro_server.api.tasks import router

    monkeypatch.setenv("WORKSPACE_BASE", "/tmp/maistro-workspace")
    _, _, admitter, _, _, _ = await wire_execution_spine(None, workspace_id="soak-test")
    headers = {"Authorization": "Bearer receipt-secret"}
    stats = soak.LoadStats()

    def replica() -> FastAPI:
        queue = TaskQueue(admitter=admitter)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_task_queue] = lambda: queue
        app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["soak:receipt-secret"])
        return app

    for replica_index in range(2):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=replica())) as client:
            if replica_index == 0:
                await soak.one_request_with(client, LB, headers, "task_submit", stats, 1)
                assert stats.kind_status_codes["task_submit"] == {202: 1}
            # Use the same load state when the LB sends a read to the peer;
            # the production route resolves the receipt from shared Run truth.
            await soak.one_request_with(client, LB, headers, "run_get", stats, 2)
            if replica_index == 0:
                assert stats.kind_status_codes["run_get"] == {200: 1}
    assert stats.kind_status_codes["run_get"] == {200: 2}
    # main_async publishes this snapshot's kind_status_codes in thresholds;
    # preserve response classes through JSON serialization, not just totals.
    counters = json.loads(json.dumps(await stats.snapshot()))
    assert counters["kind_status_codes"]["run_get"] == {"200": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("task_id", [None, "", " ", ["task-a"], 42])
async def test_receipt_load_does_not_invent_ids_from_invalid_admission(
    soak: ModuleType, task_id: object
) -> None:
    import httpx

    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(202, json={"run_id": "run-a", "task_id": task_id})

    stats = soak.LoadStats()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await soak.one_request_with(client, LB, {}, "task_submit", stats, 1)
        await soak.one_request_with(client, LB, {}, "run_get", stats, 2)
    assert requests == ["POST"]
    assert stats.kind_status_codes["run_get"] == {0: 1}
    assert "run_get" not in stats.latencies


@pytest.mark.asyncio
async def test_receipt_load_bounds_observed_ids_and_preserves_read_failures(
    soak: ModuleType,
) -> None:
    import httpx

    observed: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request.url.path)
        return httpx.Response(503)

    stats = soak.LoadStats()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await soak.one_request_with(client, LB, {}, "run_get", stats, 0)
        assert observed == []  # no admission yet: explicitly unseeded, not a fake read
        for index in range(501):
            await stats.record("task_submit", 202, 0, "run-a", task_id=f"task-{index}")
        assert len(stats.task_ids) == 500
        await soak.one_request_with(client, LB, {}, "run_get", stats, 0)
        await soak.one_request_with(client, LB, {}, "run_get", stats, 499)
    assert observed == ["/tasks/task-1", "/tasks/task-500"]
    assert stats.kind_status_codes["run_get"] == {0: 1, 503: 2}
    assert len(stats.latencies["run_get"]) == 2
    counters = json.loads(json.dumps(await stats.snapshot()))
    assert counters["kind_status_codes"]["run_get"] == {"0": 1, "503": 2}


# ─── boot hygiene (2026-10-06 incident chain) ────────────────────────────────


def test_resolve_out_dir_gives_docker_an_absolute_bind_source(soak: ModuleType) -> None:
    # `docker run -v` rejects relative bind sources; the driver must resolve
    # --out-dir before the LB mount is attempted, not after replicas are up.
    relative = soak.resolve_out_dir("docs/testing/soak/evidence")
    assert Path(relative).is_absolute()
    assert relative == str((Path.cwd() / "docs" / "testing" / "soak" / "evidence").resolve())
    assert soak.resolve_out_dir("/tmp/soak-scratch") == "/tmp/soak-scratch"


def test_boot_refuses_occupied_replica_ports(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A crashed earlier run's replicas must never be silently adopted as this
    # run's samples (observed: "boot completed in 0.0s" against orphans, then
    # a --fresh-db reset landed under the orphans' live pools).
    monkeypatch.setattr(soak, "port_closed", lambda port, timeout=1.0: port != 18202)
    with pytest.raises(RuntimeError, match=r"orphaned servers still accept.*18202"):
        soak.ensure_replica_ports_free()
    monkeypatch.setattr(soak, "port_closed", lambda port, timeout=1.0: True)
    soak.ensure_replica_ports_free()


def test_boot_failure_cleanup_kills_groups_and_reports_survivors(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[object] = []
    monkeypatch.setattr(soak, "kill_replica", lambda proc: killed.append(proc))
    monkeypatch.setattr(soak, "port_closed", lambda port, timeout=1.0: port != 18201)
    procs = {"replica_1": object(), "replica_2": object()}
    assert soak.kill_replicas_and_collect_orphans(procs, (18201, 18202)) == [18201]
    assert len(killed) == 2


async def test_lb_boot_failure_kills_both_replicas_instead_of_leaking_them(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2026-10-06: a rejected nginx bind mount raised while both replicas kept
    serving; the retry adopted the orphans ("boot completed in 0.0s") and its
    evidence measured stale state. The LB-failure path must end every replica
    it started before raising — the same doctrine as the replica path."""
    monkeypatch.setattr(soak, "ensure_postgres", lambda: None)
    monkeypatch.setattr(soak, "ensure_replica_ports_free", lambda: None)
    monkeypatch.setattr(soak, "reset_db_schema", lambda: None)
    monkeypatch.setattr(soak, "run_migrations", lambda: None)
    monkeypatch.setattr(soak, "replica_env", lambda *args, **kwargs: {})
    procs: dict[str, object] = {}

    def fake_start_replica(port: int, out_dir: Path, env: dict[str, str]) -> object:
        procs[f"replica_{port}"] = object()
        return procs[f"replica_{port}"]

    async def fake_wait_ready(name: str, url: str, proc: object, timeout: int) -> bool:
        return name != "lb"  # replicas become ready; the LB never does

    killed: list[object] = []
    monkeypatch.setattr(soak, "start_replica", fake_start_replica)
    monkeypatch.setattr(soak, "wait_ready", fake_wait_ready)
    monkeypatch.setattr(soak, "start_nginx", lambda out_dir: None)
    monkeypatch.setattr(soak, "kill_replica", lambda proc: killed.append(proc))
    monkeypatch.setattr(soak, "port_closed", lambda port, timeout=1.0: True)

    args = SimpleNamespace(
        fresh_db=True,
        pool_size=1,
        max_overflow=1,
        rate_limit_per_minute=3000,
        rate_limit_burst=100,
        out_dir="/tmp/soak-boot-hygiene-test",
    )
    with pytest.raises(RuntimeError, match="LB did not become ready"):
        await soak.boot_stack(args)
    assert len(killed) == 2


# ─── driver internals: infrastructure seams (2026-10-25 coverage repair) ─────
#
# The diff-coverage gate scores every executable line of a new file, and the
# boot/teardown/orchestration paths below had no tests: bugs there corrupt soak
# evidence silently (unbounded docker calls, leaked orphans, mis-hashed config
# identity). Each test pins one operational doctrine at its seam.


def test_sh_captures_child_output(soak: ModuleType) -> None:
    result = soak.sh([sys.executable, "-c", "print('sentinel-ok')"])
    assert result.returncode == 0
    assert result.stdout.strip() == "sentinel-ok"


def test_sha256_text_matches_the_digest_contract(soak: ModuleType) -> None:
    import hashlib

    assert soak.sha256_text("soak") == hashlib.sha256(b"soak").hexdigest()


def test_soak_registers_only_its_own_loopback_origins(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered: list[str] = []
    monkeypatch.setattr(
        soak, "configure_outbound_policy", lambda *origins: registered.extend(origins)
    )
    soak.allow_soak_origins()
    assert registered == [f"http://127.0.0.1:{soak.LB_PORT}", *soak.REPLICA_ORIGINS]


def test_pg_available_reads_pg_isready_exit_status(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def ready(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        assert cmd[:3] == ["docker", "exec", soak.PG_CONTAINER]
        return subprocess.CompletedProcess(cmd, 0, "accepting\n", "")

    monkeypatch.setattr(soak, "sh", ready)
    assert soak.pg_available() is True
    monkeypatch.setattr(
        soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "down")
    )
    assert soak.pg_available() is False


def test_pg_sql_returns_output_or_an_error_sentinel(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "  5 \n", "")
    )
    assert soak.pg_sql("SELECT 5") == "5"
    monkeypatch.setattr(
        soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "no container")
    )
    assert soak.pg_sql("SELECT 5").startswith("__error__ no container")


def test_pg_image_digest_prefers_the_registry_digest(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        soak,
        "sh",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "pgvector@sha256:abc\n", ""),
    )
    assert soak.pg_image_digest() == "pgvector@sha256:abc"
    # An empty inspect output must not present the bare tag as a digest identity.
    monkeypatch.setattr(soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "\n", ""))
    assert soak.pg_image_digest() == soak.PG_IMAGE


def test_reset_db_schema_fails_loudly(soak: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "DROP\n", "")
    )
    soak.reset_db_schema()
    monkeypatch.setattr(
        soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "locked")
    )
    with pytest.raises(RuntimeError, match="soak schema reset failed"):
        soak.reset_db_schema()


def test_ensure_postgres_reuses_a_ready_container(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker_calls: list[list[str]] = []

    def spy(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        docker_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(soak, "pg_available", lambda: True)
    monkeypatch.setattr(soak, "sh", spy)
    soak.ensure_postgres()
    assert docker_calls == []


def test_ensure_postgres_boots_waits_and_records_the_topology(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness = iter([False, True])
    monkeypatch.setattr(soak, "pg_available", lambda: next(readiness))
    cmds: list[list[str]] = []

    def spy(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "id\n", "")

    monkeypatch.setattr(soak, "sh", spy)
    sleeps: list[float] = []
    monkeypatch.setattr(soak.time, "sleep", lambda s: sleeps.append(s))
    soak.ensure_postgres()
    assert any(cmd[:2] == ["docker", "rm"] for cmd in cmds)
    run_cmd = next(cmd for cmd in cmds if cmd[:2] == ["docker", "run"])
    assert soak.PG_IMAGE in run_cmd
    assert f"127.0.0.1:{soak.PG_HOST_PORT}:5432" in run_cmd
    # Ready on the first post-run poll: no wait cycles were needed.
    assert sleeps == []


def test_ensure_postgres_docker_failure_raises(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(soak, "pg_available", lambda: False)
    monkeypatch.setattr(
        soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "denied")
    )
    with pytest.raises(RuntimeError, match="docker run postgres failed"):
        soak.ensure_postgres()


def test_ensure_postgres_never_ready_times_out(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(soak, "pg_available", lambda: False)
    monkeypatch.setattr(
        soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "id\n", "")
    )
    clock = iter([0.0, 1.0, 200.0])
    monkeypatch.setattr(soak.time, "monotonic", lambda: next(clock, 200.0))
    monkeypatch.setattr(soak.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="did not become ready in 90s"):
        soak.ensure_postgres()


def test_run_migrations_names_the_workspace_member_and_fails_loudly(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def spy(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(soak, "sh", spy)
    soak.run_migrations()
    cmd, kw = calls[0]
    # The root workspace does not install maistro-server; a bare `uv run` made
    # this harness die on ModuleNotFoundError from whatever the local venv had.
    assert cmd[:4] == ["uv", "run", "--package", "maistro-server"]
    assert kw["cwd"] == soak.REPO and kw["timeout"] == 300
    assert str(kw["env"]["DATABASE_URL"]).startswith(
        f"postgresql+asyncpg://maistro:soak@127.0.0.1:{soak.PG_HOST_PORT}"
    )

    monkeypatch.setattr(
        soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom")
    )
    with pytest.raises(RuntimeError, match="migrations failed"):
        soak.run_migrations()


def test_replica_env_wires_the_documented_soak_contract(soak: ModuleType) -> None:
    env = soak.replica_env(18201, pool_size=2, max_overflow=3, rate_per_min=3000, burst=100)
    assert env["DATABASE_URL"] == (
        f"postgresql+asyncpg://maistro:soak@127.0.0.1:{soak.PG_HOST_PORT}/maistro"
    )
    assert json.loads(env["API_KEYS"]) == [soak.SOAK_API_KEY]
    assert env["REQUIRE_AUTH"] == "true"
    assert env["TASK_DELEGATION_KEY"] == soak.SOAK_DELEGATION_KEY
    assert env["ROUTER_API_KEY"] == soak.SOAK_ROUTER_KEY
    assert env["DB_POOL_SIZE"] == "2" and env["DB_MAX_OVERFLOW"] == "3"
    assert env["RATE_LIMIT_PER_MINUTE"] == "3000" and env["RATE_LIMIT_BURST"] == "100"
    # The raised limiter needs the documented escape hatch, and the config
    # identity records which replica a process served.
    assert env["ALLOW_UNSAFE_RESOURCE_OVERRIDES"] == "true"
    assert env["MAISTRO_SOAK_REPLICA"] == "replica-18201"
    assert env["PATH"] == os.environ.get("PATH")  # inherited, not a fresh env


def test_kill_replica_kills_the_session_leader_group(soak: ModuleType) -> None:
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        assert os.getpgid(proc.pid) == proc.pid  # reproduce the wrapper topology
        soak.kill_replica(proc)
        deadline = time.monotonic() + 5
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)


def test_kill_replica_tolerates_an_already_dead_group(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def gone(pid: int) -> int:
        raise ProcessLookupError()

    monkeypatch.setattr(soak.os, "getpgid", gone)
    soak.kill_replica(SimpleNamespace(pid=12345))  # must not raise


def test_port_closed_reads_the_connect_result(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The boolean comes from connect_ex, whatever the host network stack does.

    A real loopback bind is not an oracle here: WSL mirrored networking can
    accept connects on ports nothing listens on, so the contract under test is
    the mapping from connect_ex's return code to the boolean.
    """
    import socket

    codes = iter([0, 111])

    class FakeSocket:
        def settimeout(self, timeout: float) -> None:
            assert timeout == 1.0

        def connect_ex(self, address: tuple[str, int]) -> int:
            assert address == ("127.0.0.1", 4242)
            return next(codes)

        def __enter__(self) -> FakeSocket:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(socket, "socket", lambda *a, **kw: FakeSocket())
    assert soak.port_closed(4242) is False  # connect succeeded: something serves
    assert soak.port_closed(4242) is True  # ECONNREFUSED: nothing serves


def test_proc_stats_missing_process_measures_nothing(soak: ModuleType) -> None:
    assert soak.proc_stats(2**24) is None


def test_process_group_stats_records_unclassifiable_pids(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(soak.os, "listdir", lambda path: ["10"])

    def pgid(pid: int) -> int:
        raise PermissionError()

    monkeypatch.setattr(soak.os, "getpgid", pgid)
    result = soak.process_group_stats(10)
    assert result["unclassified_pids"] == [10]
    assert result["complete"] is False
    assert result["process_count"] == 0  # permission-blocked pids are not measurements
    assert result["rss_kb"] is None


@pytest.mark.asyncio
async def test_sampler_degrades_to_the_docker_probe_when_the_pool_dies(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def dead(sql: str, *a: object) -> str:
        raise RuntimeError("pool closed")

    monkeypatch.setattr(soak, "pg_sql", lambda sql: "__error__ no container")
    proc = SimpleNamespace(pid=os.getpid(), poll=lambda: 0)
    row = await soak.sample_once({"replica_1": proc}, SimpleNamespace(fetchval=dead))
    assert "pool closed" in row["pg_probe_error"]
    assert row["pg_connections"] == "__error__ no container"
    assert row["pg_waiting_locks"] == "__error__ no container"
    assert "runs_by_status" in row
    assert row["replica_1"]["wrapper_alive"] is False


def test_resolved_host_gateway_prefers_an_ipv4_literal(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    getent = "172.17.0.1     flags\nfe80::1 flags\n"

    def fake_sh(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, getent, "")

    monkeypatch.setattr(soak, "sh", fake_sh)
    assert soak.resolved_host_gateway_ipv4() == "172.17.0.1"
    monkeypatch.setattr(soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    assert soak.resolved_host_gateway_ipv4() is None


def test_render_nginx_conf_pins_ipv4_upstreams(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(soak, "resolved_host_gateway_ipv4", lambda: "172.17.0.1")
    target = tmp_path / "nginx-soak-rendered.conf"
    ip = soak.render_nginx_conf(target)
    assert ip == "172.17.0.1"
    rendered = target.read_text()
    assert "host.docker.internal" not in rendered
    assert "172.17.0.1" in rendered
    assert rendered == (soak.REPO / "scripts/soak/nginx-soak.conf").read_text().replace(
        "host.docker.internal", "172.17.0.1"
    )


def test_render_nginx_conf_stays_runnable_and_honest_without_an_ip(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(soak, "resolved_host_gateway_ipv4", lambda: None)
    target = tmp_path / "nginx-soak-rendered.conf"
    assert soak.render_nginx_conf(target) is None
    assert target.read_text() == (soak.REPO / "scripts/soak/nginx-soak.conf").read_text()


def test_start_nginx_mounts_the_rendered_conf_and_fails_softly(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cmds: list[list[str]] = []

    def spy(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "cid\n", "")

    monkeypatch.setattr(soak, "sh", spy)
    rendered = tmp_path / "nginx-soak-rendered.conf"
    rendered.write_text("upstream probe;\n")
    assert soak.start_nginx(tmp_path) is None
    assert len(cmds) == 2  # no re-render: the conf already exists
    assert cmds[0][:2] == ["docker", "rm"]
    run_cmd = cmds[1]
    assert f"{rendered}:/etc/nginx/nginx.conf:ro" in run_cmd
    assert f"127.0.0.1:{soak.LB_PORT}:8080" in run_cmd

    monkeypatch.setattr(
        soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "bind failed")
    )
    assert soak.start_nginx(tmp_path) is None  # logged, then boot_stack handles the leak


def test_start_replica_boots_uvicorn_in_its_own_session(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded: dict[str, object] = {}

    class FakeProc:
        pid = 4242

        def poll(self) -> int | None:
            return None

    def fake_popen(cmd: list[str], **kw: object) -> FakeProc:
        recorded["cmd"] = cmd
        recorded.update(kw)
        return FakeProc()

    monkeypatch.setattr(soak.subprocess, "Popen", fake_popen)
    proc = soak.start_replica(18201, tmp_path, {"DATABASE_URL": "x"})
    assert proc.pid == 4242
    cmd = recorded["cmd"]
    assert cmd[:4] == ["uv", "run", "--package", "maistro-server"]  # see run_migrations
    assert cmd[cmd.index("--host") + 1] == "0.0.0.0"
    assert cmd[cmd.index("--port") + 1] == "18201"
    assert recorded["start_new_session"] is True  # SIGKILL must not take the driver down
    assert recorded["cwd"] == soak.REPO
    assert recorded["env"] == {"DATABASE_URL": "x"}
    assert (tmp_path / "replica-18201.log").exists()


@pytest.mark.asyncio
async def test_wait_ready_returns_on_the_first_200(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def client(**kw: object):
        class C:
            async def get(self, url: str) -> SimpleNamespace:
                return SimpleNamespace(status_code=200)

        yield C()

    monkeypatch.setattr(soak, "shared_client", client)
    assert await soak.wait_ready("r1", "http://x/health/live", None, 1.0) is True


@pytest.mark.asyncio
async def test_wait_ready_reports_an_early_exit_without_probing(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    probed = False

    @asynccontextmanager
    async def client(**kw: object):
        nonlocal probed

        class C:
            async def get(self, url: str) -> SimpleNamespace:
                nonlocal probed
                probed = True
                raise AssertionError("must not probe a dead process")

        yield C()

    monkeypatch.setattr(soak, "shared_client", client)
    proc = SimpleNamespace(returncode=3, poll=lambda: 1)
    assert await soak.wait_ready("r1", "http://x/health/live", proc, 5.0) is False
    assert probed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["status-503", "unreachable"])
async def test_wait_ready_fails_closed_after_the_window(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: str
) -> None:
    import httpx

    @asynccontextmanager
    async def client(**kw: object):
        class C:
            async def get(self, url: str) -> SimpleNamespace:
                if mode == "status-503":
                    return SimpleNamespace(status_code=503)
                raise httpx.ConnectError("down", request=None)

        yield C()

    monkeypatch.setattr(soak, "shared_client", client)
    assert await soak.wait_ready("r1", "http://x/health/live", None, 0.6) is False
    out = capsys.readouterr().out
    assert "NOT ready after 0.6s" in out
    assert f"last={'503' if mode == 'status-503' else 'unreachable'}" in out
    # The degraded-progress log fires on the final partial window (remaining
    # seconds floor to a multiple of 30).
    assert "not ready yet" in out


@pytest.mark.asyncio
async def test_load_driver_walks_the_production_mix_and_records_transport_failures(
    soak: ModuleType,
) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/health/ready", "/health/live"):
            return httpx.Response(200)
        if path == "/metrics":
            return httpx.Response(401)
        if request.method == "POST" and path == "/tasks":
            return httpx.Response(202, json={"run_id": "run-a", "task_id": "task-1"})
        if path.startswith("/tasks/"):
            return httpx.Response(200, json={"status": "queued"})
        raise AssertionError(path)

    stats = soak.LoadStats()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for kind in ("health_ready", "health_live", "task_submit", "run_get", "metrics_unauth"):
            await soak.one_request_with(client, LB, {}, kind, stats, 0)
        raise_http = httpx.ConnectError("lb gone", request=None)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(raise_http))
        ) as offline:
            await soak.one_request_with(offline, LB, {}, "health_live", stats, 0)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(RuntimeError("boom")))
        ) as broken:
            await soak.one_request_with(broken, LB, {}, "health_ready", stats, 0)

    assert stats.status_codes == {200: 3, 202: 1, 401: 1, -1: 1, -2: 1}
    assert stats.kind_status_codes["task_submit"] == {202: 1}
    assert stats.kind_status_codes["health_live"] == {200: 1, -1: 1}
    assert stats.run_ids == {"run-a"}
    assert list(stats.task_ids) == ["task-1"]
    # status 0 means "no request issued"; everything above issued one.
    assert set(stats.latencies) == {
        "health_ready",
        "health_live",
        "task_submit",
        "run_get",
        "metrics_unauth",
    }


@pytest.mark.asyncio
async def test_worker_drives_the_seeded_mix_until_the_deadline(soak: ModuleType) -> None:
    import time as time_module

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/health/ready", "/health/live"):
            return httpx.Response(200)
        if path == "/metrics":
            return httpx.Response(401)
        if request.method == "POST":
            return httpx.Response(202, json={"run_id": "run-a", "task_id": "task-1"})
        if path.startswith("/tasks/"):
            return httpx.Response(200)
        raise AssertionError(path)

    stats = soak.LoadStats()
    mix = [("health_ready", 1.0), ("task_submit", 1.0), ("run_get", 1.0), ("metrics_unauth", 1.0)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await soak._worker_with_client(
            client, LB, {}, stats, time_module.monotonic() + 0.25, mix, 200.0, 3
        )
    assert set(stats.counts) == {"health_ready", "task_submit", "run_get", "metrics_unauth"}
    assert stats.status_codes[202] >= 1


@pytest.mark.asyncio
async def test_drive_load_shares_one_pooled_client_across_workers(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    builds: list[int] = []

    @asynccontextmanager
    async def client(**kw: object):
        builds.append(1)

        class C:
            async def get(self, url: str) -> SimpleNamespace:
                return SimpleNamespace(status_code=200)

        yield C()

    monkeypatch.setattr(soak, "shared_client", client)
    stats = soak.LoadStats()
    import time as time_module

    await soak.drive_load(
        LB, {}, stats, time_module.monotonic() + 0.05, 100.0, 3, [("health_live", 1.0)]
    )
    assert builds == [1]  # one pooled client, not one per worker
    assert stats.counts["health_live"] >= 3


@pytest.mark.asyncio
async def test_eo_probe_names_transport_degradation(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    submitted = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submitted
        submitted += 1
        if submitted == 1:
            return httpx.Response(202, json={"run_id": "run-a"})
        raise httpx.ConnectError("lb gone", request=request)

    @asynccontextmanager
    async def client(**kw: object):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c

    monkeypatch.setattr(soak, "shared_client", client)
    result = await soak.phase_exactly_once_tasks(LB, {}, 4)
    assert sorted(result["statuses"]) == [-1, -1, -1, 202]
    assert result["distinct_run_ids"] == ["run-a"]
    assert result["ok"] is False
    assert result["cause"] == "transport-degraded (LB 5xx): exactly-once unproven, not falsified"


@pytest.mark.asyncio
async def test_eo_probe_names_rate_limiting_as_a_probe_design_fact(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    submissions = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submissions
        submissions += 1
        if submissions == 1:
            return httpx.Response(202, json={"run_id": "run-a"})
        return httpx.Response(429)

    @asynccontextmanager
    async def client(**kw: object):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c

    monkeypatch.setattr(soak, "shared_client", client)
    result = await soak.phase_exactly_once_tasks(LB, {}, 2)
    assert result["distinct_run_ids"] == ["run-a"]
    assert result["statuses"] == [202, 429]
    assert result["ok"] is False
    assert (
        result["cause"]
        == "rate-limited during the probe window: exactly-once unproven, not falsified"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("7", 7), ("abc", -1), (None, -1), ("", -1), (42, 42), ("12x", -1)],
)
def test_integer_or_invalid_never_lies_about_probe_failures(
    soak: ModuleType, value: object, expected: int
) -> None:
    assert soak._integer_or_invalid(value) == expected


def test_rss_and_fd_growth_ignore_malformed_rows(soak: ModuleType, tmp_path: Path) -> None:
    metrics = tmp_path / "metrics.jsonl"
    metrics.write_text(
        '{"replica_1": {"rss_kb": 100, "fds": 5}, "replica_2": {"rss_kb": 200, "fds": 6}}\n'
        "not-json\n"
        '{"replica_1": {"rss_kb": 150, "fds": 7}, "replica_2": {"rss_kb": 190, "fds": 8}}\n'
    )
    assert soak._rss_growth(metrics)["replica_1"] == {
        "first_kb": 100,
        "last_kb": 150,
        "max_kb": 150,
        "growth_pct": 50.0,
    }
    assert soak._rss_growth(metrics)["replica_2"]["growth_pct"] == -5.0
    assert soak._fd_growth(metrics)["replica_1"] == {"first": 5, "last": 7, "max": 7}
    assert soak._fd_growth(metrics)["replica_2"] == {"first": 6, "last": 8, "max": 8}


def test_collect_hashes_binds_the_config_identity(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    git_head = "cafedeadbeef" * 6  # 72-char sentinel
    rendered = tmp_path / "nginx-soak-rendered.conf"
    rendered.write_text("upstream pinned;\n")

    def fake_sh(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        head = (cmd[0], cmd[1])
        if head == ("git", "rev-parse"):
            return subprocess.CompletedProcess(cmd, 0, git_head + "\n", "")
        if head == ("git", "diff"):
            return subprocess.CompletedProcess(cmd, 0, "dirty-diff\n", "")
        if head == ("git", "status"):
            return subprocess.CompletedProcess(cmd, 0, " M scripts/x.py\n", "")
        if head == ("docker", "image"):
            return subprocess.CompletedProcess(cmd, 0, "pgvector@sha256:abc\n", "")
        raise AssertionError(cmd)

    monkeypatch.setattr(soak, "sh", fake_sh)
    monkeypatch.setattr(soak, "pg_image_digest", lambda: "pgvector@sha256:abc")
    hashes = soak.collect_hashes(tmp_path, 3000, 100, fresh_db=True, gateway_ip="172.17.0.1")
    assert hashes["git_head"] == git_head
    assert hashes["git_clean"] is False  # a dirty tree must be visible in evidence
    assert hashes["git_diff_sha256"] == soak.sha256_text("dirty-diff\n")
    assert hashes["postgres_image"] == "pgvector@sha256:abc"
    assert hashes["nginx_rendered_conf_sha256"] == soak.sha256_text("upstream pinned;\n")
    assert hashes["host_gateway_ipv4"] == "172.17.0.1"
    assert hashes["version"] == (soak.REPO / "VERSION").read_text().strip()
    base = json.dumps(
        {
            "rate_limit_per_minute": 3000,
            "rate_limit_burst": 100,
            "allow_unsafe_resource_overrides": True,
            "api_keys": [soak.SOAK_API_KEY],
            "fresh_db": True,
        },
        sort_keys=True,
    )
    assert hashes["soak_env_sha256"] == soak.sha256_text(base)

    # The config identity must distinguish --no-fresh-db evidence: prior runs'
    # rows change what every count measures.
    no_fresh = soak.collect_hashes(tmp_path, 3000, 100, fresh_db=False, gateway_ip=None)
    assert no_fresh["soak_env_sha256"] != hashes["soak_env_sha256"]
    assert no_fresh["nginx_rendered_conf_sha256"] == hashes["nginx_rendered_conf_sha256"]


@pytest.mark.asyncio
async def test_drain_replica_records_a_clean_exit(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    victim = SimpleNamespace(pid=1, returncode=0, poll=lambda: 0)
    stats = soak.LoadStats()
    before = (await stats.snapshot())["status_codes"]
    await stats.record("task_submit", 503, 0.01, None)
    await stats.record("task_submit", -1, 0.01, None)
    kill_record: dict[str, object] = {}
    await soak.drain_replica(victim, stats, kill_record, before, t_send=0.0)
    assert kill_record["drained"] is True
    assert kill_record["escalated"] is False
    assert kill_record["exit_code"] == 0
    assert kill_record["drain_5xx"] == 1
    assert kill_record["drain_conn_errors"] == 1


@pytest.mark.asyncio
async def test_drain_replica_escalates_when_the_process_ignores_sigterm(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter([100.0, 100.5, 1000.0])

    def monotonic() -> float:
        return next(clock, 1000.0)

    monkeypatch.setattr(soak.time, "monotonic", monotonic)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(soak.asyncio, "sleep", fake_sleep)
    victim = SimpleNamespace(pid=2, returncode=None, poll=lambda: None)
    killed: list[object] = []
    monkeypatch.setattr(soak, "kill_replica", lambda proc: killed.append(proc))
    stats = soak.LoadStats()
    before = (await stats.snapshot())["status_codes"]
    kill_record: dict[str, object] = {}
    await soak.drain_replica(victim, stats, kill_record, before, t_send=100.0)
    assert kill_record["drained"] is False
    assert kill_record["escalated"] is True
    assert killed == [victim]
    assert 0.5 in sleeps and 2.0 in sleeps  # poll cadence, then escalation settle


def test_teardown_lb_captures_the_lb_view_before_removal(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cmds: list[list[str]] = []

    def spy(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "lb stdout\n", "lb stderr\n")

    monkeypatch.setattr(soak, "sh", spy)
    soak._teardown_lb(SimpleNamespace(out_dir=str(tmp_path)))
    assert [cmd[:2] for cmd in cmds] == [["docker", "logs"], ["docker", "rm"]]
    log_text = (tmp_path / "lb.log").read_text()
    assert "lb stdout" in log_text and "lb stderr" in log_text


def test_teardown_lb_records_unavailable_logs(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        soak, "sh", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "gone")
    )
    soak._teardown_lb(SimpleNamespace(out_dir=str(tmp_path)))
    assert "__docker logs unavailable rc=1" in (tmp_path / "lb.log").read_text()


def test_teardown_lb_survives_a_stuck_docker_call(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def stuck_logs(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[:2] == ["docker", "logs"]:
            raise subprocess.TimeoutExpired(cmd, 60)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(soak, "sh", stuck_logs)
    soak._teardown_lb(SimpleNamespace(out_dir=str(tmp_path)))
    assert [cmd[:2] for cmd in calls] == [["docker", "logs"], ["docker", "rm"]]


def test_main_claim_probe_mode_never_boots_the_stack(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, str | None]] = []
    monkeypatch.setattr(soak, "claim_probe_cli", lambda dsn, ws, due: calls.append((dsn, ws, due)))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--claim-probe",
            "postgresql://probe",
            "ws-1",
            "--claim-due-at",
            "2026-10-25T09:00:00+00:00",
        ],
    )
    soak.main()
    assert calls == [("postgresql://probe", "ws-1", "2026-10-25T09:00:00+00:00")]


def test_main_reports_success_only_when_every_gate_passes(
    soak: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def completed_run(args: object) -> dict[str, object]:
        return _passing_evidence()

    monkeypatch.setattr(soak, "main_async", completed_run)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--out-dir", str(tmp_path)])
    soak.main()  # no SystemExit: the only unreachable-by-design path is via evidence
    assert "all hard checks passed" in capsys.readouterr().out


def test_claim_probe_cli_prints_one_json_line(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, str, str | None]] = []

    async def fake_probe(dsn: str, workspace: str, due_at: str | None) -> dict[str, object]:
        calls.append((dsn, workspace, due_at))
        return {"run_ids": ["run-1"]}

    monkeypatch.setattr(soak, "_claim_one", fake_probe)
    soak.claim_probe_cli("postgresql://probe", "ws-9", "2026-10-25T09:00:00+00:00")
    assert calls == [("postgresql://probe", "ws-9", "2026-10-25T09:00:00+00:00")]
    assert json.loads(capsys.readouterr().out.strip()) == {"run_ids": ["run-1"]}


# ─── claim-probe phase: the exactly-once race and its forensic hygiene ───────


class _FakeRacer:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def communicate(self, timeout: float) -> tuple[str, str]:
        if isinstance(self._payload, dict):
            return (json.dumps(self._payload) + "\n", "")
        return (str(self._payload), "")


def _ok_racer(schedule_id: str, already: list[str]) -> dict[str, object]:
    # The loser of the race admits nothing: it observed the occurrence as
    # already fired. Both winners and losers report the same schedule identity.
    return {
        "run_ids": [] if already else ["run-1"],
        "already_fired": already,
        "failures": [],
        "skipped": [],
        "schedule_id": schedule_id,
    }


@pytest.mark.asyncio
async def test_claim_probe_verifies_one_physical_run_per_occurrence(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    popen_cmds: list[list[str]] = []
    racers = iter(
        [
            _FakeRacer(_ok_racer("s-1", [])),
            _FakeRacer(_ok_racer("s-1", ["2026-01-01T00:00:00+00:00"])),
        ]
    )

    def fake_popen(cmd: list[str], **kw: object) -> _FakeRacer:
        popen_cmds.append(cmd)
        return next(racers)

    monkeypatch.setattr(soak.subprocess, "Popen", fake_popen)
    sqls: list[str] = []

    def fake_pg_sql(sql: str) -> str:
        sqls.append(sql)
        return "1"  # one occurrence group, holding exactly one physical Run

    monkeypatch.setattr(soak, "pg_sql", fake_pg_sql)
    terminalized: list[str] = []

    async def fake_terminalize(dsn: str, run_id: str) -> str:
        terminalized.append(run_id)
        return "cancelled"

    monkeypatch.setattr(soak, "_terminalize_probe_run", fake_terminalize)
    result = await soak.phase_claim_probe(sys.executable, "postgresql://probe")

    assert len(popen_cmds) == 2
    for cmd in popen_cmds:
        assert cmd[0] == sys.executable and cmd[1] == str(SCRIPT)
        assert "--claim-due-at" in cmd
        due = cmd[cmd.index("--claim-due-at") + 1]
        assert due.endswith(":00:00+00:00")  # pinned to the top of the hour
    assert popen_cmds[0] == popen_cmds[1]  # byte-identical racers
    assert result["runs_created_for_occurrence"] == 1
    assert result["occurrences_with_runs"] == 1
    assert result["occurrences_with_multiple_runs"] == 0
    assert result["duplicate_claims_reported"] == 1
    assert result["probe_run_cleanup"] == {
        "attempted": True,
        "run_id": "run-1",
        "terminal_status": "cancelled",
    }
    assert result["ok"] is True
    assert "scheduled_for" in sqls[0]


@pytest.mark.asyncio
async def test_claim_probe_preserves_duplicate_rows_for_forensics(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    racers = iter([_FakeRacer(_ok_racer("s-1", [])), _FakeRacer(_ok_racer("s-1", []))])
    monkeypatch.setattr(soak.subprocess, "Popen", lambda cmd, **kw: next(racers))

    def fake_pg_sql(sql: str) -> str:
        return "2"  # one occurrence group holding TWO physical Runs

    monkeypatch.setattr(soak, "pg_sql", fake_pg_sql)
    terminalized: list[str] = []

    async def fake_terminalize(dsn: str, run_id: str) -> str:
        terminalized.append(run_id)
        return "cancelled"

    monkeypatch.setattr(soak, "_terminalize_probe_run", fake_terminalize)
    result = await soak.phase_claim_probe(sys.executable, "postgresql://probe")
    assert result["occurrences_with_multiple_runs"] == 1
    assert result["ok"] is False
    # A failed race is evidence: the probe Run must survive for inspection.
    assert terminalized == []
    assert result["probe_run_cleanup"] == {"attempted": False, "reason": "race not verified"}


@pytest.mark.asyncio
async def test_claim_probe_survives_garbage_racer_output(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    racers = iter([_FakeRacer("boom"), _FakeRacer("")])
    monkeypatch.setattr(soak.subprocess, "Popen", lambda cmd, **kw: next(racers))
    probed = False

    def fake_pg_sql(sql: str) -> str:
        nonlocal probed
        probed = True
        return "1"

    monkeypatch.setattr(soak, "pg_sql", fake_pg_sql)
    result = await soak.phase_claim_probe(sys.executable, "postgresql://probe")
    assert result["ok"] is False
    assert all("error" in proc for proc in result["processes"])
    assert probed is False  # no schedule identity: no SQL claim to verify


@pytest.mark.asyncio
async def test_claim_probe_treats_a_failed_sql_probe_as_unverified(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    racers = iter([_FakeRacer(_ok_racer("s-1", [])), _FakeRacer(_ok_racer("s-1", []))])
    monkeypatch.setattr(soak.subprocess, "Popen", lambda cmd, **kw: next(racers))
    monkeypatch.setattr(soak, "pg_sql", lambda sql: "__error__ container gone")
    result = await soak.phase_claim_probe(sys.executable, "postgresql://probe")
    assert result["ok"] is False
    assert result["occurrences_with_runs"] == 0
    assert result["probe_run_cleanup"] == {"attempted": False, "reason": "race not verified"}


@pytest.mark.asyncio
async def test_claim_probe_cleanup_failure_travels_with_the_evidence(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    racers = iter([_FakeRacer(_ok_racer("s-1", [])), _FakeRacer(_ok_racer("s-1", ["x"]))])
    monkeypatch.setattr(soak.subprocess, "Popen", lambda cmd, **kw: next(racers))
    monkeypatch.setattr(soak, "pg_sql", lambda sql: "1")

    async def boom(dsn: str, run_id: str) -> str:
        raise RuntimeError("admission store offline")

    monkeypatch.setattr(soak, "_terminalize_probe_run", boom)
    result = await soak.phase_claim_probe(sys.executable, "postgresql://probe")
    assert result["ok"] is True  # H2 was decided on the rows, not the cleanup
    assert result["probe_run_cleanup"]["attempted"] is True
    assert "admission store offline" in result["probe_run_cleanup"]["error"]


def _assert_claim_one_result(
    result: dict[str, object], created: dict[str, object], due_text: str
) -> None:
    from datetime import datetime, timedelta

    from maistro.scheduling.model import OverlapPolicy

    assert result["run_ids"] == ["run-1"]
    assert result["already_fired"] == [] and result["failures"] == []
    assert result["schedule_id"] == created["schedule"].schedule_id
    schedule = created["schedule"]
    assert schedule.actor_principal_id == "soak-claim-actor"
    assert schedule.overlap_policy is OverlapPolicy.ALLOW
    assert schedule.catchup_window_seconds == 6 * 3600
    due = datetime.fromisoformat(due_text)
    assert schedule.last_fired_at == due - timedelta(minutes=1)
    assert schedule.next_due_at == due
    assert created["project_kwargs"]["workspace_id"] == "ws-claim"
    assert created["closed"] is True


def _install_claim_probe_store_seams(
    monkeypatch: pytest.MonkeyPatch, created: dict[str, object]
) -> None:
    import asyncpg

    class FakePool:
        async def close(self) -> None:
            created["closed"] = True

    class FakeProjects:
        def __init__(self, pool: object) -> None:
            created["projects_pool"] = pool

        async def create_root(self, workspace: str) -> SimpleNamespace:
            return SimpleNamespace(project_id="root-1")

        async def create(self, **kw: object) -> SimpleNamespace:
            created["project_kwargs"] = kw
            return SimpleNamespace(project_id="proj-1")

    class FakeSchedules:
        def __init__(self, pool: object) -> None:
            pass

        async def put(self, schedule: object) -> None:
            created["schedule"] = schedule

    async def fake_create_pool(*a: object, **kw: object) -> FakePool:
        return FakePool()

    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setattr("maistro.projects.pg_scope_store.PgProjectScopeStore", FakeProjects)
    monkeypatch.setattr("maistro.scheduling.pg_store.PgScheduleStore", FakeSchedules)
    monkeypatch.setattr("maistro.runs.pg_store.PgRunStore", _FakeRuns)
    monkeypatch.setattr("maistro.scheduling.admission.ScheduleRunAdmitter", _FakeAdmitter)


class _FakeRuns:
    def __init__(self, pool: object, project_store: object = None) -> None:
        pass


class _FakeAdmitter:
    def __init__(self, runs: object, templates: object, schedules: object) -> None:
        pass

    async def admit_due(self, schedule: object, now: object) -> SimpleNamespace:
        return SimpleNamespace(run_ids=["run-1"], already_fired=[], failures=[], skipped=[])


@pytest.mark.asyncio
async def test_claim_one_builds_the_pinned_hourly_schedule(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: dict[str, object] = {}
    _install_claim_probe_store_seams(monkeypatch, created)

    due_text = "2026-10-25T09:00:00+00:00"
    result = await soak._claim_one("postgresql://probe", "ws-claim", due_text)
    _assert_claim_one_result(result, created, due_text)

    # Without an explicit pin the due instant is the most recent hourly :00,
    # so both racers independently derive the same occurrence.
    result2 = await soak._claim_one("postgresql://probe", "ws-claim", None)
    assert result2["run_ids"] == ["run-1"]
    derived = created["schedule"].next_due_at
    assert (derived.minute, derived.second, derived.microsecond) == (0, 0, 0)


@pytest.mark.asyncio
async def test_terminalize_probe_run_cancels_through_the_canonical_store(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncpg

    from maistro.runs.model import RunStatus

    created: dict[str, object] = {}

    class FakePool:
        async def close(self) -> None:
            pass

    class FakeRuns:
        def __init__(self, pool: object, project_store: object = None) -> None:
            pass

        async def transition_run(
            self, run_id: str, status: RunStatus, error: str
        ) -> SimpleNamespace:
            created["run_id"] = run_id
            created["status"] = status
            created["error"] = error
            return SimpleNamespace(status=SimpleNamespace(value="cancelled"))

    async def fake_create_pool(*a: object, **kw: object) -> FakePool:
        return FakePool()

    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setattr("maistro.runs.pg_store.PgRunStore", FakeRuns)
    status = await soak._terminalize_probe_run("postgresql://probe", "run-1")
    assert status == "cancelled"
    assert created["run_id"] == "run-1"
    assert created["status"] is RunStatus.CANCELLED
    assert "soak claim probe" in str(created["error"])


# ─── main_async: the whole orchestrated run, fail-closed by construction ─────


def _spawn_sleeper(victims: list[subprocess.Popen]) -> subprocess.Popen:
    proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
    victims.append(proc)
    return proc


def _install_registration_seams(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[list[str]], list[dict[str, object]]]:
    """Never mutate process-global outbound policy or pool state in tests."""
    registered: list[list[str]] = []
    shared: list[dict[str, object]] = []
    monkeypatch.setattr(soak, "allow_soak_origins", lambda: registered.append(["origins"]))
    monkeypatch.setattr(soak, "configure_shared_http", lambda **kw: shared.append(kw))
    return registered, shared


def _install_shell_seam(soak: ModuleType, monkeypatch: pytest.MonkeyPatch, git_head: str) -> None:
    def fake_sh(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        head = (cmd[0], cmd[1])
        if head == ("git", "rev-parse"):
            return subprocess.CompletedProcess(cmd, 0, git_head + "\n", "")
        if head in (("git", "diff"), ("git", "status")):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if head == ("docker", "image"):
            return subprocess.CompletedProcess(cmd, 0, "pgvector@sha256:abc\n", "")
        if head == ("docker", "run"):
            return subprocess.CompletedProcess(cmd, 0, "172.17.0.1     flags\n", "")
        if head == ("docker", "logs"):
            return subprocess.CompletedProcess(cmd, 0, "lb stdout view\n", "lb error view\n")
        if head == ("docker", "rm"):
            return subprocess.CompletedProcess(cmd, 0, "maistro-soak-lb\n", "")
        raise AssertionError(cmd)

    monkeypatch.setattr(soak, "sh", fake_sh)


def _install_process_seams(
    soak: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    victims: list[subprocess.Popen],
    restarts: list[int],
    teardown_kills: list[object],
) -> None:
    async def fake_boot_stack(args: object) -> tuple[dict[str, object], dict[str, object]]:
        # replica_1 stays alive for the whole run (teardown must kill it);
        # replica_2 is the kill/restart victim and dies for real.
        return (
            {"replica_1": _spawn_sleeper(victims), "replica_2": _spawn_sleeper(victims)},
            {"env2": {"DB_POOL_SIZE": "2"}, "boot_seconds": 1.5},
        )

    monkeypatch.setattr(soak, "boot_stack", fake_boot_stack)

    def fake_start_replica(port: int, log_dir: Path, env: dict[str, str]) -> SimpleNamespace:
        restarts.append(port)
        return SimpleNamespace(pid=os.getpid(), poll=lambda: 0)

    monkeypatch.setattr(soak, "start_replica", fake_start_replica)

    async def fake_wait_ready(name: str, url: str, proc: object, timeout: float) -> bool:
        return True

    monkeypatch.setattr(soak, "wait_ready", fake_wait_ready)
    monkeypatch.setattr(soak, "kill_replica", lambda proc: teardown_kills.append(proc))


def _install_postgres_seam(monkeypatch: pytest.MonkeyPatch) -> object:
    import asyncpg

    class FakePool:
        def __init__(self) -> None:
            self.closed = False

        async def fetchval(self, sql: str) -> object:
            if sql == "SELECT 1":
                return 1
            if "pg_stat_activity" in sql:
                return 3
            if "pg_locks" in sql:
                return 0
            return "queued=1 completed=2"

        async def close(self) -> None:
            self.closed = True

    fake_pool = FakePool()

    async def fake_create_pool(*a: object, **kw: object) -> FakePool:
        return fake_pool

    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
    return fake_pool


def _install_load_transport(soak: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("/health/ready", "/health/live"):
            return httpx.Response(200)
        if request.method == "POST" and path == "/tasks":
            return httpx.Response(202, json={"run_id": "run-1", "task_id": "task-1"})
        if path.startswith("/tasks/"):
            return httpx.Response(200, json={"status": "queued"})
        if path == "/metrics":
            return httpx.Response(401)
        raise AssertionError(path)

    @asynccontextmanager
    async def client_for_load(**kw: object):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            yield client

    monkeypatch.setattr(soak, "shared_client", client_for_load)


def _install_phase_seams(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch, phase_calls: dict[str, object]
) -> None:
    async def fake_eo(base: str, headers: dict[str, str], n: int) -> dict[str, object]:
        phase_calls["eo"] = (base, n)
        return {"ok": True, "distinct_run_ids": ["run-1"]}

    async def fake_claim(python: str, dsn: str) -> dict[str, object]:
        phase_calls["claim"] = (python, dsn)
        return {"ok": True}

    async def fake_rate(
        lb: str, origins: tuple[str, ...], headers: dict[str, str], total: int, burst: int
    ) -> dict[str, object]:
        phase_calls["rate"] = (lb, origins, total, burst)
        return {"enforced_everywhere": True, "probe_requests": total}

    monkeypatch.setattr(soak, "phase_exactly_once_tasks", fake_eo)
    monkeypatch.setattr(soak, "phase_claim_probe", fake_claim)
    monkeypatch.setattr(soak, "phase_rate_limit", fake_rate)

    def fake_pg_sql(sql: str) -> str:
        if "run_id::text" in sql:
            return ""
        if "status NOT IN" in sql:
            return "0"
        if "task_id" in sql:
            return "0"
        if "GROUP BY status" in sql:
            return "completed=2"
        raise AssertionError(sql)

    monkeypatch.setattr(soak, "pg_sql", fake_pg_sql)


def _orchestration_args(out_dir: Path, kill_signal: str) -> SimpleNamespace:
    return SimpleNamespace(
        out_dir=str(out_dir),
        sustain_seconds=0.4,
        rps=150.0,
        workers=4,
        pool_size=2,
        max_overflow=3,
        rate_limit_per_minute=3000,
        rate_limit_burst=100,
        kill_fraction=0.3,
        kill_signal=kill_signal,
        restart_delay_s=0.0,
        eo_concurrency=12,
        rate_limit_probe_requests=800,
        fresh_db=True,
        settle_seconds=0,
        sample_interval=0.1,
    )


def _assert_orchestration(
    soak: ModuleType,
    evidence: dict,
    out_dir: Path,
    phase_calls: dict[str, object],
    git_head: str,
    kill_signal: str,
    restarts: list[int],
    teardown_kills: list[object],
    registered: list[list[str]],
    shared: list[dict[str, object]],
) -> None:
    # The kill actually fired on the real victim process group; the teardown
    # killed the replica that stayed alive.
    assert restarts == [18202]
    assert len(teardown_kills) == 1
    assert registered == [["origins"]]
    assert shared == [{"max_connections": 64}]

    lb = f"http://127.0.0.1:{soak.LB_PORT}"
    assert phase_calls["eo"] == (lb, 12)
    assert phase_calls["claim"] == (
        sys.executable,
        f"postgresql://maistro:soak@127.0.0.1:{soak.PG_HOST_PORT}/maistro",
    )
    assert phase_calls["rate"] == (lb, soak.REPLICA_ORIGINS, 800, 100)

    assert evidence["issue"] == "860"
    assert evidence["hashes"]["git_head"] == git_head
    assert evidence["hashes"]["git_clean"] is True
    assert evidence["hashes"]["host_gateway_ipv4"] == "172.17.0.1"
    assert evidence["replica_boot_seconds"] == 1.5
    assert evidence["requested_sustain_seconds"] == 0.4
    assert evidence["sustain_seconds"] < 5.0  # the observed window, not the requested one
    assert evidence["kill_restart"]["signal"] == kill_signal
    assert evidence["kill_restart"]["rejoined"] is True
    assert evidence["kill_restart"]["window_seconds"] >= 0.0  # an instant fake restart is 0.0
    assert "window_status_counts" in evidence["kill_restart"]
    if kill_signal == "SIGTERM":
        assert evidence["kill_restart"]["drained"] is True
        assert evidence["kill_restart"]["escalated"] is False

    checks = evidence["thresholds"]["checks"]
    assert checks["exact_rc_artifact"]["topology"] == "host-uvicorn-preflight"
    assert checks["exact_rc_artifact"]["ok"] is False
    assert checks["sustain_duration"]["ok"] is False  # a preflight is never a promotion run
    assert checks["replica_2_rejoined"] is True
    assert checks["lb_failover_bounded"]["ok"] is True
    assert checks["nonterminal_runs_after_settle"]["count"] == 0
    assert checks["exactly_once_task_admission"] is True
    assert checks["exactly_once_schedule_occurrence"] is True
    assert checks["rate_limit_enforced"] is True
    assert checks["task_admission_availability"]["ok"] is True
    drain = checks["graceful_drain"]
    assert drain["required"] is (kill_signal == "SIGTERM")
    assert drain["ok"] is (kill_signal == "SIGTERM")
    assert evidence["thresholds"]["p95_latency_ms"]

    # The fail-closed contract, evaluated by the same CLI gate main() uses:
    # this orchestrated host preflight must sign NOTHING.
    assert soak.failed_promotion_checks(evidence) == ["sustain_duration", "exact_rc_artifact"]

    persisted = json.loads((out_dir / "m3a-soak-evidence.json").read_text())
    assert persisted["issue"] == "860"
    assert persisted["thresholds"]["checks"]["exact_rc_artifact"]["ok"] is False
    assert (out_dir / "lb.log").read_text().startswith("lb stdout view")
    metrics_rows = [
        json.loads(line)
        for line in (out_dir / "metrics.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(metrics_rows) >= 10
    assert metrics_rows[0]["pg_connections"] == 3
    assert metrics_rows[0]["runs_by_status"] == "queued=1 completed=2"
    assert "driver_loop_lag_ms" in metrics_rows[0]
    assert "replica_1" in evidence["thresholds"]["checks"]["rss_growth"]


@pytest.mark.skipif(
    sys.platform != "linux", reason="boots real sleeper processes for /proc sampling"
)
@pytest.mark.asyncio
@pytest.mark.parametrize("kill_signal", ["SIGTERM", "SIGKILL"])
async def test_main_async_orchestrates_every_phase_and_fails_closed(
    soak: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kill_signal: str,
) -> None:
    out_dir = tmp_path / "evidence"
    out_dir.mkdir()
    victims: list[subprocess.Popen] = []
    restarts: list[int] = []
    teardown_kills: list[object] = []
    phase_calls: dict[str, object] = {}
    git_head = "cafedeadbeefcafedeadbeefcafedeadbeefcafedeadbeefcafedeadbeefcafedead"

    registered, shared = _install_registration_seams(soak, monkeypatch)
    _install_shell_seam(soak, monkeypatch, git_head)
    _install_process_seams(soak, monkeypatch, victims, restarts, teardown_kills)
    _install_postgres_seam(monkeypatch)
    _install_load_transport(soak, monkeypatch)
    _install_phase_seams(soak, monkeypatch, phase_calls)

    try:
        evidence = await soak.main_async(_orchestration_args(out_dir, kill_signal))
    finally:
        for proc in victims:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

    _assert_orchestration(
        soak,
        evidence,
        out_dir,
        phase_calls,
        git_head,
        kill_signal,
        restarts,
        teardown_kills,
        registered,
        shared,
    )


@pytest.mark.asyncio
async def test_replica_boot_failure_never_leaves_an_orphan_serving(
    soak: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The replica-side counterpart of the LB-failure doctrine: a boot where a
    replica never becomes ready must end both process groups and refuse when
    one still accepts, so a retry cannot adopt a process this run never started."""
    monkeypatch.setattr(soak, "ensure_postgres", lambda: None)
    monkeypatch.setattr(soak, "ensure_replica_ports_free", lambda: None)
    monkeypatch.setattr(soak, "reset_db_schema", lambda: None)
    monkeypatch.setattr(soak, "run_migrations", lambda: None)
    monkeypatch.setattr(soak, "replica_env", lambda *args, **kwargs: {})
    booted: list[int] = []

    def fake_start_replica(port: int, out_dir: Path, env: dict[str, str]) -> SimpleNamespace:
        booted.append(port)
        return SimpleNamespace(pid=port, poll=lambda: None)

    async def fake_wait_ready(name: str, url: str, proc: object, timeout: int) -> bool:
        return False  # the replicas never become ready

    killed: list[object] = []
    monkeypatch.setattr(soak, "start_replica", fake_start_replica)
    monkeypatch.setattr(soak, "wait_ready", fake_wait_ready)
    monkeypatch.setattr(soak, "kill_replica", lambda proc: killed.append(proc))
    # After the kill, the orphan still accepts: the run must say so.
    monkeypatch.setattr(soak, "port_closed", lambda port, timeout=1.0: False)

    args = SimpleNamespace(
        fresh_db=True,
        pool_size=1,
        max_overflow=1,
        rate_limit_per_minute=3000,
        rate_limit_burst=100,
        out_dir="/tmp/soak-replica-boot-failure",
    )
    with pytest.raises(RuntimeError, match=r"orphaned servers still accept on ports"):
        await soak.boot_stack(args)
    assert booted == [18201, 18202]
    assert len(killed) == 2
