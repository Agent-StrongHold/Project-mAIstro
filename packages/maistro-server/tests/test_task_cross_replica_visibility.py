"""#1690 E2E — two live replicas share task visibility; failover advances once.

The per-process `TaskQueue` made `GET /v1/tasks/{id}` answerable only by the
replica that accepted the `POST`: behind the production round-robin, every
other replica 404ed. This suite is the closure evidence on the *actual
composition* the issue measured — multiple real maistro-server processes over
one migrated PostgreSQL spine, requests alternated across their ports the way
the load balancer alternates across replicas:

1. a task admitted through replica A is read back — same task_id, run_id and
   state — through replica B, which never saw the `POST` and holds none of
   A's memory; the read is answered from the durable tier (the canonical Run
   committed before admission answered, plus the best-effort TaskRecord row);
2. replica A is SIGKILLed while the task is still QUEUED (claimed by no
   worker); the receipt stays queryable through B afterwards — the accepting
   replica took only its own memory with it;
3. two fresh replicas (C1, C2) recover the same pending task and race it;
   the canonical consumer claim lets exactly one own the physical Attempt —
   one execution, one NodeRun, one Attempt row — and the loser's replica,
   having dropped its unauthoritative receipt, still answers polls with the
   winner's converged truth instead of a stale non-terminal copy;
4. a byte-identical resubmission through the surviving fleet replays the
   original admission (#1176) without executing anything again.

Needs `MAISTRO_TEST_PG_DSN` pointed at a migrated PostgreSQL; skips without
one, like every other PostgreSQL-backed test in this repository. The second
test pins the authorization half on the same durable path: a foreign
principal gets 404s through it, from a differently-keyed replica.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from maistro.testing.postgres import postgres_dsn

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Generous startup deadline — cold interpreter plus app imports take tens of
#: seconds on this suite's siblings, and four processes start in pairs here.
_READY_TIMEOUT_S = 120.0

#: How long the recovered task gets to reach `completed` once the racing
#: runners are released. Startup alone dominates; this is not a perf claim.
_COMPLETE_TIMEOUT_S = 90.0


def _server_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Env for a server subprocess: PostgreSQL spine, auth off by default."""
    env = {
        key: value for key, value in os.environ.items() if key not in ("API_KEYS", "ROUTER_API_KEY")
    }
    env["PYTHONPATH"] = os.pathsep.join(
        (
            str(_REPO_ROOT / "packages" / "maistro-core" / "src"),
            str(_REPO_ROOT / "packages" / "maistro-server" / "src"),
            env.get("PYTHONPATH", ""),
        )
    )
    env.update(
        {
            "ROUTER_API_KEY": "cross-replica-test-router-key",
            "REQUIRE_AUTH": "false",
            "DEBUG": "true",
        }
    )
    if extra:
        env.update(extra)
    return env


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_open(port: int, timeout_s: float = 0.5) -> bool:
    with socket.socket() as sock:
        sock.settimeout(timeout_s)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _spawn(code: str, env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )


