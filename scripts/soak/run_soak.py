#!/usr/bin/env python3
"""M3-A #860 — representative multi-replica load and concurrency soak driver.

Boots the RC application surface (``maistro_server`` via the same entrypoint
the RC container image uses: schema migrations under the advisory lock, then
``uvicorn maistro_server.main:app``) as N replicas behind an nginx load
balancer that mirrors ``deploy/nginx.conf``, drives a sustained mixed request
profile through the LB, samples PostgreSQL / process / queue health, proves
exactly-once admission (task idempotency and cross-process schedule occurrence
claims), probes rate limiting through the LB, and kills/restarts one replica
mid-load to observe drain, failover, and recovery.

Everything observed is written as machine-readable evidence (one JSON summary
plus a JSONL metrics trace) tied to the exact commit/diff/config hashes, for
the human-readable pack in docs/testing/soak/m3a-soak-evidence.md.

This is a falsification harness, not a benchmark: pass/fail is decided by the
correctness and stability thresholds in docs/testing/soak/m3a-load-profile.md.

Usage (from the repo root):
    uv run python scripts/soak/run_soak.py --sustain-seconds 420 --out-dir docs/testing/soak/evidence

Sub-modes (used internally, useful for debugging):
    uv run python scripts/soak/run_soak.py --claim-probe <dsn> <workspace_id>
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import signal
import statistics
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maistro.http import configure_shared_http, shared_client
from maistro.security.outbound import configure_outbound_policy

REPO = Path(__file__).resolve().parents[2]
PG_CONTAINER = "maistro-soak-pg"
PG_IMAGE = "pgvector/pgvector:pg18"
PG_HOST_PORT = 18433
LB_PORT = 18080
NGINX_IMAGE = "nginx:1.27-alpine"
SOAK_API_KEY = "soak:soak-key-1"  # principal:secret form required by #843
# Synthetic soak fixtures, not credentials. TASK_DELEGATION_KEY is opaque to
# the server and ROUTER_API_KEY only has to clear the >=32-char Settings
# warning (maistro.config.loader._validate_secrets), so both are deliberately
# low-entropy: the round-1 hex-padded shapes tripped gitleaks generic-api-key
# on commit 2520eeb (see .gitleaksignore) while carrying zero secret content.
SOAK_DELEGATION_KEY = "soak-delegation-key"
SOAK_ROUTER_KEY = "soak-router-key" + "0" * 19
SHUTDOWN_DRAIN_TIMEOUT_S = 30.0  # maistro_server.main.SHUTDOWN_DRAIN_TIMEOUT
PROMOTION_MIN_SUSTAIN_SECONDS = 14_400


# Load is driven through the pooled `maistro.http` seam, so the driver is
# subject to the same default-deny outbound policy as production callers. It
# registers its own loopback stack once, up front, exactly the way a real
# deployment registers its operator-configured origins — never next to a
# fetch site, which the security inventory treats as self-authorization.
def allow_soak_origins() -> None:
    """Allow the soak stack's loopback origins for this process."""
    configure_outbound_policy(
        f"http://127.0.0.1:{LB_PORT}",
        "http://127.0.0.1:18201",
        "http://127.0.0.1:18202",
    )


def log(msg: str) -> None:
    print(f"[soak {datetime.now(UTC).strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sh(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ────────────────────────────── infrastructure ──────────────────────────────


def pg_available() -> bool:
    r = sh(
        [
            "docker",
            "exec",
            PG_CONTAINER,
            "pg_isready",
            "-U",
            "maistro",
            "-d",
            "maistro",
        ]
    )
    return r.returncode == 0


def ensure_postgres() -> None:
    if pg_available():
        log("postgres container already up")
        return
    log("starting postgres (pgvector:pg18) for the soak")
    sh(["docker", "rm", "-f", PG_CONTAINER])
    r = sh(
        [
            "docker",
            "run",
            "-d",
            "--name",
            PG_CONTAINER,
            "-e",
            "POSTGRES_USER=maistro",
            "-e",
            "POSTGRES_PASSWORD=soak",
            "-e",
            "POSTGRES_DB=maistro",
            "-p",
            f"127.0.0.1:{PG_HOST_PORT}:5432",
            PG_IMAGE,
        ]
    )
    if r.returncode != 0:
        raise RuntimeError(f"docker run postgres failed: {r.stderr}")
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if pg_available():
            log("postgres is ready")
            return
        time.sleep(1)
    raise RuntimeError("postgres did not become ready in 90s")


def pg_image_digest() -> str:
    r = sh(["docker", "image", "inspect", PG_IMAGE, "--format", "{{index .RepoDigests 0}}"])
    return r.stdout.strip() or PG_IMAGE


def reset_db_schema() -> None:
    """Drop and recreate the public schema of the dedicated soak database.

    H5 (`0 non-terminal Runs after settle`) and every status count in the
    evidence are claims about *this run*. The soak database persists across
    runs, and the claim probe's schedule Run is intentionally never executed
    (the probe races admission, then exits), so without a reset the queued
    debt of every previous run accumulates and makes the H5 gate
    structurally unsatisfiable — the round-4 preflight's "10 queued" were
    all prior probes, zero of them stalled task work. The container is
    soak-dedicated (maistro-soak-pg, port 18433) and migrations re-create
    the full schema right after, so the reset cannot touch any other
    surface. The flag is part of soak_env_sha256, so the config identity
    says which mode the evidence was taken in.
    """
    r = sh(
        [
            "docker",
            "exec",
            PG_CONTAINER,
            "psql",
            "-U",
            "maistro",
            "-d",
            "maistro",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        ]
    )
    if r.returncode != 0:
        raise RuntimeError(f"soak schema reset failed: {r.stderr[-500:]}")


def pg_sql(sql: str) -> str:
    r = sh(["docker", "exec", PG_CONTAINER, "psql", "-U", "maistro", "-d", "maistro", "-tAc", sql])
    return r.stdout.strip() if r.returncode == 0 else f"__error__ {r.stderr.strip()[:200]}"


def replica_env(
    port: int, pool_size: int, max_overflow: int, rate_per_min: int, burst: int
) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": f"postgresql+asyncpg://maistro:soak@127.0.0.1:{PG_HOST_PORT}/maistro",
            "API_KEYS": json.dumps([SOAK_API_KEY]),
            "REQUIRE_AUTH": "true",
            "TASK_DELEGATION_KEY": SOAK_DELEGATION_KEY,
            "ROUTER_API_KEY": SOAK_ROUTER_KEY,
            "DB_POOL_SIZE": str(pool_size),
            "DB_MAX_OVERFLOW": str(max_overflow),
            "RATE_LIMIT_PER_MINUTE": str(rate_per_min),
            "RATE_LIMIT_BURST": str(burst),
            # The Settings baseline validator refuses a raised limiter without
            # this documented dev/unsafe escape hatch; the soak records the
            # flag in soak_env_sha256 so the config identity stays honest.
            "ALLOW_UNSAFE_RESOURCE_OVERRIDES": "true",
            "MAISTRO_SOAK_REPLICA": f"replica-{port}",
        }
    )
    return env


