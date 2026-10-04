"""Product-path restart E2E — task admission survives a forced process death.

Evidence for #91 (M3-B1: durable, recoverable task queue). The durable-queue
machinery is pinned at the unit/queue level (`maistro-core` tests/tasks:
admission rehydration, stranded-claim terminalization, terminal-receipt
reconciliation, drain-safe persistence), and #819's SIGTERM suite pins the
shutdown half at the process level. What nothing pinned until now is the
whole product path across a *forced* restart: a real server admits a task
through the real `POST /v1/tasks` door onto a real PostgreSQL spine, the
process is SIGKILLed — no drain, no graceful shutdown, exactly the
forced-failure evidence #91 asks for — and a restarted instance must:

- rehydrate the queued admission through the real lifespan startup recovery
  (`queue.recover(run_store)` in `maistro_server.main`), answering `GET`
  with the *same* task_id and run_id (no duplicate Run, no duplicate
  admission);
- actually execute the recovered task (the executor ran, once), drive it to
  a truthful terminal state on the same canonical Run, and say so — the
  operator sees the `task_recovered` event and the completed receipt;
- on a third instance, show the same terminal outcome through the durable
  operator projection (the canonical Run behind the task, `GET /v1/runs`),
  re-derive the same receipt without executing the task again (recovery is
  idempotent; canonical history is not rewritten or duplicated), and
  reconcile a byte-identical resubmission to the original admission through
  the durable idempotency claim store (#1176).  Task *receipts* are the
  living queue's answer (ADR-018: in-memory queue, best-effort TaskRecord
  rows), so the fresh third process is asked for the Run, not the receipt.

The only seam the drivers substitute is the one `TaskRunner` is constructed
with — `maistro.agents.conductor.run_task`, the same injection point the
#819 SIGTERM suite uses — plus a no-op `TaskRunner.start` on the *first*
instance only, so the scenario has a queued (admitted, not yet dispatched)
task at kill time. The second and third instances run the unmodified app.

Needs `MAISTRO_TEST_PG_DSN` pointed at a migrated PostgreSQL; skips without
one, like every other PostgreSQL-backed test in this repository.
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

#: Generous exit deadline — the #819 suite's value: startup on a cold
#: interpreter plus sandbox-cleanup imports can take tens of seconds.
_EXIT_DEADLINE_S = 90.0

#: How long a restarted server gets to rehydrate, dispatch and complete the
#: recovered task. Startup alone can take tens of seconds; this is not a
#: performance assertion.
_COMPLETE_TIMEOUT_S = 150.0


def _server_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Env for a server subprocess: PostgreSQL spine, auth off, info logs.

    Unlike the #819 suite's env (which strips the database on purpose so the
    in-memory spine is exercised), this suite exists to prove the durable
    spine: `DATABASE_URL` is the input under test and must survive.
    """
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
            "ROUTER_API_KEY": "restart-test-router-key",
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


def _wait_ready(proc: subprocess.Popen[str], port: int, timeout_s: float = 120.0) -> None:
    """Wait until the server accepts TCP connections or the process dies."""
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
    proc: subprocess.Popen[str], deadline_s: float = _EXIT_DEADLINE_S
) -> tuple[int | None, str]:
    """SIGTERM the process; return (returncode, remaining output)."""
    proc.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            rest = proc.stdout.read() if proc.stdout else ""  # type: ignore[union-attr]
            return rc, rest
        time.sleep(0.2)
    return None, ""


def _submit_task(
    port: int, description: str, workspace: str, idempotency_key: str, timeout_s: float = 30.0
) -> dict:
    """Admit one task through the real HTTP door; return the created receipt."""
    payload = json.dumps({"description": description, "workspace": workspace}).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/tasks",
        data=payload,
        headers={"Content-Type": "application/json", "Idempotency-Key": idempotency_key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        assert response.status == 202, response.read()
        return dict(json.loads(response.read()))


def _get_task(port: int, task_id: str, timeout_s: float = 15.0) -> dict:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/v1/tasks/{task_id}", timeout=timeout_s
    ) as response:
        return dict(json.loads(response.read()))