def _wait_ready(
    proc: subprocess.Popen[str], port: int, timeout_s: float = _READY_TIMEOUT_S
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""  # type: ignore[union-attr]
            raise AssertionError(f"server process died during startup:\n{output[-4000:]}")
        if _port_open(port):
            return
        time.sleep(0.2)
    proc.kill()
    raise AssertionError(f"server not accepting connections after {timeout_s:g}s")


def _sigterm_and_wait(
    proc: subprocess.Popen[str], deadline_s: float = 90.0
) -> tuple[int | None, str]:
    proc.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            rest = proc.stdout.read() if proc.stdout else ""  # type: ignore[union-attr]
            return rc, rest
        time.sleep(0.2)
    return None, ""


def _request(
    port: int,
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    token: str | None = None,
    idempotency_key: str | None = None,
    timeout_s: float = 20.0,
) -> tuple[int, dict | str | None]:
    """One raw HTTP request; returns (status, decoded body) without raising.

    404 is an *answer* in this suite — the thing the issue measured — so the
    helper never turns one into an exception.
    """
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key is not None:
        # The route reads the key from this header (#1176); without it the
        # resubmission leg would mint a second admission instead of replaying
        # the original one.
        headers["Idempotency-Key"] = idempotency_key
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read()
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return exc.code, body.decode(errors="replace")


def _submit_task(port: int, description: str, workspace: str, idempotency_key: str) -> dict:
    status, body = _request(
        port,
        "POST",
        "/v1/tasks",
        payload={"description": description, "workspace": workspace},
        token=None,
        idempotency_key=idempotency_key,
        timeout_s=30.0,
    )
    assert status == 202, (status, body)
    assert body is not None and "task_id" in body, body
    return dict(body)


def _submit_task_with_token(
    port: int, description: str, workspace: str, token: str
) -> tuple[int, dict | str | None]:
    return _request(
        port,
        "POST",
        "/v1/tasks",
        payload={"description": description, "workspace": workspace},
        token=token,
        timeout_s=30.0,
    )


def _run_status(dsn: str, run_id: str) -> tuple[int, str | None]:
    """(row count, status) for one canonical Run, read straight from the spine."""
    import asyncio

    import asyncpg

    async def _read() -> tuple[int, str | None]:
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(
                "SELECT count(*) AS n, "
                "(SELECT status FROM canonical_runs WHERE run_id = $1) AS status "
                "FROM canonical_runs WHERE run_id = $1",
                run_id,
            )
            return int(row["n"]), row["status"]  # type: ignore[index]
        finally:
            await conn.close()

    return asyncio.run(_read())


def _execution_counts(dsn: str, run_id: str) -> tuple[int, int]:
    """(node_runs, attempts) recorded under one canonical Run."""
    import asyncio

    import asyncpg

    async def _read() -> tuple[int, int]:
        conn = await asyncpg.connect(dsn)
        try:
            node_runs = await conn.fetchval(
                "SELECT count(*) FROM canonical_node_runs WHERE run_id = $1", run_id
            )
            attempts = await conn.fetchval(
                "SELECT count(*) FROM canonical_attempts a "
                "JOIN canonical_node_runs n ON a.node_run_id = n.node_run_id "
                "WHERE n.run_id = $1",
                run_id,
            )
            return int(node_runs), int(attempts)
        finally:
            await conn.close()

    return asyncio.run(_read())


# Replica A admits only: the lifespan, API, admitter and queue are the
# untouched product path, but the worker pool never starts, so its task is
# still QUEUED (claimed by nobody) at kill time.
_ADMIT_ONLY_DRIVER = """
import asyncio

from maistro.tasks.runner import TaskRunner

async def _admission_only(self, *args, **kwargs):
    return None

TaskRunner.start = _admission_only

import uvicorn
from maistro_server.main import app
config = uvicorn.Config(app, host="127.0.0.1", port={port}, log_level="info")
asyncio.run(uvicorn.Server(config).serve())
"""

# Replica B is the stock app: its worker simply has nothing queued, exactly
# like any replica that did not accept the POST. Every read it answers is the
# shared durable path.
_STOCK_DRIVER = """
import asyncio

import uvicorn
from maistro_server.main import app
config = uvicorn.Config(app, host="127.0.0.1", port={port}, log_level="info")
asyncio.run(uvicorn.Server(config).serve())
"""

# The failover replicas recover the pending task during their own startup,
# but their dispatchers wait for the shared release file — so both replicas
# hold a recovered QUEUED receipt at the moment the race starts, and the
# canonical consumer claim, not process timing, decides the single owner.
# The gate is the dispatcher loop, not `start()`: the lifespan awaits
# `start()` (main.py), so a gated start would hold the server's own startup —
# the port would never open for `_wait_ready` — while the dispatcher loop is
# only *scheduled* by `start()`, free to block after the server is listening.
_GATED_EXECUTE_DRIVER = """
import asyncio, os

MARKER = {marker!r}
RELEASE = {release!r}

from maistro.tasks.runner import TaskRunner

_loop = TaskRunner._dispatcher_loop

async def _gated_loop(self, *args, **kwargs):
    while not os.path.exists(RELEASE):
        await asyncio.sleep(0.1)
    await _loop(self, *args, **kwargs)

TaskRunner._dispatcher_loop = _gated_loop

async def _execute(request, **_authority):
    # `main.runner_executor` calls `conductor.run_task` with the Container's
    # governed egress and its workspace/project (#718); the kwargs are the
    # seam's contract, not this test's business. Same swallow the SIGTERM
    # suite uses.
    from maistro.agents.types import ConductorOutput

    with open(MARKER, "a") as fh:
        fh.write(request.description + "\\n")
    await asyncio.sleep(0.5)
    return ConductorOutput(success=True, final_answer="done after failover")

import maistro.agents.conductor as conductor
conductor.run_task = _execute

import uvicorn
from maistro_server.main import app
config = uvicorn.Config(app, host="127.0.0.1", port={port}, log_level="info")
asyncio.run(uvicorn.Server(config).serve())
"""


@pytest.fixture()
def workspace_root() -> Iterator[Path]:
    root = Path(tempfile.gettempdir()) / "maistro-workspace" / "cross-replica-1690"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
def pg_dsn() -> str:
    dsn = postgres_dsn()
    if not dsn:
        pytest.skip("MAISTRO_TEST_PG_DSN is unset; the cross-replica E2E needs a real PostgreSQL")
    return dsn


@pytest.mark.timeout(600)
@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_a_queued_task_is_visible_on_every_replica_and_failover_runs_it_exactly_once(
    tmp_path: Path, workspace_root: Path, pg_dsn: str
) -> None:
    """LB'd create-then-poll, forced death, two-replica recovery race."""
    port_admit, port_reader = _free_port(), _free_port()
    port_failover_a, port_failover_b = _free_port(), _free_port()
    marker = tmp_path / "executions.jsonl"
    release = tmp_path / "release-runners"
    description = f"cross-replica {uuid.uuid4().hex}"
    workspace = str(workspace_root / "ws")
    idempotency_key = f"cross-replica-1690-{uuid.uuid4().hex}"
    env = _server_env({"DATABASE_URL": pg_dsn})

    # ── Replicas A (admitting) and B (reading) over one durable spine.
    # Spawned and awaited one at a time: both wirings run the same
    # ensure-schema DDL, and two concurrent first-time `CREATE INDEX IF NOT
    # EXISTS` can still lose the pg_class race (duplicate relname/relnamespace)
    # and kill a replica at startup — an artifact of the harness, not of the
    # behavior under test.
    procs: list[subprocess.Popen[str]] = []

    def _kill_all() -> None:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=30)

    try:
        reader = _spawn(_STOCK_DRIVER.format(port=port_reader), env)
        procs.append(reader)
        _wait_ready(reader, port_reader)

        admitting = _spawn(_ADMIT_ONLY_DRIVER.format(port=port_admit), env)
        procs.append(admitting)
        _wait_ready(admitting, port_admit)

        created = _submit_task(port_admit, description, workspace, idempotency_key)
        task_id = created["task_id"]
        run_id = created["run_id"]
        assert created["status"] == "queued", created
        assert task_id and run_id, created

        # The load-balanced poll replica B never saw the POST — and B's
        # recovery ran before the task existed, so nothing of it is in B's
        # memory. The 200 here is the durable path the issue asked for.
        status, receipt = _request(port_reader, "GET", f"/v1/tasks/{task_id}")
        assert status == 200, (status, receipt)
        assert receipt is not None
        assert receipt["task_id"] == task_id, receipt
        assert receipt["run_id"] == run_id, receipt
        assert receipt["status"] == "queued", receipt

        # The accepting replica still answers from its live receipt, unchanged.
        status, local = _request(port_admit, "GET", f"/v1/tasks/{task_id}")
        assert status == 200 and local is not None and local["status"] == "queued"

        # Forced death before any worker claimed the task.
        admitting.kill()
        admitting.wait(timeout=30)

        # The receipt outlives the process that accepted it.
        status, after = _request(port_reader, "GET", f"/v1/tasks/{task_id}")
        assert status == 200, (status, after)
        assert after is not None and after["status"] == "queued", after
        assert after["run_id"] == run_id, after

        # ── Two fresh replicas recover the same pending task and race it.
        # Same one-at-a-time startup as above: no concurrent first-boot DDL.
        failover_a = _spawn(
            _GATED_EXECUTE_DRIVER.format(
                port=port_failover_a, marker=str(marker), release=str(release)
            ),
            env,
        )
        procs.append(failover_a)
        _wait_ready(failover_a, port_failover_a)

        failover_b = _spawn(
            _GATED_EXECUTE_DRIVER.format(
                port=port_failover_b, marker=str(marker), release=str(release)
            ),
            env,
        )
        procs.append(failover_b)
        _wait_ready(failover_b, port_failover_b)

        # Both recoveries re-enqueued the task, but neither dispatcher has
        # been released: still QUEUED through every door.
        for port in (port_reader, port_failover_a, port_failover_b):
            status, queued = _request(port, "GET", f"/v1/tasks/{task_id}")
            assert status == 200 and queued is not None, (port, status, queued)
            assert queued["status"] == "queued", queued

        release.touch()
        deadline = time.monotonic() + _COMPLETE_TIMEOUT_S
        poll_ports = (port_reader, port_failover_a, port_failover_b)
        per_replica_200 = dict.fromkeys(poll_ports, 0)
        terminal: dict = {}
        while time.monotonic() < deadline:
            for port in per_replica_200:
                status, body = _request(port, "GET", f"/v1/tasks/{task_id}")
                if status == 200 and body is not None:
                    per_replica_200[port] += 1
                    terminal = body
            if terminal.get("status") == "completed":
                break
            time.sleep(0.5)
        assert terminal.get("status") == "completed", terminal
        assert terminal["run_id"] == run_id, terminal
        # Every door answered 200 at least once during the poll: the
        # round-robin never hit a replica that could not serve the task.
        assert all(counts > 0 for counts in per_replica_200.values()), per_replica_200

        # Exactly one execution: the consumer claim's loser never ran the
        # executor, on either failover replica. Counted per description, not
        # per file: the shared spine's recovery also advances other lanes'
        # pending tasks, and this marker is not entitled to a residue-free
        # world — only to one execution of THIS task.
        assert marker.exists(), "the winner must have executed the task"
        lines = [line for line in marker.read_text().splitlines() if line.strip()]
        assert lines.count(description) == 1, lines

        # The canonical fence, read straight from the spine: one Run, one
        # NodeRun, one Attempt — no duplicate admission, no concurrent
        # physical ownership.
        run_count, run_status = _run_status(pg_dsn, run_id)
        assert (run_count, run_status) == (1, "completed"), (run_count, run_status)
        node_runs, attempts = _execution_counts(pg_dsn, run_id)
        assert (node_runs, attempts) == (1, 1), (node_runs, attempts)

        # Idempotent resubmission through the surviving fleet replays the
        # original admission and executes nothing (#1176).
        replayed = _submit_task(port_failover_a, description, workspace, idempotency_key)
        assert replayed["task_id"] == task_id, replayed
        assert replayed["run_id"] == run_id, replayed
        assert replayed["status"] == "completed", replayed
        lines_after = [line for line in marker.read_text().splitlines() if line.strip()]
        assert lines_after.count(description) == 1, lines_after
    finally:
        _kill_all()