def run_migrations() -> None:
    """Same migration path the RC entrypoint runs (maistro_server.entrypoint)."""
    env = dict(os.environ)
    env["DATABASE_URL"] = f"postgresql+asyncpg://maistro:soak@127.0.0.1:{PG_HOST_PORT}/maistro"
    # `--package maistro-server` is load-bearing: the root workspace project
    # does not depend on maistro-server, so the documented `uv sync` does not
    # install it into the root environment (verified: `uv sync --locked
    # --extra dev --dry-run` reports "Would uninstall maistro-server"). A bare
    # `uv run python -c "import maistro_server"` is whatever the local venv
    # happens to contain — the undocumented state that made this harness fail
    # with ModuleNotFoundError on a clean checkout. Naming the workspace
    # member makes the requirement explicit and self-satisfying.
    r = sh(
        [
            "uv",
            "run",
            "--package",
            "maistro-server",
            "python",
            "-c",
            "from maistro_server.entrypoint import run_migrations; run_migrations()",
        ],
        env=env,
        cwd=REPO,
        timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"migrations failed: {r.stderr[-2000:]}")


def kill_replica(proc: subprocess.Popen[Any]) -> None:
    """SIGKILL the replica's whole process group, not the `uv` wrapper.

    start_new_session makes the wrapper a session leader; kill() alone hits
    only the wrapper and the uvicorn child keeps serving (observed in run 1:
    `rejoined=true` seconds after a "kill"). Boot-failure cleanup had the
    same bug and left an orphan bound to the replica port.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def port_closed(port: int, timeout: float = 1.0) -> bool:
    """True when nothing accepts TCP connections on 127.0.0.1:<port>."""
    import socket

    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) != 0


def start_replica(port: int, out_dir: Path, env: dict[str, str]) -> subprocess.Popen[Any]:
    """Boot one replica exactly as the RC image does, minus the container."""
    log_file = open(out_dir / f"replica-{port}.log", "ab")  # noqa: SIM115
    # --package maistro-server: see run_migrations for why the member is
    # named explicitly (the documented root `uv sync` does not install it).
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "--package",
            "maistro-server",
            "python",
            "-m",
            "uvicorn",
            "maistro_server.main:app",
            "--host",
            "0.0.0.0",  # reachable from the nginx container via the host-gateway alias
            "--port",
            str(port),
        ],
        env=env,
        cwd=REPO,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # own process group: SIGKILL must not take the driver down
    )
    return proc


async def wait_ready(
    name: str, url: str, proc: subprocess.Popen[Any] | None, timeout: float
) -> bool:
    deadline = time.monotonic() + timeout
    last_status = "unreachable"
    async with shared_client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if proc is not None and proc.poll() is not None:
                log(f"{name} exited early rc={proc.returncode}")
                return False
            try:
                r = await client.get(url)
                last_status = str(r.status_code)
                if r.status_code == 200:
                    return True
            except Exception:
                last_status = "unreachable"
            await asyncio.sleep(0.5)
            if int(deadline - time.monotonic()) % 30 == 0:
                log(f"{name} not ready yet (last={last_status})")
    log(f"{name} NOT ready after {timeout}s (last={last_status})")
    return False


def resolved_host_gateway_ipv4() -> str | None:
    """host.docker.internal's IPv4, as a soak container resolves it.

    Docker Desktop answers the name with BOTH an IPv6 address (unreachable
    from the container: `connect() failed (101: Network unreachable)`) and
    the IPv4 gateway. nginx resolves every address of a named upstream and
    round-robins NEW upstream connections across them, so each new
    connection has a coin-flip chance of an instant ENETUNREACH — which
    counts toward `max_fails` for the *peer* (failures are tracked per name,
    not per address). Three unlucky connects within fail_timeout mark the
    replica down; under sustained connection churn both replicas flap into
    the down state and the LB answers mass instant "no live upstreams" 502s
    — the F3 storm of runs 1-4 (run 1: 7445/7590 requests; only ~51 reached
    the application). Production is immune: deploy/nginx.conf targets
    compose service names, which resolve to a single container address. The
    soak therefore pins IPv4 literals instead of the dual-address name.
    """
    r = sh(["docker", "run", "--rm", NGINX_IMAGE, "getent", "ahostsv4", "host.docker.internal"])
    for line in r.stdout.splitlines():
        candidate = line.split()[0] if line.split() else ""
        if candidate.count(".") == 3 and all(p.isdigit() for p in candidate.split(".")):
            return candidate
    return None


def render_nginx_conf(target: Path) -> str | None:
    """Render the soak LB conf with IPv4 upstream literals; returns the IP."""
    template = (REPO / "scripts/soak/nginx-soak.conf").read_text()
    ip = resolved_host_gateway_ipv4()
    if ip is None:
        # Keep the run runnable, but say why the storm may recur in evidence.
        log(
            "WARNING: could not resolve host.docker.internal IPv4; "
            "mounting the template unchanged (dual-address peer poisoning may recur)"
        )
        target.write_text(template)
        return None
    target.write_text(template.replace("host.docker.internal", ip))
    return ip


def start_nginx(out_dir: Path) -> subprocess.Popen[Any] | None:
    sh(["docker", "rm", "-f", "maistro-soak-lb"])
    rendered = out_dir / "nginx-soak-rendered.conf"
    if not rendered.exists():
        render_nginx_conf(rendered)
    r = sh(
        [
            "docker",
            "run",
            "-d",
            "--name",
            "maistro-soak-lb",
            "--add-host",
            "host.docker.internal:host-gateway",
            "-v",
            f"{rendered}:/etc/nginx/nginx.conf:ro",
            "-p",
            f"127.0.0.1:{LB_PORT}:8080",
            NGINX_IMAGE,
        ]
    )
    if r.returncode != 0:
        log(f"nginx failed to start: {r.stderr[:400]}")
        return None
    return None


# ─────────────────────────────── samplers ───────────────────────────────────


def proc_stats(pid: int) -> dict[str, Any] | None:
    try:
        rss_kb = None
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    break
        fds = len(os.listdir(f"/proc/{pid}/fd"))
        return {"pid": pid, "rss_kb": rss_kb, "fds": fds}
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None


async def sample_once(procs: dict[str, subprocess.Popen[Any]], pg_pool: Any) -> dict[str, Any]:
    s: dict[str, Any] = {"ts": datetime.now(UTC).isoformat()}
    for name, proc in procs.items():
        stats = proc_stats(proc.pid) if proc.poll() is None else None
        s[name] = stats if stats else {"alive": False}
    # Query latency is measured on a dedicated asyncpg connection: the real
    # wire round-trip under load, not psql-process spawn wall time. The
    # docker-exec channel stays as fallback so a probe failure degrades the
    # sample instead of killing the trace.
    t0 = time.perf_counter()
    try:
        await pg_pool.fetchval("SELECT 1")
        s["pg_probe_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        s["pg_connections"] = await pg_pool.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        )
        s["pg_waiting_locks"] = await pg_pool.fetchval(
            "SELECT count(*) FROM pg_locks WHERE NOT granted"
        )
        s["runs_by_status"] = await pg_pool.fetchval(
            "SELECT coalesce(string_agg(status || '=' || n, ' '), 'none') FROM "
            "(SELECT status, count(*) AS n FROM canonical_runs GROUP BY status) t"
        )
    except Exception as exc:
        s["pg_probe_error"] = str(exc)[:160]
        s["pg_connections"] = pg_sql(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        )
        s["pg_waiting_locks"] = pg_sql("SELECT count(*) FROM pg_locks WHERE NOT granted")
        s["runs_by_status"] = pg_sql(
            "SELECT coalesce(string_agg(status || '=' || n, ' '), 'none') FROM "
            "(SELECT status, count(*) AS n FROM canonical_runs GROUP BY status) t"
        )
    return s


# ──────────────────────────── claim probe (subprocess mode) ─────────────────


async def _claim_one(dsn: str, workspace: str, due_at_text: str | None = None) -> dict[str, Any]:
    """Claim one due occurrence through the canonical admission authority.

    Runs in its own OS process (two of these race in the exactly-once phase).
    Same wiring as packages/maistro-core/tests/scheduling/test_pg_admission.py.
    """
    from datetime import timedelta

    import asyncpg

    from maistro.graph.definitions import GraphTemplate, Node
    from maistro.graph.templates import InMemoryGraphTemplateStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore
    from maistro.scheduling.admission import ScheduleRunAdmitter
    from maistro.scheduling.model import OverlapPolicy, Schedule
    from maistro.scheduling.pg_store import PgScheduleStore

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    assert pool is not None
    try:
        projects = PgProjectScopeStore(pool)
        root = await projects.create_root(workspace)
        project = await projects.create(
            workspace_id=workspace,
            parent_project_id=root.project_id,
            name="Soak claim probe",
        )
        templates = InMemoryGraphTemplateStore()
        await templates.put(
            GraphTemplate(
                template_id="soak-claim-template",
                workspace_id=workspace,
                name="Soak claim probe template",
                nodes=[Node(node_id="node-1", node_type="agent", name="agent")],
            )
        )
        now = datetime.now(UTC)
        # The due instant is pinned by the parent (floor(now, 1h)) and handed
        # to both racing processes, so they construct byte-identical schedules
        # and the window (due_at - 1min, now] contains exactly one hourly
        # occurrence: due_at itself. Deriving it per-process from now-90min
        # instead made the due count depend on the wall-clock minute (two
        # occurrences whenever minute <= 30), so the old "total runs == 1"
        # gate false-failed on hour-straddling runs and could not tell a
        # duplicate claim from a skipped occurrence.
        due_at = (
            datetime.fromisoformat(due_at_text)
            if due_at_text
            else now.replace(minute=0, second=0, microsecond=0)
        )
        schedule = Schedule(
            schedule_id=f"soak-claim-{workspace}",
            workspace_id=workspace,
            project_id=project.project_id,
            cron="0 * * * *",
            graph_template_id="soak-claim-template",
            overlap_policy=OverlapPolicy.ALLOW,
            catchup_window_seconds=6 * 3600,
            created_at=now - timedelta(days=1),
            # Exactly one due occurrence by construction: the pinned :00
            # instant, never more than an hour old, with the cursor just
            # below it.
            last_fired_at=due_at - timedelta(minutes=1),
            next_due_at=due_at,
        )
        await PgScheduleStore(pool).put(schedule)
        admitter = ScheduleRunAdmitter(
            PgRunStore(pool, project_store=projects), templates, PgScheduleStore(pool)
        )
        admission = await admitter.admit_due(schedule, now=now)
        return {
            "run_ids": list(admission.run_ids),
            "already_fired": [str(o) for o in admission.already_fired],
            "failures": [str(e) for e in admission.failures],
            "skipped": [str(s) for s in admission.skipped],
            "schedule_id": schedule.schedule_id,
        }
    finally:
        await pool.close()


# ────────────────────────────── load generator ──────────────────────────────


class LoadStats:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.counts: dict[str, int] = {}
        self.latencies: dict[str, list[float]] = {}
        self.status_codes: dict[int, int] = {}
        self.kind_status_codes: dict[str, dict[int, int]] = {}
        self.run_ids: set[str] = set()
        self.errors: list[str] = []

    async def record(self, kind: str, status: int, latency: float, run_id: str | None) -> None:
        async with self.lock:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.latencies.setdefault(kind, []).append(latency)
            self.status_codes[status] = self.status_codes.get(status, 0) + 1
            by_kind = self.kind_status_codes.setdefault(kind, {})
            by_kind[status] = by_kind.get(status, 0) + 1
            if run_id:
                self.run_ids.add(run_id)

    async def snapshot(self) -> dict[str, dict[Any, int]]:
        """Return one lock-consistent request counter snapshot.

        Kill-window checks must not infer a window from totals collected before
        and after concurrent workers mutate them.  This snapshot is deliberately
        counters only, keeping the four-hour run's latency samples out of the
        recovery bookkeeping.
        """
        async with self.lock:
            return {
                "counts": dict(self.counts),
                "status_codes": dict(self.status_codes),
                "kind_status_codes": {
                    kind: dict(counts) for kind, counts in self.kind_status_codes.items()
                },
            }


def _counter_delta(after: dict[Any, int], before: dict[Any, int]) -> dict[Any, int]:
    """Return non-negative counter increments between two snapshots."""
    return {key: max(after.get(key, 0) - before.get(key, 0), 0) for key in after | before}


def _check_ok(check: Any) -> bool:
    """Read a boolean check, accepting detail dictionaries without truthiness bugs."""
    return check.get("ok", False) if isinstance(check, dict) else check is True


def _integer_or_invalid(value: Any) -> int:
    """Parse a database count, returning an invalid sentinel on probe failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def failed_promotion_checks(evidence: dict[str, Any]) -> list[str]:
    """Return every failed promotion gate represented by an evidence document.

    Keep this pure so the CLI cannot accidentally report success because a new
    threshold was recorded but omitted from its process exit status.
    """
    checks = evidence.get("thresholds", {}).get("checks", {})
    required = (
        "exactly_once_task_admission",
        "exactly_once_schedule_occurrence",
        "rate_limit_enforced",
        "lb_failover_bounded",
        "replica_2_rejoined",
        "nonterminal_runs_after_settle",
        "task_admission_availability",
        "sustain_duration",
    )
    failed = [name for name in required if not _check_ok(checks.get(name))]
    drain = checks.get("graceful_drain")
    if not isinstance(drain, dict):
        # Hardening from the round-4 verify: a doc that omits the key entirely
        # used to bypass this gate because only `required`-flagged dicts were
        # inspected. The driver always writes the key (required = SIGTERM was
        # selected), so a missing record means the evidence predates the
        # drain probe or was hand-edited — either way it cannot sign a
        # promotion. A SIGKILL-mode run still passes by recording
        # {"required": false} explicitly.
        failed.append("graceful_drain")
    elif drain.get("required") and not _check_ok(drain):
        failed.append("graceful_drain")
    return failed