def _get_run(port: int, run_id: str, timeout_s: float = 15.0) -> dict:
    """The canonical Run: the restart-visible, database-backed projection."""
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/v1/runs/{run_id}", timeout=timeout_s
    ) as response:
        return dict(json.loads(response.read()))


def _wait_status(port: int, task_id: str, status: str, timeout_s: float) -> dict:
    """Poll the real API until the receipt reports `status`; return it."""
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            last = _get_task(port, task_id)
        except (urllib.error.URLError, TimeoutError, OSError):
            last = {}
        if last.get("status") == status:
            return last
        time.sleep(0.5)
    raise AssertionError(
        f"task {task_id} never reached {status!r} within {timeout_s:g}s; last receipt: {last}"
    )


@pytest.fixture()
def workspace_root() -> Iterator[Path]:
    """Task workspace root under the platform temp dir (an allowed root)."""
    root = Path(tempfile.gettempdir()) / "maistro-workspace" / "restart-91"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
def pg_dsn() -> str:
    dsn = postgres_dsn()
    if not dsn:
        pytest.skip("MAISTRO_TEST_PG_DSN is unset; the restart E2E needs a real PostgreSQL")
    return dsn


def _run_status(dsn: str, run_id: str) -> tuple[int, str | None]:
    """(row count, status) for one canonical Run, read straight from the spine."""
    import asyncpg

    async def _read() -> tuple[int, str | None]:
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(
                "SELECT count(*) AS n, (SELECT status FROM canonical_runs WHERE run_id = $1) "
                "AS status FROM canonical_runs WHERE run_id = $1",
                run_id,
            )
            return int(row["n"]), row["status"]  # type: ignore[index]
        finally:
            await conn.close()

    import asyncio

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


# The first instance admits only: the lifespan, the API, the admitter and the
# queue are the untouched product path, but the worker pool is not started, so
# the task is still QUEUED (dispatch not yet claimed it) when the process dies.
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

# The restarted instance runs the unmodified app; only the executor seam is
# substituted, so the recovered task executes without an LLM and records its
# own execution (the receipt must never claim work that never ran).
_EXECUTE_DRIVER = """
import asyncio, json

MARKER = {marker!r}

# **_kwargs absorbs the canonical runner-executor wiring (#718): the
# `/tasks` worker calls `conductor.run_task` with `governed_egress`,
# `workspace_id` and `project_id`, so a stub pinned to the pre-#718
# signature failed every recovered task with a TypeError before its
# marker could be written.
async def _execute(request, on_response=None, **_kwargs):
    from maistro.agents.types import ConductorOutput

    with open(MARKER, "a") as fh:
        fh.write(json.dumps({{"description": request.description}}) + "\\n")
    return ConductorOutput(success=True, final_answer="done after restart")

import maistro.agents.conductor as conductor
conductor.run_task = _execute

import uvicorn
from maistro_server.main import app
config = uvicorn.Config(app, host="127.0.0.1", port={port}, log_level="info")
asyncio.run(uvicorn.Server(config).serve())
"""