@pytest.mark.timeout(300)
@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_a_foreign_principal_cannot_read_a_task_through_the_durable_tier(
    tmp_path: Path, workspace_root: Path, pg_dsn: str
) -> None:
    """The shared read is scoped to the originating principal, end to end."""
    port = _free_port()
    alice_token = "alice-secret-1690"
    mallory_token = "mallory-secret-1690"
    env = _server_env(
        {
            "DATABASE_URL": pg_dsn,
            "REQUIRE_AUTH": "true",
            "API_KEYS": json.dumps([f"alice:{alice_token}", f"mallory:{mallory_token}"]),
        }
    )
    proc = _spawn(_ADMIT_ONLY_DRIVER.format(port=port), env)
    try:
        _wait_ready(proc, port)
        status, body = _submit_task_with_token(
            port, f"alice only {uuid.uuid4().hex}", str(workspace_root / "auth"), alice_token
        )
        assert status == 202, (status, body)
        task_id = body["task_id"]  # type: ignore[index]

        # The owner reads it back through the same door.
        status, receipt = _request(port, "GET", f"/v1/tasks/{task_id}", token=alice_token)
        assert status == 200 and receipt is not None, (status, receipt)
        assert receipt["task_id"] == task_id

        # A different authenticated principal gets 404s on every read shape —
        # the durable lookup grants nothing the live one would refuse.
        assert _request(port, "GET", f"/v1/tasks/{task_id}", token=mallory_token)[0] == 404
        assert _request(port, "GET", f"/v1/tasks/{task_id}/result", token=mallory_token)[0] == 404
        assert _request(port, "DELETE", f"/v1/tasks/{task_id}", token=mallory_token)[0] == 404

        # And the per-replica listing never hands Alice's work to Mallory.
        status, listing = _request(port, "GET", "/v1/tasks?limit=200", token=mallory_token)
        assert status == 200 and listing is not None
        assert all(item["task_id"] != task_id for item in listing["items"]), listing
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)