async def drive_load(
    base: str,
    headers: dict[str, str],
    stats: LoadStats,
    stop_at: float,
    rps: float,
    workers: int,
    mix: list[tuple[str, float]],
) -> None:
    # One pooled client shared by every worker: the driver itself must model
    # the connection-reuse a real client population exhibits, and building a
    # private httpx client here would bypass the transport seam the security
    # inventory counts on.
    async with shared_client(timeout=10.0) as client:
        await asyncio.gather(
            *[
                _worker_with_client(client, base, headers, stats, stop_at, mix, rps, i)
                for i in range(workers)
            ]
        )


async def _worker_with_client(
    client: Any,
    base: str,
    headers: dict[str, str],
    stats: LoadStats,
    stop_at: float,
    mix: list[tuple[str, float]],
    rps: float,
    worker_id: int,
) -> None:
    import random

    rng = random.Random(worker_id)
    kinds, weights = zip(*mix, strict=True)
    interval = 1.0 / rps
    seq = worker_id * 100_000
    while time.monotonic() < stop_at:
        kind = rng.choices(kinds, weights=weights, k=1)[0]
        await one_request_with(client, base, headers, kind, stats, seq)
        seq += 1
        await asyncio.sleep(interval * rng.uniform(0.5, 1.5))


async def one_request_with(
    client: Any,
    base: str,
    headers: dict[str, str],
    kind: str,
    stats: LoadStats,
    seq: int,
) -> None:
    import httpx

    start = time.monotonic()
    status, run_id = 0, None
    try:
        if kind == "health_ready":
            r = await client.get(f"{base}/health/ready", headers=headers)
            status = r.status_code
        elif kind == "health_live":
            r = await client.get(f"{base}/health/live")
            status = r.status_code
        elif kind == "task_submit":
            r = await client.post(
                f"{base}/tasks",
                headers={**headers, "Idempotency-Key": f"soak-{uuid.uuid4().hex}"},
                json={"description": f"soak load task {seq}"},
            )
            status = r.status_code
            if r.status_code == 202:
                body = r.json()
                run_id = body.get("run_id")
        elif kind == "run_get":
            r = await client.get(f"{base}/tasks/task-soak-{seq % 500}", headers=headers)
            status = r.status_code
        elif kind == "metrics_unauth":
            r = await client.get(f"{base}/metrics")
            status = r.status_code
    except httpx.HTTPError:
        status = -1
    except Exception:
        status = -2
    await stats.record(kind, status, time.monotonic() - start, run_id)