# The third instance is the stock app: recovery must be idempotent against a
# terminal Run, and nothing may execute again.
_STOCK_DRIVER = """
import asyncio

import uvicorn
from maistro_server.main import app
config = uvicorn.Config(app, host="127.0.0.1", port={port}, log_level="info")
asyncio.run(uvicorn.Server(config).serve())
"""


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_queued_task_survives_sigkill_and_executes_exactly_once_after_restart(
    tmp_path: Path, workspace_root: Path, pg_dsn: str
) -> None:
    """SIGKILL between admission and dispatch; the task must recover, run once."""
    port_admit, port_run, port_replay = _free_port(), _free_port(), _free_port()
    marker = tmp_path / "executions.jsonl"
    description = f"restart-e2e {uuid.uuid4().hex}"
    workspace = str(workspace_root / "ws")
    idempotency_key = f"restart-91-{uuid.uuid4().hex}"

    # ── Instance 1: real admission onto the durable spine, then forced death.
    first = _spawn(
        _ADMIT_ONLY_DRIVER.format(port=port_admit), _server_env({"DATABASE_URL": pg_dsn})
    )
    try:
        _wait_ready(first, port_admit)
        created = _submit_task(port_admit, description, workspace, idempotency_key)
    finally:
        # SIGKILL: no drain, no graceful shutdown — the forced-death evidence
        # this E2E exists to provide. The fire-and-forget receipt writes die
        # with the process; the committed Run must be enough to recover from.
        first.kill()
        first.wait(timeout=30)

    task_id = created["task_id"]
    run_id = created["run_id"]
    assert created["status"] == "queued", created
    assert task_id and run_id, f"admission must name both identities: {created}"
    # The QUEUED Run is committed before the 202 (one admission write), so it
    # is already readable from the spine while the first process is dead.
    run_count, run_status = _run_status(pg_dsn, run_id)
    assert (run_count, run_status) == (1, "queued"), (run_count, run_status)

    # ── Instance 2: the restarted server rehydrates and executes the task.
    second = _spawn(
        _EXECUTE_DRIVER.format(port=port_run, marker=str(marker)),
        _server_env({"DATABASE_URL": pg_dsn}),
    )
    try:
        _wait_ready(second, port_run)
        receipt = _wait_status(port_run, task_id, "completed", _COMPLETE_TIMEOUT_S)
        # Same canonical identities the first instance returned: recovery
        # re-enqueued the original Run; it minted nothing.
        assert receipt["run_id"] == run_id, receipt
        assert receipt["task_id"] == task_id, receipt
        run_count, run_status = _run_status(pg_dsn, run_id)
        assert (run_count, run_status) == (1, "completed"), (run_count, run_status)

        # Graceful stop for the *restarted* instance, so its full output is
        # readable: the operator-visible `task_recovered` event must be there.
        rc, output = _sigterm_and_wait(second)
    finally:
        if second.poll() is None:
            second.kill()
            second.wait(timeout=30)

    assert rc is not None, "restarted server still alive after SIGTERM"
    assert rc == 0 or rc == -signal.SIGTERM, f"unclean exit rc={rc}\n{output[-4000:]}"
    assert "task_recovered" in output, (
        f"restarted server never announced the recovered task:\n{output[-4000:]}"
    )

    # The recovered task genuinely executed — exactly once, on the restarted
    # instance, recorded by the executor itself.
    assert marker.exists(), "executor never ran the recovered task"
    executions = [json.loads(line) for line in marker.read_text().splitlines() if line.strip()]
    assert executions == [{"description": description}], executions

    # ── Instance 3: recovery is idempotent; history is neither duplicated nor
    # rewritten; the admission claim still reconciles the resubmission.
    third = _spawn(_STOCK_DRIVER.format(port=port_replay), _server_env({"DATABASE_URL": pg_dsn}))
    try:
        _wait_ready(third, port_replay)
        # The stock process holds no receipt in memory, and must not need one:
        # the operator reads the terminal state off the canonical Run, which
        # the restart neither duplicated nor rewrote.
        run_summary = _get_run(port_replay, run_id)
        assert run_summary["status"] == "completed", run_summary
        assert run_summary["run_id"] == run_id, run_summary

        # Same key, same payload: the durable claim store (#1176) replays the
        # original admission instead of minting a second task/Run — and the
        # replayed receipt is the drained TaskRecord row (#849), so it says
        # what the work's terminal outcome was, not merely that admission
        # happened.
        resubmitted = _submit_task(port_replay, description, workspace, idempotency_key)
        assert resubmitted["task_id"] == task_id, resubmitted
        assert resubmitted["run_id"] == run_id, resubmitted
        assert resubmitted["status"] == "completed", resubmitted
    finally:
        if third.poll() is None:
            third.kill()
            third.wait(timeout=30)

    node_runs, attempts = _execution_counts(pg_dsn, run_id)
    assert (node_runs, attempts) == (1, 1), (node_runs, attempts)

    # No third-instance resurrection: still exactly one execution.
    executions_after = marker.read_text().splitlines()
    assert len(executions_after) == 1, executions_after
