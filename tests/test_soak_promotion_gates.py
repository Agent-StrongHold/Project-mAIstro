"""Regression tests for #860 soak-evidence promotion gates."""

from __future__ import annotations

import importlib.util
import json
import os
import select
import signal
import subprocess
import sys
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