# ────────────────────────────── evidence phases ─────────────────────────────


async def phase_exactly_once_tasks(base: str, headers: dict[str, str], n: int) -> dict[str, Any]:
    """N concurrent identical submissions (same Idempotency-Key) through the LB."""

    key = f"soak-eo-{uuid.uuid4().hex}"
    run_ids: list[Any] = []
    statuses: list[int] = []

    async def submit(client: Any) -> None:
        try:
            r = await client.post(
                f"{base}/tasks",
                headers={**headers, "Idempotency-Key": key},
                json={"description": "exactly-once probe task"},
            )
            statuses.append(r.status_code)
            if r.status_code == 202:
                run_ids.append(r.json().get("run_id"))
        except Exception as exc:
            statuses.append(-1)
            run_ids.append(str(exc)[:80])

    async with shared_client(timeout=15.0) as client:
        await asyncio.gather(*(submit(client) for _ in range(n)))

    distinct = {r for r in run_ids if isinstance(r, str)}
    delivered = sum(1 for s in statuses if s in (200, 202, 409))
    if len(distinct) <= 1 and delivered == len(statuses):
        cause = "ok"
    elif len(distinct) <= 1:
        # Reproduced in the repair-round mini soak: 4 of 6 duplicate
        # submissions died as LB 502s (the F3 storm) while the 2 delivered
        # agreed on one run_id. The strict gate stays failed — the probe did
        # not exercise 6-way concurrency — but the evidence must say whether
        # that is because duplicates were refused or because the LB never
        # delivered the requests.
        cause = "transport-degraded (LB 5xx): exactly-once unproven, not falsified"
    else:
        cause = "duplicate-or-refused run ids across concurrent submissions"
    return {
        "concurrent_submissions": n,
        "statuses": statuses,
        "delivered": delivered,
        "cause": cause,
        "distinct_run_ids": sorted(distinct),
        "duplicate_run_ids": len(run_ids) - len(distinct) - run_ids.count(None),
        "ok": len(distinct) <= 1 and all(s in (200, 202, 409) for s in statuses),
    }


async def phase_rate_limit(
    lb: str, replica_direct: str, headers: dict[str, str], total: int, burst_budget: int
) -> dict[str, Any]:
    """Burst unauthenticated + authenticated traffic; 429 must hold per replica.

    The budget parameter is `burst_budget`, not `burst`: the inner burst
    coroutine is named `burst` and silently shadowed the parameter, which
    crashed the phase at evidence-assembly time (`int <= function`) on the
    first round-5 validation run.
    """

    async def burst(target: str, auth: bool, n: int) -> dict[str, Any]:
        counts: dict[int, int] = {}
        retry_after: str | None = None
        async with shared_client(timeout=5.0) as client:
            for _ in range(n):
                try:
                    # /health is deliberately exempt from the limiter
                    # (rate_limit.py), so the probe targets a rate-limited
                    # path; authz runs after the limiter, so an
                    # unauthenticated burst still exercises it.
                    r = await client.get(
                        f"{target}/tasks",
                        headers=headers if auth else {},
                    )
                    counts[r.status_code] = counts.get(r.status_code, 0) + 1
                    if r.status_code == 429 and retry_after is None:
                        retry_after = r.headers.get("retry-after")
                        ratelimit_headers = {
                            k: v
                            for k, v in r.headers.items()
                            if k.lower().startswith("x-ratelimit")
                        }
                    else:
                        ratelimit_headers = {}
                except Exception:
                    counts[-1] = counts.get(-1, 0) + 1
        return {
            "target": target,
            "authenticated": auth,
            "requests": n,
            "status_counts": {str(k): v for k, v in sorted(counts.items())},
            "retry_after": retry_after,
            "ratelimit_headers": ratelimit_headers,
        }

    lb_unauth = await burst(lb, auth=False, n=total)
    lb_auth = await burst(lb, auth=True, n=total)
    direct_unauth = await burst(replica_direct, auth=False, n=total)
    probes = (lb_unauth, lb_auth, direct_unauth)
    limited = all(
        b["status_counts"].get("429", 0) > 0 and b["retry_after"] is not None for b in probes
    )
    return {
        "through_lb_unauthenticated": lb_unauth,
        "through_lb_authenticated": lb_auth,
        "direct_replica_unauthenticated": direct_unauth,
        "enforced_everywhere": limited,
        # The round-4 preflight recorded enforced_everywhere=false with a
        # 20-request probe against a burst budget of 60: no burst smaller
        # than the budget can observe the limiter, so an undersized probe is
        # a probe-design fact that must travel with the verdict. The gate
        # itself stays strict — an undersized probe fails H3, it does not
        # silently count as a pass.
        "probe_requests": total,
        "rate_limit_burst": burst_budget,
        "probe_below_burst": total <= burst_budget,
    }


async def _terminalize_probe_run(dsn: str, run_id: str) -> str:
    """Cancel the claim probe's Run through the canonical store, not SQL.

    The probe races *admission*; nothing executes its Run (the racer
    processes exit after admit_due). Left alone it stays QUEUED forever and
    every later run's H5 count inherits it as debt. Cancelling through
    PgRunStore (QUEUED→CANCELLED is a legal transition, lifecycle.py) keeps
    the lifecycle table authoritative — the cleanup is recorded in the
    evidence instead of being invisible. Only ever called after the H2
    verification has counted the rows; a failed race must preserve the
    duplicate rows for forensics.
    """
    import asyncpg

    from maistro.runs.model import RunStatus
    from maistro.runs.pg_store import PgRunStore

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    assert pool is not None
    try:
        run = await PgRunStore(pool).transition_run(
            run_id,
            RunStatus.CANCELLED,
            error="soak claim probe: admission race verified, execution out of probe scope",
        )
        return run.status.value
    finally:
        await pool.close()


async def phase_claim_probe(python: str, dsn: str) -> dict[str, Any]:
    """Two OS processes race to claim the same due schedule occurrence.

    Async so the verified probe Run can be terminalized on the driver's own
    loop (the H2 SQL verdict is computed first; see probe_run_cleanup).
    """
    workspace = f"soak-claim-{uuid.uuid4().hex[:12]}"
    # Pin the occurrence: the most recent hourly :00, strictly in the past,
    # identical for both racers (see _claim_one).
    due_at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0).isoformat()
    procs = [
        subprocess.Popen(
            [
                python,
                str(Path(__file__).resolve()),
                "--claim-probe",
                dsn,
                workspace,
                "--claim-due-at",
                due_at,
            ],
            cwd=REPO,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        try:
            results.append(json.loads(out.strip().splitlines()[-1]))
        except Exception:
            results.append({"error": (out[-400:] + err[-400:])})
    ok_results = [res for res in results if "run_ids" in res]
    admitted_runs = [r for res in ok_results for r in res["run_ids"]]
    already = [res.get("already_fired", []) for res in ok_results]
    failures = [f for res in ok_results for f in res.get("failures", [])]
    schedule_ids = {res.get("schedule_id") for res in ok_results if res.get("schedule_id")}

    # Per-occurrence verification against the durable occurrence claim
    # (migration 015/016: (schedule_id, scheduled_for) is the occurrence
    # identity, with a unique expression index). Counting total run_ids, as
    # the first version did, cannot distinguish "one occurrence claimed
    # once" from "two occurrences, one skipped" — the gate below counts
    # physical Runs per occurrence instead.
    duplicate_rows = 0
    occurrence_rows = 0
    if len(schedule_ids) == 1:
        schedule_id = schedule_ids.pop()
        quoted = schedule_id.replace("'", "''")
        rows = pg_sql(
            "SELECT coalesce(string_agg(n::text, ','), '') FROM ("
            "SELECT count(*) AS n FROM canonical_runs WHERE "
            "payload -> 'provenance' ->> 'schedule_id' = '" + quoted + "' "
            "GROUP BY payload -> 'provenance' ->> 'scheduled_for') t"
        )
        if not rows.startswith("__error__"):
            counts = [int(x) for x in rows.split(",") if x.strip()]
            occurrence_rows = len(counts)
            duplicate_rows = sum(1 for n in counts if n > 1)

    race_verified = (
        len(admitted_runs) == 1
        and occurrence_rows == 1
        and duplicate_rows == 0
        and sum(len(a) for a in already) == 1
        and not failures
    )
    # H2 is decided on the rows above; the cleanup below is evidence hygiene
    # and must not run when the race failed (duplicate rows are forensic
    # evidence) or when the SQL view disagreed (nothing verified to clean).
    cleanup: dict[str, Any] = {"attempted": False, "reason": "race not verified"}
    if len(admitted_runs) == 1 and occurrence_rows == 1 and duplicate_rows == 0:
        cleanup = {"attempted": True, "run_id": admitted_runs[0]}
        try:
            cleanup["terminal_status"] = await _terminalize_probe_run(dsn, admitted_runs[0])
        except Exception as exc:
            cleanup["error"] = str(exc)[:200]

    return {
        "workspace": workspace,
        "due_at": due_at,
        "processes": results,
        "runs_created_for_occurrence": len(admitted_runs),
        "occurrences_with_runs": occurrence_rows,
        "occurrences_with_multiple_runs": duplicate_rows,
        "duplicate_claims_reported": sum(len(a) for a in already),
        "admission_failures": failures,
        "probe_run_cleanup": cleanup,
        # The pinned window holds exactly one occurrence, so both views must
        # agree: exactly one physical Run exists, it is the only occurrence
        # with runs, the loser saw it as already_fired, and nobody failed.
        "ok": race_verified if len(ok_results) == 2 else False,
    }


# ─────────────────────────────────── main ───────────────────────────────────


def collect_hashes(
    out_dir: Path, rate_per_min: int, burst: int, fresh_db: bool, gateway_ip: str | None
) -> dict[str, Any]:
    head = sh(["git", "rev-parse", "HEAD"], cwd=REPO).stdout.strip()
    diff = sh(["git", "diff", "HEAD"], cwd=REPO).stdout
    status = sh(["git", "status", "--porcelain"], cwd=REPO).stdout
    version = (REPO / "VERSION").read_text().strip() if (REPO / "VERSION").exists() else ""
    soak_cfg = {
        "rate_limit_per_minute": rate_per_min,
        "rate_limit_burst": burst,
        "allow_unsafe_resource_overrides": True,
        "api_keys": [SOAK_API_KEY],
        # Part of the config identity: --no-fresh-db evidence carries prior
        # runs' rows, so the hash must distinguish it from a fresh-database
        # run whose counts measure exactly that run.
        "fresh_db": fresh_db,
    }
    rendered = out_dir / "nginx-soak-rendered.conf"
    return {
        "git_head": head,
        "git_diff_sha256": sha256_text(diff),
        "git_status_sha256": sha256_text(status),
        "git_clean": status.strip() == "",
        "version": version,
        "postgres_image": pg_image_digest(),
        "nginx_conf_sha256": sha256_text((REPO / "scripts/soak/nginx-soak.conf").read_text()),
        # The conf actually mounted, after IPv4 rendering (see
        # resolved_host_gateway_ipv4 for why the rendered literal, not the
        # dual-address name, is the identity that matters).
        "nginx_rendered_conf_sha256": (
            sha256_text(rendered.read_text()) if rendered.exists() else None
        ),
        "host_gateway_ipv4": gateway_ip,
        "soak_env_sha256": sha256_text(json.dumps(soak_cfg, sort_keys=True)),
        "python": sys.version.split()[0],
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def boot_stack(
    args: argparse.Namespace,
) -> tuple[dict[str, subprocess.Popen[Any]], dict[str, str]]:
    """Postgres + migrations + two replicas + nginx LB; returns procs and env."""
    ensure_postgres()
    if args.fresh_db:
        reset_db_schema()
    run_migrations()
    env1 = replica_env(
        18201, args.pool_size, args.max_overflow, args.rate_limit_per_minute, args.rate_limit_burst
    )
    env2 = replica_env(
        18202, args.pool_size, args.max_overflow, args.rate_limit_per_minute, args.rate_limit_burst
    )
    procs: dict[str, subprocess.Popen[Any]] = {}
    procs["replica_1"] = start_replica(18201, Path(args.out_dir), env1)
    procs["replica_2"] = start_replica(18202, Path(args.out_dir), env2)
    # /health/live is the RC image's own healthcheck surface; /health/ready
    # stays 503 while the LLM circuit is open (no LiteLLM in the soak cell),
    # which is degraded-not-dead by design. Boot is a known slow path (the root
    # compose sets start_period: 300s for it), so the window is generous and
    # its duration is recorded as evidence.
    boot_t0 = time.monotonic()
    ok1, ok2 = await asyncio.gather(
        wait_ready("replica_1", "http://127.0.0.1:18201/health/live", procs["replica_1"], 420),
        wait_ready("replica_2", "http://127.0.0.1:18202/health/live", procs["replica_2"], 420),
    )
    boot_seconds = round(time.monotonic() - boot_t0, 1)
    log(f"replica boot completed in {boot_seconds}s (r1={ok1}, r2={ok2})")
    if not (ok1 and ok2):
        for p in procs.values():
            kill_replica(p)
        # A "cleaned up" replica that still serves is worse than one that
        # crashed: the next boot fails on the bound port and mid-run evidence
        # keeps flowing from a process the harness believes dead. Fail loudly
        # instead of leaving an orphan.
        orphans = [port for port in (18201, 18202) if not port_closed(port)]
        if orphans:
            raise RuntimeError(
                f"replicas failed to become ready (r1={ok1}, r2={ok2}) and "
                f"orphaned servers still accept on ports {orphans}"
            )
        raise RuntimeError(f"replicas failed to become ready (r1={ok1}, r2={ok2})")
    log("both replicas ready")

    start_nginx(Path(args.out_dir))
    oklb = await wait_ready("lb", f"http://127.0.0.1:{LB_PORT}/health/live", None, 60)
    if not oklb:
        raise RuntimeError("LB did not become ready")
    log("nginx LB ready")
    return procs, {"env2": env2, "boot_seconds": boot_seconds}


async def drain_replica(
    victim: subprocess.Popen[Any],
    stats: LoadStats,
    kill_record: dict[str, Any],
    status_before: dict[int, int],
    t_send: float,
) -> None:
    """Graceful-drain bookkeeping for a SIGTERM'd replica.

    Uvicorn owns SIGTERM and composes through the lifespan shutdown with
    SHUTDOWN_DRAIN_TIMEOUT (maistro_server.main, 30s). The replica must exit
    cleanly inside that window while the survivor takes the traffic — not be
    abandoned mid-request. A timeout here is a failed drain: escalate to
    SIGKILL and record it; never leave an orphan serving.
    """
    drain_deadline = t_send + SHUTDOWN_DRAIN_TIMEOUT_S + 15
    while time.monotonic() < drain_deadline and victim.poll() is None:
        await asyncio.sleep(0.5)
    drained = victim.poll() is not None
    drain_seconds = round(time.monotonic() - t_send, 1)
    status_after = (await stats.snapshot())["status_codes"]
    kill_record.update(
        {
            "drained": drained,
            "drain_seconds": drain_seconds,
            "exit_code": victim.returncode if drained else None,
            "escalated": False,
            "drain_5xx": sum(v for k, v in status_after.items() if k >= 500)
            - sum(v for k, v in status_before.items() if k >= 500),
            "drain_conn_errors": status_after.get(-1, 0) - status_before.get(-1, 0),
        }
    )
    log(
        f"replica_2 drain: exited={drained} after {drain_seconds}s "
        f"rc={victim.returncode} 5xx={kill_record['drain_5xx']} "
        f"conn_err={kill_record['drain_conn_errors']}"
    )
    if not drained:
        kill_replica(victim)
        kill_record["escalated"] = True
        await asyncio.sleep(2.0)


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    # Before anything fetches: boot_stack's readiness probes go through the
    # pooled, policy-guarded seam, so the loopback origins must be registered
    # first or every probe is refused by the outbound policy (default deny).
    allow_soak_origins()
    # Before the first pooled client is built: the load workers share one
    # 64-connection pool instead of building private clients (the shape the
    # constructor census refuses).
    configure_shared_http(max_connections=64)
    evidence: dict[str, Any] = {
        "issue": "860",
        "profile": "M3-A multi-replica load/concurrency soak",
        "started_at": datetime.now(UTC).isoformat(),
    }
    evidence["hashes"] = collect_hashes(
        Path(args.out_dir),
        args.rate_limit_per_minute,
        args.rate_limit_burst,
        args.fresh_db,
        render_nginx_conf(Path(args.out_dir) / "nginx-soak-rendered.conf"),
    )
    procs, envs = await boot_stack(args)
    env2 = envs["env2"]
    boot_seconds = envs["boot_seconds"]

    lb = f"http://127.0.0.1:{LB_PORT}"
    headers = {"Authorization": f"Bearer {SOAK_API_KEY}"}
    dsn = f"postgresql://maistro:soak@127.0.0.1:{PG_HOST_PORT}/maistro"

    import asyncpg

    pg_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    assert pg_pool is not None

    mix = [
        ("health_ready", 45),
        ("health_live", 20),
        # Sized to the soak cell's measured degraded-executor drain (no
        # LiteLLM: admitted runs take ~10-60 s through the retry path, the
        # 4-worker runner drains < 1 run/s/replica) so the per-principal
        # active-run ceiling backpressures instead of saturating for the
        # whole window (round-5 amendment; 20% kept tripping it within
        # seconds). The ceiling itself is production-untouched: at 8 active
        # root Runs it bounds the queue, which is what makes the H5
        # settle-to-zero contract satisfiable at all.
        ("task_submit", 4),
        ("run_get", 10),
        ("metrics_unauth", 5),
    ]

    metrics_file = open(Path(args.out_dir) / "metrics.jsonl", "w")  # noqa: SIM115
    sustain_started = time.monotonic()
    stop_at = sustain_started + args.sustain_seconds
    stats = LoadStats()
    load_task = asyncio.create_task(
        drive_load(lb, headers, stats, stop_at, args.rps, args.workers, mix)
    )

    kill_at = time.monotonic() + args.sustain_seconds * args.kill_fraction
    restart_delay = args.restart_delay_s
    kill_record: dict[str, Any] = {"scheduled": True}

    async def sampler() -> None:
        # driver_loop_lag_ms is how far the load driver's own event loop
        # overshot its sample sleep — the driver's responsiveness under the
        # full request mix. Replica-side loop health is read from the
        # per-kind latency p95s and the drain record.
        lag_ms = 0.0
        while time.monotonic() < stop_at + 5:
            row = await sample_once(procs, pg_pool)
            row["driver_loop_lag_ms"] = round(lag_ms, 2)
            metrics_file.write(json.dumps(row) + "\n")
            metrics_file.flush()
            t0 = time.perf_counter()
            await asyncio.sleep(args.sample_interval)
            lag_ms = (time.perf_counter() - t0 - args.sample_interval) * 1000

    sample_task = asyncio.create_task(sampler())

    # Kill / restart one replica mid-load.
    async def kill_and_restart() -> None:
        await asyncio.sleep(max(5.0, kill_at - time.monotonic()))
        victim = procs["replica_2"]
        sig = getattr(signal, args.kill_signal)
        counters_before = await stats.snapshot()
        status_before = counters_before["status_codes"]
        t_send = time.monotonic()
        if victim.poll() is None:
            # start_new_session put the `uv run` wrapper in its own session:
            # signal the whole process group, or only the wrapper gets it and
            # the uvicorn child keeps serving (the first run proved exactly
            # that: "rejoined" in under a second).
            os.killpg(os.getpgid(victim.pid), sig)
        killed_ts = datetime.now(UTC).isoformat()
        log(f"{args.kill_signal} replica_2 at {killed_ts}")
        kill_record.update({"killed_at": killed_ts, "signal": args.kill_signal})
        if args.kill_signal == "SIGTERM":
            await drain_replica(victim, stats, kill_record, status_before, t_send)
        else:
            await asyncio.sleep(restart_delay)
        procs["replica_2"] = start_replica(18202, Path(args.out_dir), env2)
        rejoined = await wait_ready(
            "replica_2", "http://127.0.0.1:18202/health/live", procs["replica_2"], 300
        )
        counters_after = await stats.snapshot()
        kill_window_seconds = round(time.monotonic() - t_send, 2)
        kill_record.update(
            {
                "restarted_at": datetime.now(UTC).isoformat(),
                "rejoined": rejoined,
                "window_seconds": kill_window_seconds,
                "window_status_counts": {
                    str(key): value
                    for key, value in sorted(
                        _counter_delta(counters_after["status_codes"], status_before).items()
                    )
                },
                "window_task_status_counts": {
                    str(key): value
                    for key, value in sorted(
                        _counter_delta(
                            counters_after["kind_status_codes"].get("task_submit", {}),
                            counters_before["kind_status_codes"].get("task_submit", {}),
                        ).items()
                    )
                },
            }
        )
        log(f"replica_2 restarted, rejoined={rejoined}")

    kill_task = asyncio.create_task(kill_and_restart())
    await load_task
    # Measure the mixed-load phase itself, not a later restart/drain that can
    # outlast it.  Otherwise a 20-second run whose SIGTERM drain hangs for 45
    # seconds could falsely present as a minute of sustained traffic.
    sustain_seconds = round(time.monotonic() - sustain_started, 2)
    await kill_task
    await sample_task
    metrics_file.close()

    log("sustained phase complete; running exactly-once and rate-limit phases")

    evidence["exactly_once_tasks"] = await phase_exactly_once_tasks(
        lb, headers, args.eo_concurrency
    )
    evidence["exactly_once_schedule_claim"] = await phase_claim_probe(sys.executable, dsn)
    evidence["rate_limit"] = await phase_rate_limit(
        lb, "http://127.0.0.1:18201", headers, args.rate_limit_probe_requests, args.rate_limit_burst
    )
    evidence["kill_restart"] = kill_record
    evidence["replica_boot_seconds"] = boot_seconds
    # Requested time is audit context; observed elapsed time is the promotion
    # contract.  A crashed or stalled driver must never sign a requested
    # four-hour run that did not actually remain under load for four hours.
    evidence["requested_sustain_seconds"] = args.sustain_seconds
    evidence["sustain_seconds"] = sustain_seconds

    # Post-kill recovery state: every task-submitted run must be terminal or
    # explicitly accounted for; nothing may sit non-terminal silently.
    await asyncio.sleep(args.settle_seconds)
    evidence["final_runs_by_status"] = pg_sql(
        "SELECT coalesce(string_agg(status || '=' || n, ' '), 'none') FROM "
        "(SELECT status, count(*) AS n FROM canonical_runs GROUP BY status) t"
    )
    evidence["nonterminal_runs"] = pg_sql(
        "SELECT count(*) FROM canonical_runs WHERE status NOT IN "
        "('completed','failed','cancelled','timed_out')"
    )
    evidence["nonterminal_run_items"] = pg_sql(
        "SELECT coalesce(string_agg(status || ':' || run_id::text, ','), '') FROM canonical_runs "
        "WHERE status NOT IN ('completed','failed','cancelled','timed_out')"
    )
    evidence["duplicate_evidence"] = {
        "runs_sharing_one_task_run_identity": pg_sql(
            "SELECT count(*) FROM (SELECT payload->>'task_id' AS t, count(*) AS n "
            "FROM canonical_runs WHERE payload ? 'task_id' GROUP BY 1 HAVING count(*) > 1) d"
        ),
    }

    # Threshold evaluation (docs/testing/soak/m3a-load-profile.md).
    total_reqs = sum(stats.counts.values())
    kill_window_estimate = restart_delay + 15  # passive-health fail_timeout is 10s
    window_statuses = {
        int(key): value for key, value in kill_record.get("window_status_counts", {}).items()
    }
    window_task_statuses = {
        int(key): value for key, value in kill_record.get("window_task_status_counts", {}).items()
    }
    kill_window_failures = sum(
        value for key, value in window_statuses.items() if key >= 500
    ) + window_statuses.get(-1, 0)
    task_sub_status_outside = {
        key: max(value - window_task_statuses.get(key, 0), 0)
        for key, value in stats.kind_status_codes.get("task_submit", {}).items()
    }
    task_submissions_outside_kill = max(
        stats.counts.get("task_submit", 0) - sum(window_task_statuses.values()), 0
    )
    task_accepted_outside_kill = task_sub_status_outside.get(202, 0)
    # Round-5 amendment: a 429 with Retry-After is designed admission
    # backpressure (the active-root-Run ceiling, #1182, mapped from an
    # escaping-500 by the F9 fix; the request limiter answers the same shape).
    # It counts as available admission machinery; 5xx and connection failures
    # do not, and the 202 count is recorded beside the ratio so a window that
    # is all backpressure cannot masquerade as an accepted-load result.
    task_limited_outside_kill = task_sub_status_outside.get(429, 0)
    available_admissions_outside_kill = task_accepted_outside_kill + task_limited_outside_kill
    task_admission_ratio = round(
        available_admissions_outside_kill / max(task_submissions_outside_kill, 1), 4
    )
    nonterminal_count = _integer_or_invalid(evidence["nonterminal_runs"])
    p95s: dict[str, float] = {}
    for kind, lat in stats.latencies.items():
        if lat:
            p95s[kind] = round(statistics.quantiles(lat, n=20)[18] * 1000, 2)

    thresholds = {
        "requests_total": total_reqs,
        "status_counts": {str(k): v for k, v in sorted(stats.status_codes.items())},
        "kind_counts": dict(sorted(stats.counts.items())),
        "p95_latency_ms": p95s,
        "task_admission_ratio": task_admission_ratio,
        "checks": {
            "exactly_once_task_admission": evidence["exactly_once_tasks"]["ok"],
            "exactly_once_schedule_occurrence": evidence["exactly_once_schedule_claim"]["ok"],
            "rate_limit_enforced": evidence["rate_limit"]["enforced_everywhere"],
            "lb_failover_bounded": {
                "observed_5xx_and_conn_errors": kill_window_failures,
                "observed_window_seconds": kill_record.get("window_seconds"),
                "upper_bound_kill_window": kill_window_estimate,
                "budget": kill_window_estimate * args.rps * args.workers,
                "ok": kill_window_failures <= kill_window_estimate * args.rps * args.workers,
                "note": (
                    "5xx + conn errors only during the measured kill/rejoin window "
                    "must stay within the passive-health budget"
                ),
            },
            "replica_2_rejoined": kill_record.get("rejoined", False),
            # SIGTERM is the default promotion probe.  SIGKILL remains useful
            # for a separate abrupt-failure run, where a graceful drain is not
            # applicable and therefore is not silently counted as a pass.
            "graceful_drain": (
                {
                    "signal": kill_record.get("signal"),
                    "drained": kill_record.get("drained"),
                    "escalated": kill_record.get("escalated"),
                    "drain_seconds": kill_record.get("drain_seconds"),
                    "drain_5xx": kill_record.get("drain_5xx"),
                    "drain_conn_errors": kill_record.get("drain_conn_errors"),
                    "ok": (
                        kill_record.get("drained", False)
                        and not kill_record.get("escalated", True)
                        and (
                            kill_record.get("drain_5xx", 0)
                            + kill_record.get("drain_conn_errors", 0)
                        )
                        <= kill_window_estimate * args.rps * args.workers
                    )
                    if kill_record.get("signal") == "SIGTERM"
                    else False,
                    "required": args.kill_signal == "SIGTERM",
                }
            ),
            "nonterminal_runs_after_settle": {
                "count": nonterminal_count,
                "items": evidence["nonterminal_run_items"],
                "ok": nonterminal_count == 0,
            },
            "task_admission_availability": {
                "accepted_202_outside_kill_window": task_accepted_outside_kill,
                "backpressured_429_outside_kill_window": task_limited_outside_kill,
                "available_outside_kill_window": available_admissions_outside_kill,
                "submissions_outside_kill_window": task_submissions_outside_kill,
                "ratio": task_admission_ratio,
                "ok": task_admission_ratio >= 0.99,
            },
            "sustain_duration": {
                "observed_seconds": sustain_seconds,
                "minimum_seconds": PROMOTION_MIN_SUSTAIN_SECONDS,
                "ok": sustain_seconds >= PROMOTION_MIN_SUSTAIN_SECONDS,
            },
            "rss_growth": _rss_growth(Path(args.out_dir) / "metrics.jsonl"),
            "fd_growth": _fd_growth(Path(args.out_dir) / "metrics.jsonl"),
        },
    }
    evidence["thresholds"] = thresholds
    evidence["finished_at"] = datetime.now(UTC).isoformat()

    out = Path(args.out_dir) / "m3a-soak-evidence.json"
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True))
    log(f"evidence written to {out}")

    for proc in procs.values():
        if proc.poll() is None:
            # The wrapper is a session leader (start_new_session): terminate()
            # would reach only it, so address the group and escalate to
            # SIGKILL like the boot-failure path does.
            kill_replica(proc)
    # Keep the LB's own view of the run (upstream errors, no-live-upstream
    # windows, failover events) before the container is removed: F3 could not
    # be root-caused for two rounds because the LB side of the story was
    # deleted with the container at teardown.
    lb_logs = sh(["docker", "logs", "maistro-soak-lb"])
    lb_log_text = (
        lb_logs.stdout + lb_logs.stderr
        if lb_logs.returncode == 0
        else f"__docker logs unavailable rc={lb_logs.returncode}: {lb_logs.stderr[:200]}"
    )
    (Path(args.out_dir) / "lb.log").write_text(lb_log_text)
    sh(["docker", "rm", "-f", "maistro-soak-lb"])
    with contextlib.suppress(Exception):
        await pg_pool.close()
    return evidence


def _iter_metrics(path: Path) -> list[dict[str, Any]]:
    rows = []
    with open(path) as f:
        for line in f:
            with contextlib.suppress(json.JSONDecodeError):
                rows.append(json.loads(line))
    return rows


def _rss_growth(path: Path) -> dict[str, Any]:
    rows = _iter_metrics(path)
    out: dict[str, Any] = {}
    for name in ("replica_1", "replica_2"):
        series = [
            r[name]["rss_kb"]
            for r in rows
            if name in r and isinstance(r[name], dict) and r[name].get("rss_kb")
        ]
        if len(series) >= 2:
            out[name] = {
                "first_kb": series[0],
                "last_kb": series[-1],
                "max_kb": max(series),
                "growth_pct": round((series[-1] - series[0]) / max(series[0], 1) * 100, 1),
            }
    return out


def _fd_growth(path: Path) -> dict[str, Any]:
    rows = _iter_metrics(path)
    out: dict[str, Any] = {}
    for name in ("replica_1", "replica_2"):
        series = [
            r[name]["fds"]
            for r in rows
            if name in r and isinstance(r[name], dict) and r[name].get("fds")
        ]
        if len(series) >= 2:
            out[name] = {"first": series[0], "last": series[-1], "max": max(series)}
    return out


def claim_probe_cli(dsn: str, workspace: str, due_at: str | None = None) -> None:
    result = asyncio.run(_claim_one(dsn, workspace, due_at))
    print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sustain-seconds", type=int, default=420)
    parser.add_argument("--rps", type=float, default=20.0, help="per-worker request rate")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--pool-size", type=int, default=2)
    parser.add_argument("--max-overflow", type=int, default=3)
    parser.add_argument("--rate-limit-per-minute", type=int, default=120)
    parser.add_argument("--rate-limit-burst", type=int, default=60)
    parser.add_argument("--kill-fraction", type=float, default=0.35)
    parser.add_argument(
        "--kill-signal",
        choices=["SIGKILL", "SIGTERM"],
        default="SIGTERM",
        help="SIGTERM exercises the graceful drain path (SHUTDOWN_DRAIN_TIMEOUT); "
        "SIGKILL is the hard-failure failover probe",
    )
    parser.add_argument("--restart-delay-s", type=float, default=12.0)
    parser.add_argument("--eo-concurrency", type=int, default=12)
    # 800: the profile's phase-5 spec. A probe smaller than the configured
    # burst cannot observe the limiter at all (round-4 preflight used 20
    # against burst=60 and recorded enforced=false); probe sizing is recorded
    # alongside the verdict so an undersized probe is never mistaken for
    # falsification.
    parser.add_argument("--rate-limit-probe-requests", type=int, default=800)
    parser.add_argument(
        "--fresh-db",
        dest="fresh_db",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="reset the dedicated soak database schema before migrations so "
        "every count in the evidence measures exactly this run (default; "
        "--no-fresh-db keeps prior runs' rows and inherits their H5 debt)",
    )
    parser.add_argument("--settle-seconds", type=int, default=120)
    parser.add_argument("--sample-interval", type=float, default=2.0)
    parser.add_argument("--out-dir", default="docs/testing/soak/evidence")
    parser.add_argument("--claim-probe", nargs=2, metavar=("DSN", "WORKSPACE"), default=None)
    parser.add_argument(
        "--claim-due-at",
        dest="claim_due_at",
        default=None,
        metavar="ISO_DATETIME",
        help="pin the due occurrence for --claim-probe (parent passes the same value to both racers)",
    )
    args = parser.parse_args()

    if args.claim_probe:
        claim_probe_cli(args.claim_probe[0], args.claim_probe[1], args.claim_due_at)
        return

    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    evidence = asyncio.run(main_async(args))
    failed = failed_promotion_checks(evidence)
    if failed:
        log(f"FAILED checks: {failed}")
        sys.exit(1)
    log("all hard checks passed")


if __name__ == "__main__":
    main()
